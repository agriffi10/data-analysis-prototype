"""convert: one typed read, three writers, one conditional write, and nothing left on disk.

Driven through `handler`, because the decorator stack is part of the verb — a test calling the
inner function would let the span and the failure notifier be removed with the suite green.
"""

import csv
import io
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import polars as pl
import pytest
from botocore.exceptions import ClientError

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "results-conversion-common"))
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "table-builder-infer-schema"))
sys.path.insert(0, str(_HERE.parent / "table-builder-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_convert as c
from cpcommon import clients
from cpcommon.type_mapping import map_dtype
from rccommon import config as rc_config
from rccommon import parquet_footer

#: One column per mapped dtype, with the text Athena renders for each. The empty and NULL text
#: columns are the pair FR-001 is about: an unquoted empty field is NULL and `""` is a real
#: empty string, and no hand-written expectation can stand in for that distinction.
EVERY_TYPE = (
    ("c_boolean", "boolean", '"true"'),
    ("c_tinyint", "tinyint", '"1"'),
    ("c_smallint", "smallint", '"2"'),
    ("c_integer", "integer", '"3"'),
    ("c_bigint", "bigint", '"4"'),
    ("c_real", "real", '"1.5"'),
    ("c_double", "double", '"2.5"'),
    ("c_date", "date", '"2020-01-02"'),
    ("c_timestamp", "timestamp", '"2020-01-02 03:04:05.123"'),
    ("c_varchar", "varchar", '"hello"'),
    ("c_json", "json", '"{""a"":1}"'),
    ("c_empty", "varchar", '""'),
    ("c_null", "varchar", ""),
)


def _columns(pairs=EVERY_TYPE, decimal=True):
    """The described columns, in the shape describe-results emits."""
    described = [{"name": name, "type": kind} for name, kind, _ in pairs]
    if decimal:
        described.append({"name": "c_decimal", "type": "decimal", "precision": 10, "scale": 2})
    return described


def _csv(pairs=EVERY_TYPE, rows=1, decimal=True):
    """An Athena-shaped result object: every field quoted, NULL written as an unquoted blank."""
    names = [name for name, _, _ in pairs] + (["c_decimal"] if decimal else [])
    header = ",".join(f'"{name}"' for name in names)
    body = ",".join([text for _, _, text in pairs] + (['"1.25"'] if decimal else []))
    return ("\n".join([header, *([body] * rows)]) + "\n").encode()


class FakeS3:
    """S3 for one conversion: a size, a download, a write, and a record of every call."""

    def __init__(self, payload=None, occupied=False, size=None):
        self.payload = payload if payload is not None else _csv()
        self.occupied, self.calls, self.written = occupied, [], []
        self.size = len(self.payload) if size is None else size

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        self._refuse_unless_results_bucket(kwargs["Bucket"], "HeadObject")
        return {"ContentLength": self.size}

    def download_fileobj(self, bucket, key, handle):
        self.calls.append(("download_fileobj", {"Bucket": bucket, "Key": key}))
        self._refuse_unless_results_bucket(bucket, "GetObject")
        handle.write(self.payload)

    def _refuse_unless_results_bucket(self, bucket, operation):
        """Answers the way the execution role's grant does, which is the point of the fake.

        `s3:GetObject` is granted on the USER-SPACE bucket's results prefixes and nowhere else,
        so a read aimed at the shared bucket is an AccessDenied in production. A fake that
        ignored the bucket would be green against a converter reading from the destination —
        which is exactly the bug that shipped past two suites whose fixtures were all personal.
        """
        if bucket != "user-bkt":
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "no grant"}}, operation
            )

    def get_object(self, **kwargs):  # pragma: no cover - reaching this is the failure
        raise AssertionError("the result object must be streamed to disk, never read into memory")

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        if self.occupied and "IfNoneMatch" in kwargs:
            raise _precondition_failed()
        body = kwargs["Body"]
        self.written.append(body.read() if hasattr(body, "read") else body)
        return {}


def _precondition_failed():
    """The error botocore raises when a conditional write meets an existing object."""
    return ClientError({"Error": {"Code": "PreconditionFailed", "Message": "exists"}}, "PutObject")


@pytest.fixture
def s3(tmp_path, monkeypatch):
    """Points the verb at a scratch directory of its own and a fake S3."""
    monkeypatch.setattr(c, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(c.notify, "emit_notification", lambda *a, **kw: None)
    fake = FakeS3()
    clients._s3 = fake
    return fake


def _event(fmt="parquet", on_conflict="refuse", columns=None, filename=None, chosen=None):
    """The described request, as the machine's Described state hands it over.

    `columnIndexes` is always present and is null when the request named no columns, because the
    `Described` Pass state names it and a Pass hard-fails on an absent key.
    """
    name = filename or f"q1.{fmt}"
    return {
        "columnIndexes": chosen,
        "requestId": "req-1",
        "username": "alice",
        "format": fmt,
        "onConflict": on_conflict,
        "queryExecutionId": "11111111-2222-4333-8444-555555555555",
        "resultsKey": "alice/athenaresults/exec.csv",
        "destination": {
            "bucket": "user-bkt",
            "key": f"alice/out/{name}",
            "prefix": "out/",
            "spaceKind": "personal",
            "spaceName": "alice",
        },
        "columns": columns if columns is not None else _columns(),
        "resultsBytes": len(_csv()),
    }


def _uploaded(fake, tmp_path, suffix):
    """Writes what the verb uploaded back to disk, so a reader can be pointed at it."""
    path = tmp_path / f"uploaded{suffix}"
    path.write_bytes(fake.written[0])
    return path


# ── The happy paths, one per format ──────────────────────────────────────────


def test_a_parquet_conversion_writes_one_typed_file_and_reports_its_rows(s3, tmp_path):
    result = c.handler(_event("parquet"), None)

    assert result["outcome"] == "converted" and result["reason"] is None
    assert result["rows"] == 1 and result["bytes"] > 0
    assert result["precisionNote"] is False
    put = next(kwargs for name, kwargs in s3.calls if name == "put_object")
    assert put["ContentType"] == "application/vnd.apache.parquet"
    assert put["IfNoneMatch"] == "*"
    assert "Metadata" not in put, "the SQL, the execution and the actor are not stamped on the object"
    written = _uploaded(s3, tmp_path, ".parquet")
    assert parquet_footer.row_count(written) == 1
    assert parquet_footer.codecs_of(written) == {"zstd"}, (
        "polars' default compression changed; users are now receiving a different file"
    )


def test_a_json_conversion_writes_one_object_per_line_in_column_order(s3, tmp_path):
    result = c.handler(_event("json"), None)

    assert result["outcome"] == "converted" and result["rows"] == 1
    body = s3.written[0].decode()
    assert not body.startswith("["), "NDJSON carries no enclosing array"
    (line,) = [entry for entry in body.split("\n") if entry]
    record = json.loads(line)
    assert list(record) == [column["name"] for column in _columns()]
    assert record["c_boolean"] is True
    assert record["c_bigint"] == 4
    assert record["c_double"] == 2.5
    assert record["c_decimal"] == "1.25", "a decimal is a JSON string; a number would round it"
    assert record["c_date"] == "2020-01-02"
    assert record["c_timestamp"] == "2020-01-02T03:04:05.123000", (
        "ISO-8601 to microseconds with no zone designator; polars' own NDJSON writer emits a "
        "space separator and a variable-width fraction"
    )
    assert record["c_empty"] == "", "a quoted empty field is an empty string"
    assert record["c_null"] is None, "an unquoted empty field is NULL"
    put = next(kwargs for name, kwargs in s3.calls if name == "put_object")
    assert put["ContentType"] == "application/x-ndjson"


def test_an_excel_conversion_writes_one_sheet_with_serials_and_no_formula(s3, tmp_path):
    wide = [*_columns(decimal=False), {"name": "c_formula", "type": "varchar"}]
    event = _event("xlsx", columns=wide)
    payload = _csv(decimal=False)
    header, row = payload.decode().splitlines()
    s3.payload = f'{header},"c_formula"\n{row},"=1+1"\n'.encode()
    s3.size = len(s3.payload)

    result = c.handler(event, None)

    assert result["outcome"] == "converted" and result["rows"] == 1
    workbook = zipfile.ZipFile(io.BytesIO(s3.written[0]))
    sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet and "<f " not in sheet, "a cell must never be a formula"
    assert "<v>43832</v>" in sheet, "a date is written as an Excel serial, not as text"
    assert re.search(r"<v>43832\.\d+</v>", sheet), (
        "and a timestamp is a serial too, carrying its time of day in the fraction"
    )
    assert 't="b"><v>1</v>' in sheet, "a boolean is a boolean cell, not the text 'true'"
    assert "2020-01-02" not in sheet, "no date reached the sheet as text"
    put = next(kwargs for name, kwargs in s3.calls if name == "put_object")
    assert put["ContentType"].endswith("spreadsheetml.sheet")


def test_a_shared_space_destination_still_reads_the_result_from_the_actors_own_space(s3):
    """The two buckets differ only for a SHARED destination, and that is the whole test.

    An execution's result object is always under the actor's own results prefix in the
    user-space bucket; the destination may be a shared space in a different bucket entirely.
    Reading from the destination's bucket is an AccessDenied in production — the read grant does
    not extend there — reported to the user as "something went wrong". Every fixture in this
    file used a personal destination, where the two strings coincide, so the suite agreed with
    a converter that had them the wrong way round.
    """
    shared = {
        "bucket": "shared-bkt",
        "key": "finance/out/q1.parquet",
        "prefix": "out/",
        "spaceKind": "shared",
        "spaceName": "finance",
    }
    result = c.handler({**_event("parquet"), "destination": shared}, None)

    assert result["outcome"] == "converted"
    reads = [kwargs for name, kwargs in s3.calls if name in ("head_object", "download_fileobj")]
    assert {call["Bucket"] for call in reads} == {"user-bkt"}, "the result is read from the actor's space"
    writes = [kwargs for name, kwargs in s3.calls if name == "put_object"]
    assert writes[0]["Bucket"] == "shared-bkt", "and written to the space they chose"


def test_the_formula_guard_would_see_a_workbook_that_evaluated_strings(s3, tmp_path):
    """The plant for the assertion above, and the honest scope of it.

    Only a leading `=` becomes a formula: measured, `+`, `-`, `@`, a tab and a carriage return
    all stay shared strings whatever the workbook option says. So the fixture MUST carry an `=`
    value or the guard proves nothing — and the other five prefixes are inert in `.xlsx` by the
    format rather than by anything this verb does, which is why the assertion above is not
    coverage of them.
    """
    import xlsxwriter

    frame = pl.DataFrame({"s": ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\tx", "\rx"]})
    plain, planted = tmp_path / "plain.xlsx", tmp_path / "planted.xlsx"
    frame.write_excel(plain, worksheet="results")
    book = xlsxwriter.Workbook(planted, {"strings_to_formulas": True})
    frame.write_excel(workbook=book, worksheet="results")
    book.close()

    def sheet(path):
        return zipfile.ZipFile(path).read("xl/worksheets/sheet1.xml").decode()

    assert "<f>" not in sheet(plain)
    assert sheet(planted).count("<f>") == 1, "only the leading-= value is evaluated"
    assert "workbook=" not in (_HERE / "rc_convert.py").read_text(), (
        "the verb must never supply its own workbook: polars' default is the whole guard"
    )


# ── The round trips that make "save it, then build a table from it" compose ──


@pytest.mark.parametrize("fmt", ["parquet", "json"])
def test_the_written_file_reads_back_through_the_table_builders_own_probe(s3, tmp_path, fmt):
    """The property the arc exists for, asserted through table-builder's real inference.

    Parquet round-trips every type. JSON loses five of them, and each loss is the format rather
    than a defect: JSON carries no integer or float width, so the three narrow integers widen to
    `bigint` and `real` to `double`; and `decimal` reads back as `string` because this spec
    REQUIRES it to be written as one, a number having rounded it. `date` and `timestamp` survive
    only through infer-schema's regex over sample values, not because NDJSON carries the type.
    """
    import infer_schema

    reported = {
        column["name"]: map_dtype(c.types.polars_dtype(c.types.athena_type_of(column)))
        for column in _columns()
    }
    # Two rows, the second with the null column filled. An all-NULL column has no type in
    # NDJSON at all — infer-schema reads polars' `Null` and `map_dtype` refuses it — so a
    # single-row fixture would be asserting about a shape the format cannot carry rather than
    # about this writer.
    filled = tuple(
        (name, kind, '"x"' if text == "" else text) for name, kind, text in EVERY_TYPE
    )
    s3.payload = _csv().rstrip(b"\n") + b"\n" + _csv(filled).splitlines()[1] + b"\n"
    s3.size = len(s3.payload)
    c.handler(_event(fmt), None)
    written = _uploaded(s3, tmp_path, f".{fmt}")
    if fmt == "parquet":
        inferred = infer_schema._infer_columns(str(written), "parquet")
    else:
        inferred = infer_schema._infer_columns(io.BytesIO(written.read_bytes()), "json")
    got = {column["name"]: column["type"] for column in inferred}

    assert list(got) == list(reported), "the names and their order must survive either format"
    if fmt == "parquet":
        assert got == reported
        return
    lost = {
        "c_tinyint": "bigint",
        "c_smallint": "bigint",
        "c_integer": "bigint",
        "c_real": "double",
        "c_decimal": "string",
    }
    for name, hive in reported.items():
        assert got[name] == lost.get(name, hive), f"{name} did not survive as expected"
    assert set(lost) & set(got) == set(lost), "the exception list names columns the fixture holds"


# ── The refusals, each a return value rather than a raise ────────────────────


def test_an_unmappable_column_type_is_refused_naming_the_column(s3):
    result = c.handler(_event(columns=[{"name": "shape", "type": "geometry"}]), None)

    assert result["outcome"] == "refused"
    assert result["reason"] == "unsupported_column_type"
    assert result["tokens"] == {"column": "shape"}
    assert s3.written == [], "nothing is written when a column cannot be typed"
    # This verb REPLACES the state, and it has two returns. The converted arm is held by
    # `test_converted_reads_exactly_the_keys_the_convert_verb_returns`; nothing held this one,
    # so removing the key here left the plane green. `Converted` reads `$.traceparent` once
    # FR-004 lands, and this is the arm where the user has already been answered.
    assert result["traceparent"].startswith("00-")


def test_a_value_that_does_not_parse_refuses_without_quoting_the_cell(s3):
    s3.payload = b'"n"\n"not-a-number"\n'
    s3.size = len(s3.payload)

    result = c.handler(_event(columns=[{"name": "n", "type": "bigint"}]), None)

    assert result["outcome"] == "refused" and result["reason"] == "results_unreadable"
    assert s3.written == [], "no partial file is written"


def test_an_unparsed_values_detail_names_its_column_and_no_position(tmp_path):
    """polars' message carries the column and a byte offset, and the offset its streaming reader
    reports is relative to a chunk rather than to the file — so the detail an operator reads
    names the column and quotes no position that would send them to the wrong place."""
    source = tmp_path / "result.csv"
    source.write_bytes(b'"n"\n"not-a-number"\n')

    with pytest.raises(c._Refusal) as refusal:
        c._write_parquet(c._frame(source, {"n": pl.Int64()}), tmp_path / "out.parquet")

    assert refusal.value.reason == "results_unreadable"
    assert refusal.value.detail == "a value in column 'n' did not parse"


def test_an_occupied_destination_is_refused_only_when_the_request_asked_to_be(s3):
    s3.occupied = True
    refused = c.handler(_event("parquet", on_conflict="refuse"), None)
    assert refused["outcome"] == "refused" and refused["reason"] == "destination_occupied"
    assert s3.written == []

    overwritten = c.handler(_event("parquet", on_conflict="overwrite"), None)
    assert overwritten["outcome"] == "converted"
    put = [kwargs for name, kwargs in s3.calls if name == "put_object"][-1]
    assert "IfNoneMatch" not in put, "an overwrite carries no condition"


def _collected_widths(monkeypatch):
    """Records the width of every frame any lazy frame is collected into.

    The refusals below must be decided before the typed frame is materialised, and the count
    they are decided from is itself a collect — of ONE column. So "nothing was collected" is the
    wrong assertion and "every collect was one column wide" is the right one.
    """
    widths = []
    original = pl.LazyFrame.collect

    def recording(self, *args, **kwargs):
        collected = original(self, *args, **kwargs)
        widths.append(collected.width)
        return collected

    monkeypatch.setattr(pl.LazyFrame, "collect", recording)
    return widths


def test_too_many_rows_for_a_spreadsheet_refuses_with_the_count(s3, monkeypatch):
    """Driven against a lowered ceiling rather than a million-row fixture: the guard is the
    comparison, and a fixture large enough to trip the real number would take minutes to build
    and would test polars rather than this. Lowered where the predicate reads it, in
    `rccommon.config`, which is the module both this verb and the budget test ask."""
    monkeypatch.setattr(rc_config, "EXCEL_MAX_ROWS", 2)
    widths = _collected_widths(monkeypatch)
    s3.payload = _csv(rows=3)
    s3.size = len(s3.payload)

    result = c.handler(_event("xlsx"), None)

    assert result["outcome"] == "refused" and result["reason"] == "excel_row_limit"
    assert result["tokens"] == {"count": 3}
    assert s3.written == []
    assert widths == [1], "only the one-column count was collected; the typed frame never was"


def test_too_many_cells_for_a_spreadsheet_refuses_before_the_frame_is_built(s3, monkeypatch):
    """The refusal that would have stopped the production timeout: a result under the byte cap
    and the row ceiling whose CELLS do not fit, refused from the count and the column count."""
    columns = _columns()
    monkeypatch.setattr(rc_config, "EXCEL_MAX_CELLS", 3 * len(columns) - 1)
    widths = _collected_widths(monkeypatch)
    s3.payload = _csv(rows=3)
    s3.size = len(s3.payload)

    result = c.handler(_event("xlsx"), None)

    assert result["outcome"] == "refused" and result["reason"] == "excel_cell_limit"
    assert result["tokens"] == {"rows": 3, "columns": len(columns), "count": 3 * len(columns)}
    assert s3.written == []
    assert widths == [1], "only the one-column count was collected; the typed frame never was"


def test_the_count_is_the_csvs_own_rows(s3, monkeypatch):
    """The count is the CSV's data-row count, not a line count and not an estimate.

    A quoted newline is one row: the file below has two rows over three lines, so it converts
    at a ceiling of two and is refused, naming two, at a ceiling of one — a count of lines
    would say three both times. A header-only file is zero rows, so it converts even at a
    ceiling of zero.
    """
    pairs = (("c_text", "varchar", '"one\nline"'),)
    s3.payload = b'"c_text"\n"one\nline"\n"two"\n'
    s3.size = len(s3.payload)
    event = _event("xlsx", columns=_columns(pairs, decimal=False))

    monkeypatch.setattr(rc_config, "EXCEL_MAX_ROWS", 2)
    assert c.handler(event, None)["outcome"] == "converted"

    monkeypatch.setattr(rc_config, "EXCEL_MAX_ROWS", 1)
    refused = c.handler(event, None)
    assert refused["reason"] == "excel_row_limit" and refused["tokens"] == {"count": 2}

    monkeypatch.setattr(rc_config, "EXCEL_MAX_ROWS", 0)
    s3.payload = b'"c_text"\n'
    s3.size = len(s3.payload)
    assert c.handler(event, None)["outcome"] == "converted"


def _multi_line_payload(rows: int, width: int = 200) -> bytes:
    """A result whose every tenth value is a multi-line JSON document, as Athena quotes it.

    Large enough that polars splits the file across threads, which is where a count that tracks
    quotes chunk by chunk went wrong: under polars 1.12 the fast count read this shape as 3,256
    rows of 5,000.

    **`width` is not decoration.** At 200 characters and 60,000 rows or more, polars 1.12's
    STREAMING reader mis-split this shape — `sink_csv` and `sink_parquet` raised on a whole save
    and a column-subset save wrote fragments as extra rows — on a file Python's own `csv` module
    reads correctly. polars 1.44.2 streams it correctly, and the plane page records the history.
    """
    lines = ['"id","doc"']
    for i in range(rows):
        doc = '{\n  ""k"": 1,\n  ""v"": ""' + "z" * width + '""\n}' if i % 10 == 0 else "{}"
        lines.append(f'"{i}","{doc}"')
    return ("\n".join(lines) + "\n").encode()


def test_a_multi_line_value_across_chunks_is_still_one_row_to_the_count(s3, monkeypatch):
    """The refusal comes from the COUNT, not from the check after the frame is built.

    That is what the width recorder says: only the one-column count was collected. A count that
    miscounted here would admit the file, build the frame, and leave the refusal to the height
    check — correct in its answer and wrong in its cost. It can only miscount where polars runs
    more than one thread, which is every developer machine and the function itself.
    """
    columns = [{"name": "id", "type": "bigint"}, {"name": "doc", "type": "varchar"}]
    s3.payload = _multi_line_payload(5_000)
    s3.size = len(s3.payload)
    monkeypatch.setattr(rc_config, "EXCEL_MAX_ROWS", 4_999)
    widths = _collected_widths(monkeypatch)

    result = c.handler(_event("xlsx", columns=columns), None)

    assert result["reason"] == "excel_row_limit" and result["tokens"] == {"count": 5_000}
    assert widths == [1], "the count refused it, before anything was materialised"


def test_a_count_that_disagrees_with_the_built_frame_is_refused_before_the_write(s3, monkeypatch):
    """The check after the frame is built is the net under the count: a count that admitted a
    result the frame then shows to be over a limit is refused there, never written short."""
    asked = []

    def admits_first(rows, columns):
        asked.append(rows)
        return None if len(asked) == 1 else "excel_row_limit"

    monkeypatch.setattr(c, "excel_refusal", admits_first)
    s3.payload = _csv(rows=3)
    s3.size = len(s3.payload)

    result = c.handler(_event("xlsx"), None)

    assert result["reason"] == "excel_row_limit" and result["tokens"] == {"count": 3}
    assert asked == [3, 3], "asked of the count, then of the built frame's height"
    assert s3.written == []


def test_a_header_that_disagrees_with_the_metadata_is_a_fault_not_a_silent_rename(s3):
    """polars renames columns to the override keys and applies types POSITIONALLY when the
    header does not match, with no error at all — so the disagreement has to be caught here or
    the user receives a file whose columns are labelled wrongly."""
    s3.payload = b'"x","y"\n"1","2"\n'
    s3.size = len(s3.payload)

    with pytest.raises(RuntimeError, match="metadata named"):
        c.handler(
            _event(columns=[{"name": "a", "type": "bigint"}, {"name": "b", "type": "bigint"}]), None
        )


# ── The properties that hold across every path ───────────────────────────────


def test_an_empty_result_set_writes_a_file_with_the_schema_and_no_rows(s3, tmp_path):
    s3.payload = _csv(rows=0)
    s3.size = len(s3.payload)

    parquet = c.handler(_event("parquet"), None)
    assert parquet["rows"] == 0
    assert parquet_footer.row_count(_uploaded(s3, tmp_path, ".parquet")) == 0
    assert pl.read_parquet_schema(_uploaded(s3, tmp_path, ".parquet"))

    s3.written.clear()
    as_json = c.handler(_event("json"), None)
    assert as_json["rows"] == 0 and s3.written[0] == b"", "an empty result is a zero-byte .json"


def test_the_result_object_is_streamed_to_disk_and_read_exactly_once(s3):
    c.handler(_event("parquet"), None)

    reads = [name for name, _ in s3.calls if name in ("download_fileobj", "get_object")]
    assert reads == ["download_fileobj"], "read once, to a file, never into memory"
    assert [name for name, _ in s3.calls].count("head_object") == 1


def test_a_result_that_grew_past_the_cap_since_it_was_described_is_a_fault(s3):
    s3.size = c.max_result_bytes("parquet") + 1

    with pytest.raises(RuntimeError, match="grew to"):
        c.handler(_event("parquet"), None)
    assert s3.written == []


def test_the_streamed_writers_never_materialise_the_frame(s3, monkeypatch):
    """The behavioural form of FR-001's streaming rule, and the reason it is behavioural.

    An AST sweep over two named functions cannot see a `collect()` in a helper they call, so it
    would pass on exactly the refactor that breaks the property. Making the calls themselves
    raise closes the whole class: if either streamed path materialises anything, anywhere, by
    any route, the conversion fails rather than quietly succeeding on a smaller fixture.

    Excel is deliberately left unpatched — it CANNOT stream, which is why its size cap is set by
    memory instead of by the disk.

    **CSV is the one streamed format that collects anything**, and the guard had to change shape
    to admit it: its row count is a projected read of the file it wrote, which cannot leave a
    LazyFrame without a `collect`. Refusing every `collect` outright would have forbidden an
    honest count; admitting "a 1x1 result" would have admitted the WRONG count just as readily,
    since polars' fast count collects a 1x1 frame too. So the guard records widths instead
    and holds Parquet and JSON to collecting NOTHING, which is strictly what they did before.
    """

    def refuse(*args, **kwargs):
        raise AssertionError("a streamed conversion materialised the frame")

    monkeypatch.setattr(pl, "read_csv", refuse)

    widths = _collected_widths(monkeypatch)
    assert c.handler(_event("parquet"), None)["outcome"] == "converted"
    assert c.handler(_event("json"), None)["outcome"] == "converted"
    assert widths == [], "neither Parquet nor JSON collects anything at all"

    assert c.handler(_event("csv"), None)["outcome"] == "converted"
    assert widths == [1], (
        "a CSV conversion collects exactly one thing, one column wide: the row count. The WIDTH "
        "is all this can see — `pl.len()` and `pl.first().len()` both collect a 1x1 frame, and on "
        "polars 1.44.2 both count right — so what is held is the count itself, to the row, by "
        "`test_a_csv_conversions_row_count_is_right_on_a_file_the_reader_splits`"
    )


def test_the_scratch_disk_is_empty_when_the_next_conversion_starts(s3):
    """A warm container is reused, and a conversion killed by the function's own timeout never
    runs its cleanup — so the entry sweep is what makes the second request's disk budget real."""
    c.handler(_event("parquet"), None)
    assert list(c.SCRATCH_ROOT.iterdir()) == [], "the request's directory is removed on the way out"

    stale = c.SCRATCH_ROOT / "left-behind"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "huge.csv").write_bytes(b"x" * 1024)
    seen = {}
    original = c._download

    def watching(bucket, key, target, fmt, described_bytes):
        seen["contents"] = sorted(p.name for p in c.SCRATCH_ROOT.iterdir())
        return original(bucket, key, target, fmt, described_bytes)

    c._download = watching
    try:
        c.handler(_event("parquet"), None)
    finally:
        c._download = original
    assert seen["contents"] == ["request"], "a previous request's bytes survived into this one"


def test_the_scratch_path_cannot_be_steered_by_the_request_id(s3):
    """The request id is the CALLER's string, and the route validator is shape-only by design.

    `Path / "../x"` walks out of the root and `Path / "/tmp/x"` replaces it outright, either of
    which puts the working directory somewhere the entry sweep above will never find — so a run
    killed by the function's own timeout would leave bytes behind that accumulate until the
    10 GB disk is full and every later conversion in that container fails on the download.
    The directory therefore carries no part of the id at all.
    """
    for hostile in ("../escaped", "/tmp/absolute-escape", "a/b/c"):  # noqa: S108
        s3.calls.clear()
        result = c.handler({**_event("parquet"), "requestId": hostile}, None)
        assert result["outcome"] == "converted"
        assert list(c.SCRATCH_ROOT.iterdir()) == [], "nothing is left inside the root"
        assert not (c.SCRATCH_ROOT.parent / "escaped").exists()
        assert not pathlib.Path("/tmp/absolute-escape").exists()  # noqa: S108


def test_a_refusal_leaves_the_disk_clean_too(s3):
    c.handler(_event(columns=[{"name": "shape", "type": "geometry"}]), None)
    assert list(c.SCRATCH_ROOT.iterdir()) == []


def test_the_precision_sentence_is_earned_by_the_frame_rather_than_assumed(s3):
    """FR-004's condition, which was computed by nothing any test ran.

    `precisionNote` was only ever supplied as an INPUT to the notifier, so `return False` at the
    top of `_loses_precision` left the suite green while every spreadsheet lost its warning. The
    condition is a property of the values, not of the schema: a bigint column of small numbers
    loses nothing, and warning about it would train the reader to ignore the sentence.
    """
    def convert(columns, body):
        s3.written.clear()
        s3.payload = (",".join(f'"{c["name"]}"' for c in columns) + "\n" + body + "\n").encode()
        s3.size = len(s3.payload)
        return c.handler(_event("xlsx", columns=columns), None)

    small = [{"name": "n", "type": "bigint"}]
    assert convert(small, '"42"')["precisionNote"] is False, "a small bigint loses nothing"

    exact = c.EXCEL_EXACT_INTEGER
    assert convert(small, f'"{exact - 1}"')["precisionNote"] is False, "2^53 - 1 is exact"
    assert convert(small, f'"{exact}"')["precisionNote"] is True
    assert convert(small, f'"-{exact}"')["precisionNote"] is True, "the magnitude is what matters"
    assert convert(small, "")["precisionNote"] is False, "an all-NULL column has no magnitude"

    narrow = [{"name": "d", "type": "decimal", "precision": 10, "scale": 2}]
    assert convert(narrow, '"1.25"')["precisionNote"] is False
    wide = [{"name": "d", "type": "decimal", "precision": 20, "scale": 2}]
    assert convert(wide, '"1.25"')["precisionNote"] is True, (
        "a decimal wider than a double's 15 significant digits rounds whatever it holds"
    )


def test_a_file_too_large_for_one_put_is_uploaded_in_parts_under_the_same_condition(s3, monkeypatch):
    """The multipart half of FR-005, which is reachable: JSON's cap times its measured expansion
    is about 5.4 GB, past S3's 5 GB single-put limit. Driven against a lowered threshold rather
    than a five-gigabyte fixture, because the guard is the branch and the condition on the
    COMPLETE — the parts themselves carry none, and putting it there would be a silent no-op."""
    completed, aborted, parts = [], [], []

    def create(**kwargs):
        s3.calls.append(("create_multipart_upload", kwargs))
        return {"UploadId": "up-1"}

    def upload_part(**kwargs):
        parts.append(kwargs)
        assert "IfNoneMatch" not in kwargs, "a part carries no condition; only the complete does"
        return {"ETag": f'"etag-{kwargs["PartNumber"]}"'}

    def complete(**kwargs):
        completed.append(kwargs)
        if s3.occupied and "IfNoneMatch" in kwargs:
            raise _precondition_failed()
        return {}

    monkeypatch.setattr(c, "SINGLE_PUT_MAX_BYTES", 1)
    monkeypatch.setattr(c, "PART_BYTES", 64)
    s3.create_multipart_upload = create
    s3.upload_part = upload_part
    s3.complete_multipart_upload = complete
    s3.abort_multipart_upload = lambda **kwargs: aborted.append(kwargs)

    result = c.handler(_event("parquet"), None)

    assert result["outcome"] == "converted" and result["bytes"] > 0
    assert len(parts) > 1, "the fixture is large enough to need more than one part"
    assert [part["PartNumber"] for part in parts] == list(range(1, len(parts) + 1))
    assert completed[0]["IfNoneMatch"] == "*"
    assert completed[0]["MultipartUpload"]["Parts"] == [
        {"ETag": f'"etag-{n}"', "PartNumber": n} for n in range(1, len(parts) + 1)
    ]
    assert aborted == [], "a completed upload is not aborted"

    s3.occupied = True
    refused = c.handler(_event("parquet"), None)
    assert refused["outcome"] == "refused" and refused["reason"] == "destination_occupied"
    assert len(aborted) == 1, "a refused multipart is aborted, or it holds storage invisibly"


def test_the_row_count_is_the_csvs_own_data_row_count(s3):
    """Counted from the CSV independently, by a reader that is not polars and not the writer.

    Both counts come from the OUTPUT — the Parquet footer and the newline count — so a count
    that drifted from the source would agree with itself. Mutations inflating either above one
    row survived, because the only fixtures were zero rows and one.
    """
    import csv
    import io as _io

    rows = 37
    s3.payload = _csv(rows=rows)
    s3.size = len(s3.payload)
    independent = sum(1 for _ in csv.reader(_io.StringIO(s3.payload.decode()))) - 1
    assert independent == rows, "the fixture builder and the CSV parser disagree"

    for fmt in ("parquet", "json", "xlsx", "csv"):
        s3.written.clear()
        assert c.handler(_event(fmt), None)["rows"] == independent, f"{fmt} miscounted"


def test_the_sheet_is_named_and_excels_row_ceiling_is_excels(s3):
    """Two constants nothing pinned: the worksheet name (the XML is read positionally, so
    dropping `worksheet=` survived) and the row ceiling itself (the refusal test monkeypatches
    it, so changing it by 48,575 survived too)."""
    import xml.etree.ElementTree as ET

    c.handler(_event("xlsx"), None)
    workbook = zipfile.ZipFile(io.BytesIO(s3.written[0]))
    names = [
        sheet.get("name")
        for sheet in ET.fromstring(workbook.read("xl/workbook.xml")).iter()  # noqa: S314
        if sheet.tag.endswith("}sheet")
    ]
    assert names == ["results"]
    assert rc_config.EXCEL_MAX_ROWS == 1_048_575, (
        "one less than Excel's 1,048,576, because the header takes one"
    )


def test_the_upload_path_raises_no_transient_error(s3):
    """The machine retries this verb on TransientError alone, so a transient raised after the
    object exists would re-run a completed write and report the user's success as a conflict."""
    import ast

    tree = ast.parse((_HERE / "rc_convert.py").read_text())
    bodies = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert {"_upload", "_multipart", "_occupied_or_raise", "_download"} <= set(bodies), (
        "the functions this walks have been renamed, so the sweep below has no population"
    )

    def names(function):
        # Docstrings are stripped by the AST walk, which matters here: the prose explaining
        # this very rule names TransientError, so a source-text sweep would report the
        # explanation as the violation.
        return {
            node.id for node in ast.walk(function) if isinstance(node, ast.Name)
        } | {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}

    for after_the_write in ("_upload", "_multipart", "_occupied_or_raise"):
        found = names(bodies[after_the_write])
        assert "TransientError" not in found and "raise_if_transient" not in found, (
            f"{after_the_write} can raise a transient, so a retry could re-run a completed write"
        )
    assert "raise_if_transient" in names(bodies["_download"]), (
        "the positive control: the READ path does classify transients, so the absences above "
        "are a property of the upload rather than of a sweep that finds nothing anywhere"
    )


def test_a_personal_conversion_emits_all_three_child_spans(s3, captured_events):
    """THREE spans, not one, and on a run that reaches no shared helper at all.

    The body is download then write then upload, with three comparable costs, so a single span
    covering almost the whole root would tell an operator nothing about which of the three was
    slow. A personal-space destination is the fixture deliberately: it touches none of the shared
    transfer engine, so these three spans are the only child spans this verb can have and the
    assertion cannot be satisfied by somebody else's instrumentation.

    Args:
      s3: The fake S3 client and scratch directory.
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    result = c.handler(_event("parquet"), None)

    assert result["outcome"] == "converted", "the spans are asserted on a SUCCESSFUL run"
    root = captured_events.spans("convert")
    assert len(root) == 1, f"expected one convert root span, got {len(root)}"
    for name in ("download-results", "write-conversion", "upload-conversion"):
        children = captured_events.child_spans("convert", name=name)
        assert len(children) == 1, (
            f"convert emitted {len(children)} {name!r} child spans, expected exactly one"
        )
        assert children[0]["parent_span_id"] == root[0]["span_id"]


# ── The chosen columns, and the fourth writer (SPEC-239 FR-003, FR-004) ──────

_ABC = (("a", "varchar", '"1"'), ("b", "varchar", '"2"'), ("c", "varchar", '"3"'))


def _abc(s3, rows=1):
    """Points the fake at a three-column result `a, b, c` and returns its described columns."""
    s3.payload = _csv(_ABC, rows=rows, decimal=False)
    s3.size = len(s3.payload)
    return _columns(_ABC, decimal=False)


def test_a_parquet_conversion_writes_only_the_chosen_columns_in_the_chosen_order(s3, tmp_path):
    columns = _abc(s3)

    result = c.handler(_event("parquet", columns=columns, chosen=[2, 0]), None)

    assert result["outcome"] == "converted"
    written = pl.read_parquet(_uploaded(s3, tmp_path, ".parquet"))
    assert written.columns == ["c", "a"], "the file's schema is the chosen order, not the result's"
    assert written.rows() == [("3", "1")], "and each column carries its own values"


def test_a_json_conversion_writes_only_the_chosen_columns_in_the_chosen_order(s3, tmp_path):
    columns = _abc(s3)

    c.handler(_event("json", columns=columns, chosen=[2, 0]), None)

    lines = [json.loads(line) for line in s3.written[0].decode().splitlines()]
    assert [list(line) for line in lines] == [["c", "a"]], "keys are exactly the chosen two, in order"
    assert lines[0] == {"c": "3", "a": "1"}


def test_an_excel_conversion_writes_only_the_chosen_columns_in_the_chosen_order(s3, tmp_path):
    columns = _abc(s3)

    c.handler(_event("xlsx", columns=columns, chosen=[2, 0]), None)

    workbook = zipfile.ZipFile(io.BytesIO(s3.written[0]))
    shared = [
        node.text
        for node in ET.fromstring(workbook.read("xl/sharedStrings.xml")).iter()  # noqa: S314
        if node.tag.endswith("}t")
    ]
    assert shared[:2] == ["c", "a"], "the header row is the chosen columns, in order"


def test_a_column_left_out_cannot_refuse_the_file_by_its_type(s3, tmp_path):
    """A `decimal` with no precision is a type this plane refuses outright — `athena_type_of`
    will not invent a scale. Refusing a whole export over a column the file does not contain
    would make hiding a column unable to rescue an export that a column's type broke."""
    pairs = (("a", "varchar", '"1"'), ("b", "decimal", '"2.5"'), ("c", "varchar", '"3"'))
    s3.payload = _csv(pairs, decimal=False)
    s3.size = len(s3.payload)
    columns = _columns(pairs, decimal=False)

    refused = c.handler(_event("parquet", columns=columns), None)
    assert refused["outcome"] == "refused" and refused["reason"] == "unsupported_column_type"

    s3.written.clear()
    kept = c.handler(_event("parquet", columns=columns, chosen=[0, 2]), None)

    assert kept["outcome"] == "converted"
    assert pl.read_parquet(_uploaded(s3, tmp_path, ".parquet")).columns == ["a", "c"]


def test_the_excel_cell_cap_counts_the_columns_the_workbook_will_hold(s3, monkeypatch):
    """The cap is about what the workbook costs to BUILD, so it has to be charged the kept
    columns. Charged the result's width instead, hiding columns could not rescue a result the
    cell cap refuses — which is the one repair a user has for it."""
    wide = tuple((f"c{i}", "varchar", '"x"') for i in range(20))
    columns = _columns(wide, decimal=False)
    monkeypatch.setattr(c, "EXCEL_MAX_CELLS", 5_000_000)
    monkeypatch.setattr(rc_config, "EXCEL_MAX_CELLS", 5_000_000)
    monkeypatch.setattr(c, "_write_excel", lambda frame, schema, target: _stub_workbook(frame, schema, target))

    s3.payload = _csv(wide, rows=1, decimal=False)
    s3.size = len(s3.payload)

    assert c.handler(_event("xlsx", columns=columns, chosen=list(range(8))), None)["outcome"] == "converted"


def _stub_workbook(frame, schema, target):
    """The Excel writer with the workbook build replaced, so the refusal is what is measured."""
    c._refuse_what_excel_cannot_hold(500_000, len(schema))
    target.write_bytes(b"stub")
    return 500_000, False


def test_the_cell_cap_still_refuses_the_same_result_when_no_columns_are_chosen(s3, monkeypatch):
    """The positive control for the test above: 500,000 rows of 20 columns is over the cap and
    8 of them is under it, so the pass there is about the projection and not about the number."""
    wide = tuple((f"c{i}", "varchar", '"x"') for i in range(20))
    columns = _columns(wide, decimal=False)
    monkeypatch.setattr(c, "EXCEL_MAX_CELLS", 5_000_000)
    monkeypatch.setattr(rc_config, "EXCEL_MAX_CELLS", 5_000_000)
    monkeypatch.setattr(c, "_write_excel", lambda frame, schema, target: _stub_workbook(frame, schema, target))
    s3.payload = _csv(wide, rows=1, decimal=False)
    s3.size = len(s3.payload)

    refused = c.handler(_event("xlsx", columns=columns), None)

    assert refused["outcome"] == "refused" and refused["reason"] == "excel_cell_limit"


def test_a_csv_conversion_writes_athenas_own_text_and_keeps_null_apart_from_empty(s3, tmp_path):
    """The whole claim of the CSV writer: a file made this way holds what a copy of the object
    would. Only the quoting may differ, and the two encodings agree where it matters — an
    unquoted empty field is NULL and `""` is an empty string, going in and coming out."""
    pairs = (
        ("dbl", "double", '"1.50"'),
        ("ts", "timestamp", '"2026-09-16 10:00:00.000"'),
        ("txt", "varchar", '"He said ""hi"", then\nleft"'),
        ("nothing", "varchar", ""),
        ("blank", "varchar", '""'),
    )
    s3.payload = _csv(pairs, decimal=False)
    s3.size = len(s3.payload)

    result = c.handler(_event("csv", columns=_columns(pairs, decimal=False)), None)

    assert result["outcome"] == "converted" and result["rows"] == 1
    put = next(kwargs for name, kwargs in s3.calls if name == "put_object")
    assert put["ContentType"] == "text/csv"
    read_back = pl.read_csv(
        _uploaded(s3, tmp_path, ".csv"),
        schema_overrides={name: pl.String() for name, _, _ in pairs},
        infer_schema_length=0,
    )
    assert read_back.rows() == [("1.50", "2026-09-16 10:00:00.000", 'He said "hi", then\nleft', None, "")], (
        "the double keeps its trailing zero, the timestamp its space and its milliseconds, the "
        "quoted newline its newline, and NULL is still not the empty string"
    )


def test_a_csv_conversion_types_nothing_so_a_type_this_plane_cannot_map_is_no_obstacle(s3, tmp_path):
    """`decimal` with no precision refuses every other format. CSV never asks `schema_of` at all,
    so the column's own text is written and the conversion succeeds."""
    pairs = (("a", "varchar", '"1"'), ("b", "decimal", '"2.5"'))
    s3.payload = _csv(pairs, decimal=False)
    s3.size = len(s3.payload)

    result = c.handler(_event("csv", columns=_columns(pairs, decimal=False), chosen=[1]), None)

    assert result["outcome"] == "converted"
    assert s3.written[0] == b"b\n2.5\n", "the header is the one kept column and the value is its text"


def test_a_csv_conversions_row_count_is_right_on_a_file_the_reader_splits(s3):
    """The shape that once broke polars' fast count: a file large enough for polars to split
    across threads, holding values with newlines inside their quotes. Under polars 1.12
    `select(pl.len())` read it tens of thousands of rows short; the writer counts through a
    column instead, and this holds that count to the row on the same shape.
    """
    columns = [{"name": "id", "type": "varchar"}, {"name": "doc", "type": "varchar"}]
    s3.payload = _multi_line_payload(100_000, width=20)
    s3.size = len(s3.payload)

    result = c.handler(_event("csv", columns=columns), None)

    assert result["rows"] == 100_000


def test_an_occupied_destination_refuses_a_csv_conversion_as_it_refuses_a_parquet_one(s3):
    s3.occupied = True

    refused = c.handler(_event("csv"), None)

    assert refused["outcome"] == "refused" and refused["reason"] == "destination_occupied"
    assert s3.written == []


@pytest.mark.parametrize(
    "chosen",
    [[-1], [0, -1], [1, 1], [], [3], [True], ["1"], [1.0], [[0]], {0: 1}, (0, 2), "02"],
    ids=[
        "negative", "negative-among-valid", "repeat", "empty", "past-the-end", "bool", "string",
        "float", "nested", "object", "tuple", "string-of-digits",
    ],
)
def test_a_chosen_list_that_is_not_positions_of_this_result_is_a_LOUD_fault(s3, chosen):
    """Every one of these writes a FILE if it is not checked, which is why the check is here as
    well as upstream. `[-1]` indexes from the end and would write the LAST column while reporting
    success; `[1, 1]` collapses in the schema dict and writes one column where two were asked
    for; `[]` writes a Parquet file of no columns at all, and it uploads. Measured, before this
    guard: `[-1]` converted and the file held column `c`.

    The last four are about the clause ORDER rather than about writing a file: a list holding a
    list must be caught before `set` is asked to hash it, and a dict of valid positions must be
    caught before anything iterates its KEYS — which would satisfy every remaining clause and
    convert as though the contract permitted a mapping here.

    A fault rather than a refusal, because validate-authorize refuses all of these and
    describe-results the upper bound — reaching convert means the states disagree, which is the
    same class as the header check and is treated the same way."""
    columns = _abc(s3)

    with pytest.raises(RuntimeError, match="distinct positions"):
        c.handler(_event("csv", columns=columns, chosen=chosen), None)

    assert s3.written == [], "nothing is uploaded when the state cannot be trusted"


def test_convert_survives_a_state_that_does_not_carry_the_key_at_all(s3, tmp_path):
    """The deploy window this whole ordering exists for, from the other side: this verb's new
    image runs against the PREVIOUS ASL for as long as the two deploys take, and that ASL's
    `Described` Pass names no `columnIndexes`. Reading it with `events.require` instead of `get`
    is a KeyError on every conversion in that window — and every other fixture here sets the key,
    so nothing else in this file would notice."""
    event = _event("parquet")
    del event["columnIndexes"]

    result = c.handler(event, None)

    assert result["outcome"] == "converted"
    assert pl.read_parquet(_uploaded(s3, tmp_path, ".parquet")).width == len(_columns())


def test_a_dropped_columns_VALUES_are_never_typed_either(s3, tmp_path):
    """The type half of this is covered above; this is the value half, which is the one a user
    meets. A `bigint` column holding text refuses the whole conversion — and leaving that column
    out converts, because a dropped column is read as text, which any value parses as."""
    pairs = (("a", "varchar", '"1"'), ("b", "bigint", '"not-a-number"'), ("c", "varchar", '"3"'))
    s3.payload = _csv(pairs, decimal=False)
    s3.size = len(s3.payload)
    columns = _columns(pairs, decimal=False)

    refused = c.handler(_event("parquet", columns=columns), None)
    assert refused["outcome"] == "refused" and refused["reason"] == "results_unreadable"

    s3.written.clear()
    kept = c.handler(_event("parquet", columns=columns, chosen=[0, 2]), None)

    assert kept["outcome"] == "converted"
    assert pl.read_parquet(_uploaded(s3, tmp_path, ".parquet")).columns == ["a", "c"]


def _written_rows(fmt, data):
    """The rows a converted file holds, as text, whatever the format wrote them as."""
    if fmt == "csv":
        return [list(row) for row in csv.reader(io.StringIO(data.decode()))][1:]
    if fmt == "json":
        return [list(json.loads(line).values()) for line in data.decode().splitlines()]
    return [list(row) for row in pl.read_parquet(io.BytesIO(data)).rows()]


@pytest.mark.parametrize("chosen", [None, [0]], ids=["whole", "id-only"])
@pytest.mark.parametrize("fmt", ["parquet", "json", "csv"])
def test_a_result_holding_multi_line_values_converts_row_for_row(s3, fmt, chosen):
    """The shape polars 1.12's streaming reader mis-split, at 200,000 rows and about 7 MB — well
    past the 60,000 where 1.12 refused a whole save or wrote a column-subset one with extra rows.
    Every row is compared with Python's own `csv` module's reading of the input, so a fragment of
    a document landing in a kept column is a red test rather than a count that happens to agree.
    """
    columns = [{"name": "id", "type": "varchar"}, {"name": "doc", "type": "varchar"}]
    s3.payload = _multi_line_payload(200_000)
    s3.size = len(s3.payload)
    expected = [row if chosen is None else [row[i] for i in chosen]
                for row in list(csv.reader(io.StringIO(s3.payload.decode())))[1:]]

    result = c.handler(_event(fmt, columns=columns, chosen=chosen), None)

    assert (result["outcome"], result["rows"]) == ("converted", 200_000)
    assert _written_rows(fmt, s3.written[0]) == expected
