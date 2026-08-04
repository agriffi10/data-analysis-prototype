"""Handler tests for infer-schema.

Real polars fixtures (Parquet / CSV / JSON). Two seams, matching the two source paths:
Parquet keeps the source-URI seam pointing polars at a local fixture (polars scans local
paths and s3:// the same way), while CSV/JSON are stubbed at the S3 CLIENT, so the
assertions run through the real bounded head read and the in-memory buffer polars is
actually handed in prod. Stubbing CSV at the URI seam instead is what let the
object_store bug ship: polars reads a local path happily, so the test passed while every
real build failed. Asserts the type rules plus scan-error → terminal and transient-S3 →
raised.

Run under pytest, which supplies the cpcommon path and the config env baseline from
conftest.py. The `python3 test_infer_schema.py` mode this file used to advertise has not
worked since the verb started importing cpcommon — the __main__ block below still runs,
but only under an environment that provides both.
"""

import datetime as dt
import io as io_module
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

import infer_schema as i
import polars as pl
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError


class _FakeClientError(Exception):
    """A botocore-SHAPED error: carries ``.response["Error"]["Code"]``.

    The distinction matters. The pre-existing tests raised ``RuntimeError("Throttling
    Exception")`` — a throttle NAME in the message but no ``.response`` — so
    ``_error_code`` read "" and the transient mapping never fired, i.e. those tests passed
    whether or not the fix worked. A real botocore fault looks like THIS.
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


_REAL_CHECK = i._check_access
# Captured because _use_fixture replaces it globally and never restores it: without this,
# a test that needs the REAL ranged reader silently gets the previous test's local-file
# stub, and passes alone while failing (or worse, asserting nothing) in the full suite.
_REAL_PARQUET_SOURCE = i._parquet_source
_TMP = tempfile.mkdtemp()


def _use_fixture(path):
    # Parquet seam: hand polars a local file object (it seeks either the same way) and
    # no-op the S3 access probe. The handle is the seam's return value — polars reads it
    # after the lambda returns, so a context manager would close it too early (SIM115).
    i._parquet_source = lambda bucket, key: open(path, "rb")  # noqa: SIM115
    i._check_access = lambda bucket, key: None


class _FakeBody:
    def __init__(self, data):
        self._data = data
        self.closed = False

    def iter_chunks(self, size):
        for start in range(0, len(self._data), size):
            yield self._data[start: start + size]

    def close(self):
        self.closed = True


class _FakeS3Get:
    def __init__(self, data):
        self.data = data

    def head_object(self, *a, **k):
        return {"ContentLength": len(self.data)}

    def get_object(self, **kwargs):
        return {"Body": _FakeBody(self.data)}


def _use_ranged_parquet(data):
    """Serve ``data`` over a fake S3 honouring Range, with the REAL S3RangeReader in play.

    The other Parquet tests hand polars a local file, which cannot tell a footer read from
    a whole-object read. This one counts bytes, so "reads the footer, not the object" is
    an assertion — the property that broke in production for CSV.
    """
    served = {"bytes": 0, "ranges": []}

    class _RangedS3:
        @staticmethod
        def head_object(*a, **k):
            return {"ContentLength": len(data)}

        @staticmethod
        def get_object(Bucket=None, Key=None, Range=None):
            start, end = Range.split("=")[1].split("-")
            chunk = data[int(start): int(end) + 1]
            served["bytes"] += len(chunk)
            served["ranges"].append((int(start), len(chunk)))
            return {"Body": io_module.BytesIO(chunk)}

    i._check_access = _REAL_CHECK
    i._parquet_source = _REAL_PARQUET_SOURCE
    clients._s3 = _RangedS3()
    return served


def _use_s3_fixture(data):
    """Serve ``data`` from a fake S3 and make any s3:// URI read a hard failure.

    CSV/JSON must reach polars as boto3-fetched bytes; if the handler ever goes back to
    handing polars an s3:// URI, _object_uri raises and the test fails loudly rather than
    silently exercising a path that does not work in Lambda.
    """
    def _no_parquet_source(bucket, key):
        raise AssertionError("CSV/JSON must not be read through the Parquet ranged reader")

    i._parquet_source = _no_parquet_source
    i._check_access = _REAL_CHECK
    clients._s3 = _FakeS3Get(data)


def _event(fmt, partition_keys=None, sample="alice/sales/2026/part-0"):
    return {
        "actor": "alice",
        "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice"},
        "tableName": "sales_2026",
        "location": "s3://dat-prod-user-space/alice/sales/2026/",
        "format": fmt,
        "partitioned": bool(partition_keys),
        "partitionKeys": partition_keys or [],
        "sampleObjectKey": sample,
        "fileCount": 1,
        "requestId": "r1",
    }


def _types(out):
    return {c["name"]: c["type"] for c in out["columns"]}


def test_parquet_preserves_native_types():
    path = os.path.join(_TMP, "s.parquet")
    pl.DataFrame({
        "order_id": pl.Series([1, 2], dtype=pl.Int64),
        "amount": pl.Series([1.5, 2.5], dtype=pl.Float64),
        "d": pl.Series([dt.date(2026, 1, 1), dt.date(2026, 1, 2)]),
        # Naive on purpose: a tz-aware value makes polars write Datetime(tz), which is a
        # different Parquet logical type than the one this test asserts on.
        "ts": pl.Series([dt.datetime(2026, 1, 1, 12), dt.datetime(2026, 1, 2, 12)]),  # noqa: DTZ001
        "note": pl.Series(["a", "b"], dtype=pl.String),
    }).write_parquet(path)
    _use_fixture(path)
    out = i.handler(_event("parquet"), None)
    assert _types(out) == {
        "order_id": "bigint", "amount": "double", "d": "date", "ts": "timestamp", "note": "string",
    }
    # column order preserved
    assert [c["name"] for c in out["columns"]] == ["order_id", "amount", "d", "ts", "note"]


def test_parquet_reads_only_the_footer_not_the_whole_object():
    """A Parquet source must cost a small tail read, however large the object.

    This is the test that fails if the probe goes back to scan_parquet: over a file object
    scan_parquet issues ONE read for the entire object, which is how a 250 GB source would
    end up inside a 1 GB Lambda. The fixture has to dwarf polars' ~64 KiB footer
    read-ahead or the whole file IS the footer read and this proves nothing.
    """
    blob = io_module.BytesIO()
    pl.DataFrame({
        "id": pl.Series(range(400_000), dtype=pl.Int64),
        "amount": pl.Series([1.5] * 400_000, dtype=pl.Float64),
        "note": pl.Series(["abcdefghij"] * 400_000),
    }).write_parquet(blob, row_group_size=20_000)
    data = blob.getvalue()
    assert len(data) > 300_000, "fixture must dwarf the footer read-ahead"

    served = _use_ranged_parquet(data)
    out = i.handler(_event("parquet"), None)

    assert [c["name"] for c in out["columns"]] == ["id", "amount", "note"]
    assert served["bytes"] <= 256 * 1024, f"footer read grew to {served['bytes']} bytes"
    assert served["bytes"] < len(data) / 4, f"read {served['bytes']} of {len(data)}"
    assert min(s for s, _ in served["ranges"]) > len(data) / 2, "the read must sit in the tail"


def test_csv_is_all_string_from_header_no_inference():
    _use_s3_fixture(b"order_id,amount,ts\n1,2.50,2026-01-01\n2,3.75,2026-01-02\n")
    out = i.handler(_event("csv"), None)
    # Every column string despite int/float/date-looking values.
    assert _types(out) == {"order_id": "string", "amount": "string", "ts": "string"}


def test_csv_header_is_read_without_downloading_the_object():
    """The reported bug: a real 31 MiB CSV failed with "failed to allocate 32446710 bytes
    to download" because polars' object_store tried to fetch the whole file. The header
    must come from a bounded boto3 read — _use_s3_fixture fails the test if an s3:// URI
    is used at all, and the body here is far bigger than the header."""
    rows = b"".join(b"%d,%d.50,2026-01-01\n" % (n, n) for n in range(50_000))
    _use_s3_fixture(b"order_id,amount,ts\n" + rows)
    out = i.handler(_event("csv"), None)
    assert [c["name"] for c in out["columns"]] == ["order_id", "amount", "ts"]


def test_csv_header_with_a_quoted_comma_survives_the_head_read():
    """polars parses the header, so a quoted name containing a comma stays one column —
    the reason the head read keeps whole lines instead of splitting on the first newline."""
    _use_s3_fixture(b'order_id,"amount, net",ts\n1,2.50,2026-01-01\n')
    out = i.handler(_event("csv"), None)
    assert [c["name"] for c in out["columns"]] == ["order_id", "amount, net", "ts"]


def test_json_dates_are_parsed():
    _use_s3_fixture(
        b'{"id": 1, "d": "2026-01-01", "ts": "2026-01-01T12:00:00", "name": "a"}\n'
        b'{"id": 2, "d": "2026-01-02", "ts": "2026-01-02T13:30:00", "name": "b"}\n'
    )
    out = i.handler(_event("json"), None)
    assert _types(out) == {"id": "bigint", "d": "date", "ts": "timestamp", "name": "string"}


def test_json_types_are_inferred_from_rows_beyond_a_wide_first_record():
    """A column null in row 1 and typed later must still type correctly, even when the
    first record alone is wider than a read chunk.

    This does NOT pin the line bound (an earlier version of this test claimed it did):
    reading stops at a CHUNK boundary, so the head overshoots by up to 256 KiB — thousands
    of rows — and no realistic input separates a 1-line bound from a 1001-line one.
    max_lines bounds COST, not correctness. What it does cover is the real path: a
    multi-chunk boto3 head, reassembled, inferred by polars from the buffer.
    """
    wide = b'{"a": null, "pad": "' + b"x" * 300_000 + b'"}\n'
    _use_s3_fixture(wide + b"".join(b'{"a": %d, "pad": "y"}\n' % n for n in range(500)))
    out = i.handler(_event("json"), None)
    assert _types(out) == {"a": "bigint", "pad": "string"}


def test_transient_get_on_the_body_read_is_not_terminalized():
    """The head read runs inside the scan's try/except, so a throttled GetObject must be
    re-raised as TransientError — reporting it as an unreadable file would be a permanent
    verdict on a fault the SFN would have retried."""
    class _ThrottledS3:
        def head_object(self, *a, **k):
            return {"ContentLength": 10}

        def get_object(self, **kwargs):
            raise _FakeClientError("SlowDown")

    i._check_access = _REAL_CHECK
    clients._s3 = _ThrottledS3()
    q = _arm_notifications()
    try:
        i.handler(_event("csv"), None)
    except TransientError:
        assert q.calls == [], "a retryable throttle must not notify the actor"
        return
    except TerminalError:
        raise AssertionError("a throttled body read must not be terminalized")
    raise AssertionError("expected TransientError from a throttled GetObject")


def test_ddl_is_generated_and_carried():
    path = os.path.join(_TMP, "s2.parquet")
    pl.DataFrame({"id": pl.Series([1], dtype=pl.Int64)}).write_parquet(path)
    _use_fixture(path)
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]
    out = i.handler(_event("parquet", partition_keys=keys), None)
    assert out["columns"] == [{"name": "id", "type": "bigint"}]
    assert out["ddl"].startswith("CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026`")
    assert "PARTITIONED BY (`year` int)" in out["ddl"]
    assert "'projection.year.range'='2000,2100'" in out["ddl"]
    assert out["requestId"] == "r1"  # request carried through


def test_scan_error_is_terminal_schema_inference_failed():
    path = os.path.join(_TMP, "bad.parquet")
    with open(path, "w") as fh:
        fh.write("this is not a parquet file")
    _use_fixture(path)
    try:
        i.handler(_event("parquet"), None)
    except TerminalError as exc:
        assert exc.reason == "schema_inference_failed"
        return
    raise AssertionError("expected TerminalError(schema_inference_failed)")


def test_transient_s3_head_is_raised_as_TransientError():
    """A throttle/5xx on the head probe must reach the SFN as TransientError — the name
    InferSchema's Retry list now recognizes. A bare ClientError matches nothing there and
    would permanently fail the build; this is the bug being fixed."""
    i._check_access = _REAL_CHECK  # exercise the real head_object access probe

    class _FakeS3:
        def head_object(self, *a, **k):
            raise _FakeClientError("SlowDown")

    clients._s3 = _FakeS3()
    try:
        i.handler(_event("parquet"), None)
    except TransientError:
        return
    except TerminalError:
        raise AssertionError("a throttle must not be terminalized")
    raise AssertionError("expected TransientError from a throttled head probe")


def test_non_transient_s3_head_propagates_unchanged():
    """AccessDenied/NoSuchKey is deterministic — mapping it to TransientError would burn
    the SFN's retry attempts on a fault that cannot resolve. It propagates as-is."""
    i._check_access = _REAL_CHECK

    class _FakeS3:
        def head_object(self, *a, **k):
            raise _FakeClientError("AccessDenied")

    clients._s3 = _FakeS3()
    try:
        i.handler(_event("parquet"), None)
    except TransientError:
        raise AssertionError("a deterministic S3 fault must NOT become TransientError")
    except _FakeClientError as err:
        assert err.response["Error"]["Code"] == "AccessDenied"
        return
    raise AssertionError("expected the original ClientError to propagate")


def test_a_transient_head_is_not_notified_it_will_be_retried():
    """TransientError passes through @notifies_on_failure un-notified — otherwise every
    retry attempt would spam the actor with a premature 'something went wrong'."""
    i._check_access = _REAL_CHECK

    class _FakeS3:
        def head_object(self, *a, **k):
            raise _FakeClientError("SlowDown")

    clients._s3 = _FakeS3()
    q = _arm_notifications()
    try:
        i.handler(_event("parquet"), None)
    except TransientError:
        pass
    assert q.calls == [], "a retryable throttle must not notify the actor"


def test_infer_schema_state_retries_TransientError():
    """The code half is useless without the infra half: InferSchema's Retry list must name
    TransientError, or the mapping above just renames an error that still fails permanently.
    This pins the exact bug's second cause so it can't silently regress."""
    import re

    tftpl = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "infra", "modules", "table-builder", "state-machine.asl.json.tftpl",
    )
    with open(tftpl) as fh:
        asl = json.loads(re.sub(r"\$\{[^}]+\}", "ARN", fh.read()))
    retries = asl["States"]["InferSchema"]["Retry"]
    named = [e for r in retries for e in r["ErrorEquals"]]
    assert "TransientError" in named, f"InferSchema Retry must name TransientError; got {named}"


def test_notifies_actor_on_schema_inference_failure():
    path = os.path.join(_TMP, "bad2.parquet")
    with open(path, "w") as fh:
        fh.write("not parquet")
    _use_fixture(path)
    q = _arm_notifications()
    try:
        i.handler(_event("parquet"), None)
    except TerminalError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:infer"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "sales_2026": the data schema couldn\'t be read.'


def test_no_notification_on_success():
    path = os.path.join(_TMP, "ok.parquet")
    pl.DataFrame({"id": pl.Series([1], dtype=pl.Int64)}).write_parquet(path)
    _use_fixture(path)
    q = _arm_notifications()
    i.handler(_event("parquet"), None)
    assert q.calls == []


def test_notifies_actor_on_unexpected_s3_error():
    # A DETERMINISTIC S3 error (AccessDenied) escaping the access probe is a terminal
    # failure the SFN records; @notifies_on_failure tells the actor rather than failing
    # silently, and the original exception still propagates unchanged (the test above).
    # Uses a botocore-shaped error so the non-transient branch is genuinely exercised —
    # not the old RuntimeError, whose missing .response made the transient mapping a no-op.
    i._check_access = _REAL_CHECK

    class _FakeS3:
        def head_object(self, *a, **k):
            raise _FakeClientError("AccessDenied")

    clients._s3 = _FakeS3()
    q = _arm_notifications()
    try:
        i.handler(_event("parquet"), None)
    except _FakeClientError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageDeduplicationId"] == "r1:infer"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "sales_2026": something went wrong. Please try again.'


def test_malformed_event_is_terminal_and_notifies():
    # SPEC-083 FR-002: a missing required key → typed terminal + actor notification,
    # before any S3 access probe.
    q = _arm_notifications()
    bad = {"actor": "alice", "space": {"database": "alice"}, "requestId": "r1"}  # no format/sampleObjectKey/...
    try:
        i.handler(bad, None)
    except TerminalError as exc:
        assert exc.reason == "malformed_event"
    else:
        raise AssertionError("expected TerminalError(malformed_event)")
    assert len(q.calls) == 1 and q.calls[0]["MessageGroupId"] == "alice"


# ── The refresh cross-check (SPEC-143 FR-006) ────────────────────────────────

_CSV_SERDE = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
_JSON_SERDE = "org.openx.data.jsonserde.JsonSerDe"
_PARQUET_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"


def _storage(library):
    return {"serializationLibrary": library, "parameters": {}}


def test_a_folder_whose_format_no_longer_matches_the_table_is_terminal():
    """The failure a refresh must not paper over: re-deriving columns cannot fix a table
    declared with OpenCSVSerde over a folder that now holds JSON."""
    event = {**_event("json"), "storage": _storage(_CSV_SERDE)}
    try:
        i.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == "format_changed", exc.reason
        return
    raise AssertionError("expected TerminalError(format_changed)")


def test_a_serde_this_repo_does_not_write_is_refused_rather_than_guessed():
    event = {**_event("csv"), "storage": _storage("com.example.MysterySerDe")}
    try:
        i.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == "format_changed", exc.reason
        assert "unrecognised" in exc.detail
        return
    raise AssertionError("expected TerminalError(format_changed)")


def test_a_matching_serde_passes_the_cross_check_for_every_format_this_repo_writes():
    """Runs the check in isolation: the full handler would then go on to read S3."""
    for library, fmt in ((_CSV_SERDE, "csv"), (_JSON_SERDE, "json"), (_PARQUET_SERDE, "parquet")):
        i._check_format_matches_storage(_storage(library), fmt)


def test_a_refresh_whose_format_still_matches_infers_as_normal():
    """And the create path stays invisible to the guard: every OTHER test in this file is
    a create with no `storage` at all, so their continuing to pass is the coverage that
    the check is gated on presence rather than on format."""
    _use_s3_fixture(b"order_id,amount\n1,2.50\n")
    event = {**_event("csv"), "storage": _storage(_CSV_SERDE)}

    out = i.handler(event, None)

    assert [c["name"] for c in out["columns"]] == ["order_id", "amount"]


def test_the_shared_verbs_never_learn_about_mode():
    """FR-006 AC4. The branch is the state machine's business: the moment either shared
    verb reads `mode`, the claim that a refresh reuses them UNCHANGED stops being true and
    the two branches start drifting apart inside one file.

    An AST scan for the string LITERAL, so prose about mode (this file's own docstrings
    included) cannot trip it and neither quote style can slip past.
    """
    import ast

    verbs = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (
        os.path.join(verbs, "table-builder-inspect-source", "inspect_source.py"),
        os.path.join(verbs, "table-builder-infer-schema", "infer_schema.py"),
    ):
        with open(path) as handle:
            tree = ast.parse(handle.read())
        literals = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == "mode"
        ]

        assert not literals, f"{os.path.basename(path)} reads mode (line {literals[0].lineno})"


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
