"""Holds each of the seven flat planes to emitting a child span, reddenable one plane at a time.

The guard exists because the failure it catches is silent. A refactor that moves a plane off an
instrumented path takes that plane's child spans with it and changes nothing else: the verb still
runs, still narrates, still reports a root span, and reads as instrumented while reporting one flat
duration for everything it did.

**Each case names a VERB and a SPAN rather than asserting "this plane has some child span".** Four
of the seven reach their span through the same shared function, so a plane with two independent
sources would keep passing after one of them was removed — and the assertion that cannot fail for
half its population is the one nobody notices has stopped working.

**How each case was proven, and why the four transfer planes are proven differently.** Every case
reddens on its own and on nothing else, verified by planting. For shared-space, results-conversion
and table-builder the plant is removing that plane's step, which is private to it. The other four
reach `copy-batch` through one shared function, so removing THAT step reddens all four at once and
proves nothing per plane. They are planted the way they would actually fail instead — the verb is
moved off the instrumented path, which is exactly the silent refactor described above. Seven plants,
seven single-case failures.

Runnable under pytest. It drives real handlers, so it needs the layer paths and the environment
baseline `conftest.py` sets.
"""

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent

for _directory in (
    "shared-space-common",
    "archive-copy-objects",
    "file-ops-copy-objects",
    "file-send-copy-objects",
    "table-share-copy-objects",
    "shared-space-add-members",
    "results-conversion-convert",
    "table-builder-execute-ddl",
    "table-builder-apply-refresh",
):
    _path = str(_HERE / _directory)
    if _path not in sys.path:
        sys.path.append(_path)

import add_members
import archive_copy_objects
import execute_ddl
import file_ops_copy_objects
import file_send_copy_objects
import pytest
import rc_convert
import table_share_copy_objects
from botocore.exceptions import ClientError
from cpcommon import clients, config
from fakes import install

#: One (plane, verb, span) triple per flat plane. The verb is the root span's name as `traced`
#: stamps it, which for the four transfer planes is the same word in four different services —
#: they are told apart by which module the case drives, not by a field on the event, because the
#: capturing fixture reconfigures the library with one service name for the whole process.
_CASES = [
    ("archive", "copy-objects", "copy-batch"),
    ("file-ops", "copy-objects", "copy-batch"),
    ("file-send", "copy-objects", "copy-batch"),
    ("table-share", "copy-objects", "copy-batch"),
    ("shared-space", "add-members", "write-roster"),
    ("results-conversion", "convert", "download-results"),
    ("table-builder", "execute-ddl", "athena-run-ddl"),
]


class _CopyS3:
    """An S3 client that accepts every copy, for the four transfer planes' copy verbs.

    Attributes:
      copies: One entry per ``CopyObject``.
    """

    def __init__(self):
        """Starts with no recorded copies.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.copies = []

    def copy_object(self, **kwargs):
        """Accepts one copy.

        Args:
          **kwargs: The ``CopyObject`` arguments.

        Returns:
          None.

        Raises:
          None.
        """
        self.copies.append(kwargs)


class _ConvertS3:
    """The four calls one personal conversion makes, and nothing else.

    Deliberately refuses a read aimed anywhere but the user-space bucket, the way the execution
    role's grant does — a fake that ignored the bucket would be green against a converter reading
    from the destination.

    Attributes:
      payload: The CSV bytes the result object serves.
      written: The bodies handed to ``put_object``.
    """

    def __init__(self, payload):
        """Serves one result object.

        Args:
          payload: The CSV bytes.

        Returns:
          None.

        Raises:
          None.
        """
        self.payload = payload
        self.written = []

    def head_object(self, **kwargs):
        """Reports the result object's size.

        Args:
          **kwargs: The ``HeadObject`` arguments.

        Returns:
          The content length.

        Raises:
          ClientError: When aimed outside the user-space bucket.
        """
        self._only_user_space(kwargs["Bucket"], "HeadObject")
        return {"ContentLength": len(self.payload)}

    def download_fileobj(self, bucket, key, handle):
        """Streams the result object onto the handle.

        Args:
          bucket: The source bucket.
          key: The source key.
          handle: The open file to write into.

        Returns:
          None.

        Raises:
          ClientError: When aimed outside the user-space bucket.
        """
        self._only_user_space(bucket, "GetObject")
        handle.write(self.payload)

    def put_object(self, **kwargs):
        """Accepts the converted file.

        Args:
          **kwargs: The ``PutObject`` arguments.

        Returns:
          An empty response.

        Raises:
          None.
        """
        body = kwargs["Body"]
        self.written.append(body.read() if hasattr(body, "read") else body)
        return {}

    @staticmethod
    def _only_user_space(bucket, operation):
        """Refuses a read outside the actor's own space, as the grant does.

        Args:
          bucket: The bucket the call names.
          operation: The operation name, for the error.

        Returns:
          None.

        Raises:
          ClientError: ``AccessDenied`` for any other bucket.
        """
        if bucket != "user-bkt":
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "no grant"}}, operation
            )


class _Athena:
    """An Athena client whose statement succeeds on the first poll."""

    def start_query_execution(self, **kwargs):
        """Starts the statement.

        Args:
          **kwargs: The ``StartQueryExecution`` arguments.

        Returns:
          The execution id.

        Raises:
          None.
        """
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, QueryExecutionId):
        """Reports the statement as succeeded.

        Args:
          QueryExecutionId: The execution id.

        Returns:
          A succeeded status.

        Raises:
          None.
        """
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}


def _copy_items(destination_bucket="user-bkt"):
    """Two manifest lines, so a per-item span would be visible as two rather than one.

    Args:
      destination_bucket: Where the copies land.

    Returns:
      A list of transfer items.

    Raises:
      None.
    """
    return [
        {
            "recipient": "bob",
            "kind": "user",
            "itemKey": f"alice/part-{i}/",
            "srcBucket": "user-bkt",
            "srcKey": f"alice/part-{i}.parquet",
            "destBucket": destination_bucket,
            "destKey": f"bob/part-{i}.parquet",
            "size": 10,
        }
        for i in range(2)
    ]


def _drive_copy(module):
    """Drives one plane's copy verb over a two-item batch.

    Args:
      module: The verb module.

    Returns:
      The module that was driven, so a case can prove it drove its own plane's.

    Raises:
      None.
    """
    clients._s3 = _CopyS3()
    module.handler({"Items": _copy_items()}, None)
    return module


def _drive_add_members():
    """Drives the shared-space add-members verb over two new members.

    Two rather than one deliberately: both of this plane's spans wrap a loop, and at one member
    a span around the loop and a span around its body are indistinguishable.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}, "carol": {}}
    registry = {
        "name": "sales",
        "owner": "alice",
        "members": ["alice"],
        "status": "active",
        "createdAt": "t0",
        "lastRequestId": "r0",
    }
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    add_members.handler(
        {
            "space": "sales",
            "requestId": "r1",
            "registry": registry,
            "payload": {"members": ["bob", "carol"]},
        },
        None,
    )


def _drive_convert(tmp_path, monkeypatch):
    """Drives the results-conversion convert verb on a personal-space conversion.

    Args:
      tmp_path: A scratch directory for this test.
      monkeypatch: Used to point the verb at that directory and silence its notifier.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setattr(rc_convert, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(rc_convert.notify, "emit_notification", lambda *a, **kw: None)
    clients._s3 = _ConvertS3(b'"a"\n"1"\n')
    rc_convert.handler(
        {
            "requestId": "r1",
            "username": "alice",
            "queryExecutionId": "q-1",
            "resultsKey": "alice/results/q1.csv",
            "resultsBytes": 8,
            "format": "parquet",
            "onConflict": "refuse",
            "columns": [{"name": "a", "type": "varchar"}],
            "destination": {
                "bucket": "user-bkt",
                "key": "alice/out/q1.parquet",
                "prefix": "out/",
                "spaceKind": "personal",
                "spaceName": None,
            },
        },
        None,
    )


def _drive_execute_ddl(monkeypatch):
    """Drives the table-builder execute-ddl verb through a succeeding statement.

    The catalog fake is the one apply-refresh uses: it serves a flat table at the location this
    event declares, which is what the verb's post-condition reads back before it reports the
    table created.

    Args:
      monkeypatch: Used to silence the verb's success notification.

    Returns:
      None.

    Raises:
      None.
    """
    clients._athena = _Athena()
    clients._glue = _Glue()
    monkeypatch.setattr(execute_ddl.notify, "emit_created", lambda event: None)
    config.NOTIFICATIONS_QUEUE_URL = ""
    execute_ddl.handler(
        {
            "actor": "alice",
            "space": {
                "kind": "personal",
                "bucket": "user-bkt",
                "prefix": "alice/sales/",
                "database": "alice",
            },
            "tableName": "sales",
            "location": "s3://user-bkt/alice/sales/",
            "partitionKeys": [],
            "ddl": "CREATE EXTERNAL TABLE IF NOT EXISTS sales (a string)",
            "requestId": "r1",
        },
        None,
    )


def _drive(plane, tmp_path, monkeypatch):
    """Runs one plane's named verb to a successful completion.

    Args:
      plane: The plane whose verb to drive.
      tmp_path: A scratch directory, used by the conversion.
      monkeypatch: Used by the conversion and the DDL run.

    Returns:
      The verb module that was driven.

    Raises:
      KeyError: For a plane this harness does not know how to drive.
    """
    if plane == "archive":
        return _drive_copy(archive_copy_objects)
    if plane == "file-ops":
        return _drive_copy(file_ops_copy_objects)
    if plane == "file-send":
        return _drive_copy(file_send_copy_objects)
    if plane == "table-share":
        return _drive_copy(table_share_copy_objects)
    if plane == "shared-space":
        _drive_add_members()
        return add_members
    if plane == "results-conversion":
        _drive_convert(tmp_path, monkeypatch)
        return rc_convert
    if plane == "table-builder":
        _drive_execute_ddl(monkeypatch)
        return execute_ddl
    raise KeyError(f"no driver for plane {plane!r}")


@pytest.mark.parametrize(
    ("plane", "verb", "span"), _CASES, ids=[case[0] for case in _CASES]
)
def test_each_flat_plane_emits_a_named_child_span_inside_its_verbs_span(
    plane, verb, span, captured_events, tmp_path, monkeypatch
):
    """One plane, one named verb, one named span, parented to that verb's root.

    The parentage is the half that a weaker guard drops. A span with a null ``parent_span_id``
    is what instrumentation placed where the trace context does not reach emits — inside a
    worker pool, say — and it satisfies "this plane emits a span of that name" while being
    unattributable to the run that produced it.

    Args:
      plane: The control plane under test.
      verb: The root span's name.
      span: The child span's name.
      captured_events: The shared capturing sink.
      tmp_path: A scratch directory for the conversion driver.
      monkeypatch: Used by two of the drivers.

    Returns:
      None.

    Raises:
      None.
    """
    driven = _drive(plane, tmp_path, monkeypatch)

    if span == "copy-batch":
        assert plane.replace("-", "_") in driven.__name__, (
            f"{plane}: the dispatch drove {driven.__name__!r}. The four transfer planes assert "
            "the SAME verb and span names, so only the module picked tells their cases apart and "
            "a copy-paste in the dispatch would leave all four green with three never exercised. "
            "The other three planes need no such check — their verb and span names are unique."
        )
    roots = captured_events.spans(verb)
    assert len(roots) == 1, (
        f"{plane}: driving {verb!r} produced {len(roots)} root spans, so the child assertion "
        "below has no single parent to check against"
    )
    children = captured_events.child_spans(verb, name=span)
    assert len(children) == 1, (
        f"{plane}: {verb!r} emitted {len(children)} {span!r} child spans, expected exactly one — "
        f"this plane reports one flat duration for everything {verb!r} does"
    )
    assert children[0]["parent_span_id"] == roots[0]["span_id"], (
        f"{plane}: {verb!r}'s {span!r} span is not parented to the verb's own span, so it "
        "cannot be attributed to the run that produced it"
    )


def test_the_case_table_covers_every_flat_plane():
    """A positive control over the population the parametrisation is written from.

    Seven planes were named as having no child spans at all. A case table that quietly lost one
    would leave that plane unguarded while every remaining case still passed.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert {case[0] for case in _CASES} == {
        "archive",
        "file-ops",
        "file-send",
        "results-conversion",
        "shared-space",
        "table-builder",
        "table-share",
    }, f"the case table covers {sorted(case[0] for case in _CASES)}"
    assert len(_CASES) == 7, "a plane is named twice, so one of the seven has no case"


def test_the_collector_collects_through_this_harness(captured_events):
    """A positive control that this file's drivers produce events at all.

    Every assertion above is over what the sink collected. A harness that stopped collecting —
    a fixture that no longer swaps the sink, a driver that silently stopped reaching its verb —
    turns the count assertions into comparisons against zero, which fail loudly, and the
    parentage assertion into one that is never reached. This says so in one named place.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _drive_copy(archive_copy_objects)

    assert captured_events.events, "the sink collected nothing through this file's drivers"
    assert captured_events.spans("copy-objects"), "no root span reached the sink"


class _Glue:
    """A catalog that applies what it is told, so a read-back agrees with what was written.

    Serves both table-builder drivers: execute-ddl reads this table back to confirm the table
    standing is the one its request declared, and apply-refresh writes to it and re-reads.

    Attributes:
      table: The live table ``get_table`` reports, updated in place by ``update_table``.
    """

    def __init__(self):
        """Serves one two-column table.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.table = {
            "Name": "sales",
            "DatabaseName": "alice",
            "UpdateTime": "2026-02-01T00:00:00Z",
            "TableType": "EXTERNAL_TABLE",
            "PartitionKeys": [],
            "Parameters": {"EXTERNAL": "TRUE"},
            "StorageDescriptor": {
                "Location": "s3://user-bkt/alice/sales/",
                "Columns": [{"Name": "order_id", "Type": "string"}],
                "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde"},
            },
        }

    def get_table(self, **kwargs):
        """Reports the live table.

        Args:
          **kwargs: The ``GetTable`` arguments.

        Returns:
          The table.

        Raises:
          None.
        """
        return {"Table": self.table}

    def update_table(self, **kwargs):
        """Applies the update, so the read-back sees what was written.

        Args:
          **kwargs: The ``UpdateTable`` arguments.

        Returns:
          None.

        Raises:
          None.
        """
        self.table = {**self.table, **kwargs["TableInput"]}


def _drive_apply_refresh(monkeypatch):
    """Drives table-builder's apply-refresh, which is that plane's worst case at three spans.

    Args:
      monkeypatch: Used to silence the verb's outcome notification.

    Returns:
      None.

    Raises:
      None.
    """
    import apply_refresh

    clients._glue = _Glue()
    monkeypatch.setattr(
        apply_refresh.notify, "emit_refresh_outcome", lambda *a, **kw: None
    )
    config.NOTIFICATIONS_QUEUE_URL = ""
    apply_refresh.handler(
        {
            "mode": "refresh",
            "actor": "alice",
            "space": {
                "kind": "personal",
                "bucket": "user-bkt",
                "prefix": "alice/sales/",
                "database": "alice",
            },
            "tableName": "sales",
            "requestId": "r1",
            "format": "csv",
            "partitionKeys": [],
            "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        },
        None,
    )


#: The WORST-CASE verb on each plane, and the TOTAL span events one invocation of it emits — the
#: verb's own root span included. Two events per span, so these are (1 root + n steps) x 2.
#:
#: **Counting every span event rather than this spec's own span NAMES is the whole point.** A
#: by-name filter is blind in the only direction a volume guard matters: a step added later under a
#: new name is invisible to it, and so is a step planted inside `copy_batch`'s worker pool, which
#: emits ROOT spans with a null parent rather than children. Counting all of them catches an
#: addition, a removal, and the pool mistake with one number.
#:
#: A RATCHET, not the budget FR-005 asks for. It carries no headroom deliberately: a step added to
#: any of these verbs SHOULD stop here and be argued for, which is the decision this spec exists to
#: make carefully.
_SPAN_EVENTS_PER_INVOCATION = {
    "archive": ("copy-objects", 4),
    "file-ops": ("copy-objects", 4),
    "file-send": ("copy-objects", 4),
    "table-share": ("copy-objects", 4),
    "shared-space": ("add-members", 6),
    "results-conversion": ("convert", 8),
    "table-builder": ("apply-refresh", 8),
}

#: The band one serialized span event's size must stay inside, in bytes. The budget below divides
#: the day-object ceiling by a MEASURED event size, so a serialization change that inflated an
#: event would quietly shrink the budget while every count assertion stayed green. Measured at
#: ~400 bytes on this pin; the band is wide because the point is to catch a change of KIND, not to
#: pin a number that a field addition would redden.
_EVENT_BYTES_BAND = (150, 2000)


def _day_object_ceiling_bytes():
    """The sweep's own size constant, READ from the sweep rather than copied beside it.

    Copied, it would be a second home for a number whose only meaning is what the sweep does with
    it, and the two would drift. Read, a change to the sweep reddens the budget below.

    Args:
      None.

    Returns:
      The byte size at which the sweep calls out a day object's read-modify-write cost.

    Raises:
      None.
    """
    sweep = str(_HERE / "log-sweep")
    if sweep not in sys.path:
        sys.path.append(sweep)
    import log_sweep

    return log_sweep.LARGE_OBJECT_WARN_BYTES


@pytest.mark.parametrize(
    "plane", sorted(_SPAN_EVENTS_PER_INVOCATION), ids=sorted(_SPAN_EVENTS_PER_INVOCATION)
)
def test_the_span_events_each_planes_worst_case_verb_emits(
    plane, captured_events, tmp_path, monkeypatch
):
    """Measured by driving the verb and counting, never by counting decorators.

    Counting decorators is what makes a volume claim wrong: it cannot see a step reached twice, a
    step on a path the verb does not take, or a step inside a worker pool emitting one span per
    item with no parent. Driving and counting sees all three.

    Args:
      plane: The plane whose worst-case verb to measure.
      captured_events: The shared capturing sink.
      tmp_path: A scratch directory for the conversion driver.
      monkeypatch: Used by three of the drivers.

    Returns:
      None.

    Raises:
      None.
    """
    verb, expected = _SPAN_EVENTS_PER_INVOCATION[plane]
    if plane == "table-builder":
        _drive_apply_refresh(monkeypatch)
    else:
        _drive(plane, tmp_path, monkeypatch)

    spans = [
        event
        for event in captured_events.events
        if event["message"] in ("span.start", "span.end")
    ]
    assert spans, (
        f"{plane}: driving {verb!r} emitted no span events at all, so the count below is a "
        "comparison against an empty collector rather than a measurement"
    )
    assert len(spans) == expected, (
        f"{plane}: {verb!r} now emits {len(spans)} span events, not {expected}. Every one is an "
        "SQS message and a line in a day object the sweep rewrites in full, so a change here is a "
        "volume decision — argue for it and move the number."
    )


def test_the_events_per_service_day_budget_is_derived_from_the_sweeps_own_constant(
    captured_events,
):
    """The budget FR-005 asks for, in the direction that IS derivable, with its limits stated.

    The sweep writes one day object per service-day and rewrites it in full, so events per
    service-day is the bound that matters. The ceiling used here is
    `log_sweep.LARGE_OBJECT_WARN_BYTES`, read from the sweep rather than copied.

    **That constant is a detector, not the true ceiling, and using it is deliberately
    conservative.** The observability README states the sweep has 512 MB and that this constant
    "warns long before that becomes binding", and the sibling constant's own guard asserts memory
    is over four times it, because peak resident while appending is several multiples of the
    object. So the real ceiling is larger and a budget derived from this one errs safe. What is
    NOT derivable is the exact ceiling — the peak-resident multiple is nowhere measured — and the
    fleet's invocation rate, which does not exist on a system with no production traffic. Both are
    in `docs/testing/owed.md`; this asserts the half that stands without them.

    Args:
      captured_events: The shared capturing sink, used to measure a real event's size.

    Returns:
      None.

    Raises:
      None.
    """
    _drive_copy(archive_copy_objects)
    events = [e for e in captured_events.events if e["message"] == "span.start"]
    assert events, "no event to measure, so the budget below would divide by a guess"

    #: One NDJSON line as the sweep writes it: the event's JSON plus the newline it appends.
    bytes_per_event = max(len(json.dumps(event)) + 1 for event in events)
    low, high = _EVENT_BYTES_BAND
    assert low <= bytes_per_event <= high, (
        f"a span event serializes to {bytes_per_event} bytes, outside the {low}-{high} band the "
        "budget below is derived against — re-derive the budget rather than widening the band"
    )

    ceiling = _day_object_ceiling_bytes()
    budget = ceiling // bytes_per_event
    worst = max(count for _verb, count in _SPAN_EVENTS_PER_INVOCATION.values())
    sustainable = budget // worst

    assert budget > 0 and sustainable > 0, (
        f"the derivation collapsed: {ceiling} bytes / {bytes_per_event} bytes = {budget} events "
        f"per service-day, {sustainable} invocations of the worst verb"
    )
    assert sustainable > 1000, (
        f"at {ceiling // 1024 // 1024} MiB and {bytes_per_event} bytes an event, one service-day "
        f"holds {budget} events — {sustainable} invocations of the worst-case verb from this "
        "spec's spans alone. Below a thousand the spans, not the narrative, would be what sizes "
        "the day object, and the ratchet above stops being the right instrument."
    )
