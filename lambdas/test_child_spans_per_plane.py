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
      None.

    Raises:
      None.
    """
    clients._s3 = _CopyS3()
    module.handler({"Items": _copy_items()}, None)


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

    Args:
      monkeypatch: Used to silence the verb's success notification.

    Returns:
      None.

    Raises:
      None.
    """
    clients._athena = _Athena()
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
      None.

    Raises:
      KeyError: For a plane this harness does not know how to drive.
    """
    if plane == "archive":
        _drive_copy(archive_copy_objects)
    elif plane == "file-ops":
        _drive_copy(file_ops_copy_objects)
    elif plane == "file-send":
        _drive_copy(file_send_copy_objects)
    elif plane == "table-share":
        _drive_copy(table_share_copy_objects)
    elif plane == "shared-space":
        _drive_add_members()
    elif plane == "results-conversion":
        _drive_convert(tmp_path, monkeypatch)
    elif plane == "table-builder":
        _drive_execute_ddl(monkeypatch)
    else:
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
    _drive(plane, tmp_path, monkeypatch)

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
    """A catalog that applies what it is told, so apply-refresh's read-back agrees.

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
            "partitionKeys": [],
            "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        },
        None,
    )


#: The WORST-CASE verb on each plane, and the events this spec adds to it. Two per step — a
#: `span.start` and a `span.end` — so these are the step counts doubled, MEASURED by driving each
#: verb and counting through the sink rather than by counting decorators.
#:
#: A RATCHET, not a budget, and the distinction is the point. FR-005 asks for a budget in events
#: per service-day derived from the day-object ceiling and the fleet's invocation rate. Neither
#: input can be established today — `log_sweep.LARGE_OBJECT_WARN_BYTES` is a detector sized to fire
#: long before anything binds, not a ceiling, and this fleet has no production traffic to rate.
#: Both are recorded in `docs/testing/owed.md` rather than met with numbers chosen to pass. What
#: this table does hold is that the volume cannot grow without somebody editing it.
#:
#: The values carry no headroom deliberately: a step added to any of these verbs SHOULD stop here
#: and be argued for, since that is the whole decision this spec exists to make carefully. The
#: headroom that matters is the fraction of a day object left for SPEC-227 and later, which is
#: unquantifiable until the ceiling is.
_ADDED_EVENTS = {
    "archive": ("copy-objects", 2),
    "file-ops": ("copy-objects", 2),
    "file-send": ("copy-objects", 2),
    "table-share": ("copy-objects", 2),
    "shared-space": ("add-members", 4),
    "results-conversion": ("convert", 6),
    "table-builder": ("apply-refresh", 6),
}

#: The span names this spec introduced. Counting events by NAME rather than counting every span
#: is what keeps the measurement about this spec: a plane's pre-existing root span and its
#: narrative are not this spec's to budget.
_SPEC_SPANS = frozenset(
    {
        "copy-batch",
        "write-manifest",
        "read-failed-items",
        "write-roster",
        "notify-members",
        "download-results",
        "write-conversion",
        "upload-conversion",
        "athena-run-ddl",
        "infer-columns",
        "glue-get-table",
        "glue-update-table",
        "glue-read-back-table",
    }
)


@pytest.mark.parametrize("plane", sorted(_ADDED_EVENTS), ids=sorted(_ADDED_EVENTS))
def test_the_events_this_spec_adds_to_each_planes_worst_case_verb(
    plane, captured_events, tmp_path, monkeypatch
):
    """Measured by driving the verb and counting, never by counting decorators.

    Counting decorators is what makes a volume claim wrong: it cannot see a step reached twice,
    a step on a path the verb does not take, or a step inside a worker pool emitting one span
    per item with no parent. Driving and counting sees all three.

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
    verb, expected = _ADDED_EVENTS[plane]
    if plane == "table-builder":
        _drive_apply_refresh(monkeypatch)
    else:
        _drive(plane, tmp_path, monkeypatch)

    added = [
        event
        for event in captured_events.events
        if event["message"] in ("span.start", "span.end")
        and event["function"] in _SPEC_SPANS
    ]
    assert added, (
        f"{plane}: driving {verb!r} emitted none of this spec's spans, so the count below is a "
        "comparison against an empty collector rather than a measurement"
    )
    assert len(added) == expected, (
        f"{plane}: {verb!r} now emits {len(added)} of this spec's events, not {expected}. Every "
        "one is an SQS message and a line in a day object the sweep rewrites in full, so a "
        "change here is a volume decision — argue for it and move the number."
    )
