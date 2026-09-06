"""convert: one typed read, three writers, one conditional write, and nothing left on disk.

Driven through `handler`, because the decorator stack is part of the verb — a test calling the
inner function would let the span and the failure notifier be removed with the suite green.
"""

import io
import json
import os
import pathlib
import re
import sys
import zipfile

import polars as pl
import pytest

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
        return {"ContentLength": self.size}

    def download_fileobj(self, bucket, key, handle):
        self.calls.append(("download_fileobj", {"Bucket": bucket, "Key": key}))
        handle.write(self.payload)

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
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "PreconditionFailed", "Message": "exists"}}, "PutObject")


@pytest.fixture
def s3(tmp_path, monkeypatch):
    """Points the verb at a scratch directory of its own and a fake S3."""
    monkeypatch.setattr(c, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(c.notify, "emit_notification", lambda *a, **kw: None)
    fake = FakeS3()
    clients._s3 = fake
    return fake


def _event(fmt="parquet", on_conflict="refuse", columns=None, filename=None):
    """The described request, as the machine's Described state hands it over."""
    name = filename or f"q1.{fmt}"
    return {
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


def test_a_value_that_does_not_parse_refuses_without_quoting_the_cell(s3):
    s3.payload = b'"n"\n"not-a-number"\n'
    s3.size = len(s3.payload)

    result = c.handler(_event(columns=[{"name": "n", "type": "bigint"}]), None)

    assert result["outcome"] == "refused" and result["reason"] == "results_unreadable"
    assert s3.written == [], "no partial file is written"


def test_an_occupied_destination_is_refused_only_when_the_request_asked_to_be(s3):
    s3.occupied = True
    refused = c.handler(_event("parquet", on_conflict="refuse"), None)
    assert refused["outcome"] == "refused" and refused["reason"] == "destination_occupied"
    assert s3.written == []

    overwritten = c.handler(_event("parquet", on_conflict="overwrite"), None)
    assert overwritten["outcome"] == "converted"
    put = [kwargs for name, kwargs in s3.calls if name == "put_object"][-1]
    assert "IfNoneMatch" not in put, "an overwrite carries no condition"


def test_too_many_columns_for_a_spreadsheet_refuses_with_the_count(s3):
    wide = [{"name": f"c{i}", "type": "varchar"} for i in range(c.EXCEL_MAX_COLUMNS + 1)]
    result = c.handler(_event("xlsx", columns=wide), None)

    assert result["outcome"] == "refused" and result["reason"] == "excel_column_limit"
    assert result["tokens"] == {"count": c.EXCEL_MAX_COLUMNS + 1}
    assert s3.written == []
    assert [name for name, _ in s3.calls] == [], (
        "a result too wide for a worksheet is refused from the metadata alone, before a byte "
        "of it is fetched"
    )


def test_too_many_rows_for_a_spreadsheet_refuses_with_the_count(s3, monkeypatch):
    """Driven against a lowered ceiling rather than a million-row fixture: the guard is the
    comparison, and a fixture large enough to trip the real number would take minutes to build
    and would test polars rather than this."""
    monkeypatch.setattr(c, "EXCEL_MAX_ROWS", 2)
    s3.payload = _csv(rows=3)
    s3.size = len(s3.payload)

    result = c.handler(_event("xlsx"), None)

    assert result["outcome"] == "refused" and result["reason"] == "excel_row_limit"
    assert result["tokens"] == {"count": 3}
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
    """

    def refuse(*args, **kwargs):
        raise AssertionError("a streamed conversion materialised the frame")

    monkeypatch.setattr(pl.LazyFrame, "collect", refuse)
    monkeypatch.setattr(pl, "read_csv", refuse)

    assert c.handler(_event("parquet"), None)["outcome"] == "converted"
    assert c.handler(_event("json"), None)["outcome"] == "converted"


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
    assert seen["contents"] == ["req-1"], "a previous request's bytes survived into this one"


def test_a_refusal_leaves_the_disk_clean_too(s3):
    c.handler(_event(columns=[{"name": "shape", "type": "geometry"}]), None)
    assert list(c.SCRATCH_ROOT.iterdir()) == []


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
