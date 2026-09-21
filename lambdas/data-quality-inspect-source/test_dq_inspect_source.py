"""Unit tests for the data-quality inspect-source Lambda (SPEC-110).

Pure logic, AWS stubbed: s3_listing.list_data_objects and the S3 client are replaced on
the verb module, so no bucket is touched.
"""

import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_inspect_source as v
import polars as pl
import pytest
import test_bounded_read as ranged_s3
from cpcommon import bounded_read
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError, TransientError
from dqcommon import messages

BUCKET = "dq-user-bkt"
LOCATION = "alice/sales"
REQUEST_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
EXECUTION_ARN = "arn:aws:states:eu-west-2:111122223333:execution:dq:run-1"


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code.

    botocore ships in the Lambda RUNTIME but is NOT a test dependency of this repo, so
    the suites fake it rather than import it (see table-builder-execute-ddl's
    _FakeClientError and shared-space-common's fakes.FakeClientError). Importing the real
    one passes locally, where botocore is usually present transitively, and fails in CI.
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeS3:
    """Stands in for the S3 client's head_object (the folder-vs-file probe) and its writes.

    ``keys`` are the object keys that EXIST as exact objects; anything else raises the
    404 that means "not an object, so treat it as a folder". Writes are kept, and a
    conditional create over a key already written fails 412, because the request-id claim
    is exactly that write.
    """

    def __init__(self, keys=()):
        self.keys = set(keys)
        self.head_calls = []
        self.puts = []
        self.written = {}

    def head_object(self, Bucket, Key):  # boto3's kwarg casing
        self.head_calls.append(Key)
        if Key in self.keys:
            return {"ContentLength": 1}
        raise _FakeClientError("404")

    def put_object(self, Bucket, Key, Body, **kw):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, **kw})
        if kw.get("IfNoneMatch") == "*" and (Bucket, Key) in self.written:
            raise _FakeClientError("PreconditionFailed")
        self.written[(Bucket, Key)] = Body
        return {}

    def get_object(self, Bucket, Key):
        body = self.written[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}


@pytest.fixture(autouse=True)
def _restore_verb_module():
    """Snapshot/restore the verb module's namespace around every test.

    conftest.py does this for the cpcommon modules, but not for the verb — and _setup
    below stubs the verb's own _probe_columns. Without this, that stub would leak into
    the probe tests further down and they would silently assert against the stub instead
    of the real polars read.
    """
    saved = dict(vars(v))
    yield
    v.__dict__.clear()
    v.__dict__.update(saved)


_DEFAULT_COLUMNS = [{"name": "id", "type": "string"}]


def _setup(objects, exact_keys=(), columns=None):
    """Point the verb at a fake listing + a fake S3, returning the recorded prefixes.

    The per-file probe is stubbed by default — the tests below that exercise the REAL
    probe call _probe_columns directly rather than going through the handler.
    ``columns`` may be a dict keyed by object key to give files differing column lists.
    """
    listed = []
    fake = _FakeS3(exact_keys)
    v.clients.s3 = lambda: fake

    def _list(bucket, prefix):
        listed.append((bucket, prefix))
        return iter(objects)

    def _probe(bucket, key, fmt):
        if isinstance(columns, dict):
            return columns[key]
        return list(columns or _DEFAULT_COLUMNS)

    v.s3_listing.list_data_objects = _list
    v._probe_columns = _probe
    return listed, fake


def _event(**over):
    event = {
        "requestId": REQUEST_ID,
        "execution": {"arn": EXECUTION_ARN},
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "location": LOCATION,
        "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
    }
    event.update(over)
    return event


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


# ── the request id is claimed before anything is named from it ───────────────


def test_a_request_id_another_execution_holds_is_refused_before_listing_and_tells_nobody():
    """The holder's retry carries on; a second execution with its id reads nothing and writes nothing.

    Every later verb names its tables, output and Athena tokens from the request id, so the only
    safe place to stop a second execution is before the manifest exists. It is silent: the holder
    is the run that reports, and a reuse is a hand-built request with nothing it should be told.
    The empty folder at the end is the positive control — the same harness does notify a refusal
    that is not silent, so the silence above is not a notifier nobody wired up.
    """
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    sqs = _FakeSqs()
    v.clients._sqs = sqs
    listed, fake = _setup([("alice/sales/a.csv", 10)])
    v.handler(_event(), None)
    v.handler(_event(), None)
    writes_before, listings_before, probes_before = len(fake.puts), len(listed), len(fake.head_calls)

    with pytest.raises(TerminalError) as err:
        v.handler(_event(execution={"arn": f"{EXECUTION_ARN}-second"}), None)

    assert err.value.reason == messages.REQUEST_ID_REUSED
    assert (len(listed), len(fake.head_calls)) == (listings_before, probes_before)
    assert [put["Bucket"] for put in fake.puts[writes_before:]] == [cpconfig.ADMIN_BUCKET]
    assert sqs.calls == []

    _setup([])
    with pytest.raises(TerminalError):
        v.handler(_event(requestId="6ba7b810-9dad-41d1-80b4-00c04fd430c8"), None)
    assert len(sqs.calls) == 1


# ── FR-001: listing ──────────────────────────────────────────────────────────


def test_folder_is_listed_with_a_trailing_slash():
    """A prefix match without the slash would swallow alice/sales2/ and sales-archive/."""
    listed, _ = _setup([("alice/sales/a.csv", 10)])
    out = v.handler(_event(), None)
    assert listed == [(BUCKET, "alice/sales/")]
    assert out["pathFilter"] is None


def test_single_file_location_yields_a_one_object_manifest():
    listed, _ = _setup([("alice/sales/a.csv", 10)], exact_keys=["alice/sales/a.csv"])
    out = v.handler(_event(location="alice/sales/a.csv"), None)
    assert listed == [(BUCKET, "alice/sales/a.csv")]
    assert out["fileCount"] == 1
    assert out["format"] == "csv"
    assert out["pathFilter"] == f"s3://{BUCKET}/alice/sales/a.csv"


# ── SPEC-151 FR-002: a single-file listing matches the object, not the prefix ────


def test_a_single_file_check_ignores_siblings_sharing_its_stem():
    """list_objects_v2 is a PREFIX match, so data.csv also returns data.csv.gz.

    Left unfiltered this was the worst defect in the plane: the extra keys made
    `keys == [prefix]` false in create-temp-tables, so the parent-folder promotion did not
    apply, the external table was built at s3://…/data.csv/ over nothing, and GROUPING SETS
    still emitted a total row — so the user got verdict "clean", rowCount 0, over data
    nothing had read.
    """
    listed, fake = _setup(
        [
            ("alice/sales/data.csv", 10),
            ("alice/sales/data.csv.gz", 20),
            ("alice/sales/data.csv2", 30),
        ],
        exact_keys=["alice/sales/data.csv"],
    )

    out = v.handler(_event(location="alice/sales/data.csv"), None)

    assert listed == [(BUCKET, "alice/sales/data.csv")]
    assert out["fileCount"] == 1
    assert [f["key"] for f in _manifest_of(fake)["files"]] == ["alice/sales/data.csv"]


def test_empty_location_is_terminal_no_data_files():
    _setup([])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.NO_DATA_FILES


def test_user_settings_is_excluded_at_a_space_root_scan():
    """A check pointed at the space root must not treat the notification inbox as data."""
    page = {
        "Contents": [
            {"Key": "alice/data.csv", "Size": 10},
            {"Key": "alice/user_settings/notifications.json", "Size": 10},
            {"Key": "alice/system_settings/athenaresults/q.csv", "Size": 10},
        ]
    }
    fake = _FakeS3()
    fake.get_paginator = lambda op: type("P", (), {"paginate": staticmethod(lambda **kw: [page])})()
    v.clients.s3 = lambda: fake
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(location="alice"), None)

    assert [f["key"] for f in _manifest_of(fake)["files"]] == ["alice/data.csv"]


def test_a_zero_byte_object_at_the_location_is_a_folder_not_a_file():
    """S3 has no directories — a folder IS a zero-byte placeholder object (SPEC-016).

    With a placeholder at 'alice/sales', head_object SUCCEEDS, so a size-blind probe would
    read the location as a file and list the slash-less prefix 'alice/sales' — silently
    pulling in 'alice/sales-archive/' and 'alice/sales2/'. The placeholder itself is then
    dropped by s3_listing (size 0), so nothing fails and the user gets a report over files
    they never selected.
    """
    fake = _FakeS3()
    fake.head_object = lambda Bucket, Key: {"ContentLength": 0}
    v.clients.s3 = lambda: fake
    listed = []
    v.s3_listing.list_data_objects = lambda bucket, prefix: (
        listed.append((bucket, prefix)) or iter([("alice/sales/a.csv", 10)])
    )
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(), None)

    assert listed == [(BUCKET, "alice/sales/")], "a zero-byte hit must not become a file"


def test_a_transient_head_error_is_retryable_not_a_folder():
    """Only a real 404 means "folder"; a 503 must not be mistaken for one — and must reach
    the SFN as a TransientError, the ONLY name in InspectSource's Retry list our own code
    can raise. A bare ClientError matches nothing there and would be recorded as a
    permanent failure carrying raw AWS text."""
    _setup([])
    fake = _FakeS3()

    def _boom(Bucket, Key):
        raise _FakeClientError("SlowDown")

    fake.head_object = _boom
    v.clients.s3 = lambda: fake
    with pytest.raises(TransientError):
        v.handler(_event(), None)


# ── FR-005: the per-file header probe ────────────────────────────────────────
#
# These drive REAL polars against real files (local paths for the s3:// path, a real
# gzip stream for the compressed path). Mocking the probe would assert nothing about the
# thing SPEC-111's DDL depends on.


class _ProbedS3(_FakeS3):
    """``_FakeS3``, with source objects the real probe reads, each ranged as S3 ranges it."""

    def __init__(self, sources):
        super().__init__()
        self.sources = {key: ranged_s3.RangedS3(blob) for key, blob in sources.items()}

    def head_object(self, Bucket, Key):
        if Key in self.sources:
            return self.sources[Key].head_object()
        return super().head_object(Bucket, Key)

    def get_object(self, Bucket, Key, Range=None):
        if Key in self.sources:
            return self.sources[Key].get_object(Bucket=Bucket, Key=Key, Range=Range)
        return super().get_object(Bucket, Key)


def _setup_probed(sources):
    """Point the verb at ``sources`` with the per-file probe left REAL, unlike ``_setup``."""
    fake = _ProbedS3(sources)
    v.clients.s3 = lambda: fake
    v.s3_listing.list_data_objects = lambda bucket, prefix: iter(
        [(key, len(blob)) for key, blob in sources.items()]
    )
    return fake


def test_a_parquet_folder_is_probed_through_each_files_footer_alone():
    blob = io.BytesIO()
    pl.DataFrame({
        "id": pl.Series(range(50_000), dtype=pl.Int64),
        "note": pl.Series(["x"] * 50_000),
    }).write_parquet(blob, row_group_size=5_000)
    data = blob.getvalue()
    fake = _setup_probed({"alice/sales/part-0.parquet": data})

    v.handler(_event(), None)

    assert _manifest_of(fake)["files"][0]["columns"] == [
        {"name": "id", "type": "bigint"},
        {"name": "note", "type": "string"},
    ]
    source = fake.sources["alice/sales/part-0.parquet"]
    assert source.served == struct.unpack("<I", data[-8:-4])[0] + 8, "only the trailer and the footer"


def _not_parquet():
    return b"PAR1" + bytes(64) + b"PAR2"


def _footer_over_the_bound():
    """Built when the test runs, not at collection, so 32 MiB is not held for the whole suite."""
    declared = bounded_read.DEFAULT_PROBE_MAX_BYTES + 1
    return b"PAR1" + bytes(declared) + struct.pack("<I", declared) + b"PAR1"


@pytest.mark.parametrize(
    ("build", "reason"),
    [(_not_parquet, "does not end in PAR1"), (_footer_over_the_bound, "probe bound")],
    ids=["not-parquet", "footer-over-the-bound"],
)
def test_a_parquet_file_whose_footer_the_probe_will_not_read_is_an_unreadable_header(build, reason):
    """Refused as the unreadable file it is, in the new reader's own words — a refusal from
    anywhere else would carry polars' text instead, which is how this tells the two apart."""
    fake = _setup_probed({"alice/sales/part-0.parquet": build()})

    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)

    assert err.value.reason == messages.UNREADABLE_HEADER
    assert reason in err.value.detail
    assert len(fake.sources["alice/sales/part-0.parquet"].ranges) == 1, "no footer may be fetched"


# ── FR-005: the gzip probe's byte bound ──────────────────────────────────────


# The probe checks its bounds after each chunk, so it can overshoot by at most one chunk.
_CHUNK_SLACK = 256 * 1024


# ── FR-006: the manifest and the bounded state output ────────────────────────


def _manifest_of(fake):
    manifests = [put for put in fake.puts if put["Bucket"] == BUCKET]
    assert len(manifests) == 1, f"expected exactly one manifest write, got {len(manifests)}"
    return json.loads(manifests[0]["Body"])


# ── FR-006: the state payload bound ──────────────────────────────────────────


# -- SPEC-132: the narrative ------------------------------------------------------------


def _probe_that_quotes_a_cell(secret):
    def _boom(bucket, key, fmt):
        try:
            raise ValueError(f"could not parse '{secret}' as dtype i64")
        except ValueError as exc:
            raise TerminalError(
                messages.UNREADABLE_HEADER,
                f"could not read the schema of {key}: {exc}",
                tokens={"object": key},
            ) from exc

    return _boom


def test_ACCEPTED_the_span_error_stack_may_carry_file_contents(monkeypatch, captured_events):
    """CHARACTERISATION of an ACCEPTED behaviour (user decision, 2026-07-23), not a gap.

    `log-foundry`'s `end_event` attaches `traceback.format_exception(...)` to every failed
    span, and that walks the `__cause__` chain — so the polars message, cell value and all,
    lands in `error.stack` on the span.end of both the step and the handler. Suppressing
    `detail` does nothing about it, and neither would fixing the raise site, since
    `raise ... from exc` is what puts the cause's text there.

    The user accepted this rather than stripping it: `logs/` is admin-only, and a stack is
    diagnostic metadata an admin debugging a failed run needs. The absolute no-file-contents
    rule binds a **field** a verb chooses to emit (asserted by the test above); it does not
    bind an automatic traceback. See `docs/decisions/control-planes.md` and the module docstring in
    `cpcommon/observability.py`.

    Kept as a tripwire, NOT deleted: if this starts **failing**, `log-foundry` began stripping
    stacks (an upstream `capture_stack=False` landed), and the decision to accept them should
    be revisited in the open rather than the test quietly removed.
    """
    _setup([("alice/sales/a.csv", 10)])
    secret = "ACME-SECRET-CELL-VALUE"
    monkeypatch.setattr(v, "_probe_columns", _probe_that_quotes_a_cell(secret))

    with pytest.raises(TerminalError):
        v.handler(_event(), None)

    stacks = [
        e["function"]
        for e in captured_events.events
        if secret in str((e.get("error") or {}).get("stack", ""))
    ]
    assert stacks, (
        "error.stack no longer carries the cause's text — log-foundry began stripping stacks. "
        "Revisit the 2026-07-23 decision to accept them (decisions/) rather than deleting this."
    )
