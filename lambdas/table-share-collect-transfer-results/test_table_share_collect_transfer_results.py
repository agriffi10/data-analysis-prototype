"""Unit tests for the collect-transfer-results Lambda (SPEC-160 FR-004).

Attribution is where per-recipient isolation lives now that the fan-out is over
(recipient x object) pairs, so these tests are about who ends up with a table: a recipient with
one failed item does not, a recipient the guard already refused keeps its own reason, and an
export that cannot be attributed fails the whole request rather than reporting success.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_collect_transfer_results as m
from cpcommon import clients, config
from cpcommon.errors import TerminalError

_MANIFEST_KEY = "table-share/h/exec-1/results/run/manifest.json"


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return payload if isinstance(payload := self._payload, bytes) else json.dumps(payload).encode()


class _FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, **kwargs):
        try:
            return {"Body": _Body(self.objects[kwargs["Key"]])}
        except KeyError as err:
            raise _S3Error("NoSuchKey") from err


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


def _setup(objects=None):
    clients._s3 = _FakeS3(objects or {})
    sent = []
    m.notify.emit_notification = lambda user, message, **_: sent.append((user, message))
    return sent


def _resolved(name, kind="user"):
    return {
        "kind": kind,
        "name": name,
        "valid": True,
        "database": name,
        "destBucket": "user-bkt",
        "destPrefix": f"{name}/shared_tables/orders_copy/",
    }


def _item(recipient):
    return {"recipient": recipient, "kind": "user", "srcKey": "alice/sales/p.parquet"}


def _event(guard_results, item_count=2):
    return {
        "actor": "alice",
        "source": {"database": "alice", "table": "sales"},
        "tableName": "orders_copy",
        "guardResults": guard_results,
        "transfer": {"itemCount": item_count, "resultsPrefix": "table-share/h/exec-1/results"},
        "mapRun": {
            "MapRunArn": "arn:aws:states:us-east-1:1:mapRun/m/r",
            "ResultWriterDetails": {"Bucket": "admin-bkt", "Key": _MANIFEST_KEY},
        },
    }


def _export(failures=(), failed_batches=(), copied=None):
    """A results export: one SUCCEEDED file carrying per-item failures, one FAILED file.

    The item counts matter as much as the failures — the collector reconciles what the export
    accounts for against the manifest's own `itemCount` (default 2 here), so a fixture that
    under-reports is itself a valid test of that guard.
    """
    objects = {
        _MANIFEST_KEY: {
            "ResultFiles": {
                "SUCCEEDED": [{"Key": "r/SUCCEEDED_0.json"}],
                "FAILED": [{"Key": "r/FAILED_0.json"}] if failed_batches else [],
            }
        },
        "r/SUCCEEDED_0.json": [
            {
                "Status": "SUCCEEDED",
                "Output": json.dumps({
                    "copied": 2 - len(failures) - len(failed_batches) if copied is None else copied,
                    "failures": list(failures),
                }),
                "OutputDetails": {"Included": True},
            }
        ],
    }
    if failed_batches:
        objects["r/FAILED_0.json"] = [
            {
                "Status": "FAILED",
                "Input": json.dumps({"Items": [_item(name) for name in failed_batches]}),
                "InputDetails": {"Included": True},
                "OutputDetails": {"Included": False},
            }
        ]
    return objects


def test_a_clean_transfer_leaves_every_recipient_ok():
    _setup(_export())

    out = m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}]), None)

    assert [(e["name"], e["status"]) for e in out["outcomes"]] == [("bob", "ok")]
    assert out["outcomes"][0]["recipient"] == _resolved("bob")


def test_a_recipient_with_one_failed_item_gets_no_table():
    """FR-004 AC4 — a partial copy under a table definition is worse than no table."""
    _setup(_export(failures=[{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]))

    out = m.handler(
        _event([{"status": "ok", "recipient": _resolved("bob")}, {"status": "ok", "recipient": _resolved("carol")}]),
        None,
    )

    by_name = {e["name"]: e for e in out["outcomes"]}
    assert by_name["bob"]["status"] == "ok"
    assert by_name["carol"]["status"] == "failed"
    assert by_name["carol"]["reason"] == "copy_failed"
    assert by_name["carol"]["recipient"] is None, "a failed recipient must not reach create-table"


class _FakeSqs:
    """Records every send the real notification sender makes.

    Attributes:
      calls: The keyword arguments of each ``send_message``.
    """

    def __init__(self):
        """Starts with nothing sent.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls = []

    def send_message(self, **kwargs):
        """Keeps one send.

        Args:
          **kwargs: The send's arguments.

        Returns:
          A response carrying a message id.

        Raises:
          None.
        """
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def test_a_copy_failure_is_told_under_the_runs_name_and_the_name_reaches_create_table(monkeypatch):
    """The collector hands the notifier, and the finish Map, the state that carries the execution name.

    Table-share's only run identity is the name the machine stamps, and every verb between the stamp
    and create-table passes the state on in Python, where no template pin can see a key dropped.
    Driven through the real sender, so the id asserted is the one the queue would compare.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      None.

    Raises:
      AssertionError: If the copy failure's id does not name the run, or the name is dropped from
        the state create-table's notices are built from.
    """
    clients._s3 = _FakeS3(_export(failures=[{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]))
    queue = _FakeSqs()
    monkeypatch.setattr(clients, "_sqs", queue)
    monkeypatch.setattr(clients, "_sqs_bounded", queue)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/n.fifo", raising=False)
    event = {
        **_event([{"status": "ok", "recipient": _resolved("bob")}, {"status": "ok", "recipient": _resolved("carol")}]),
        "execution": {"name": "exec-1"},
    }

    out = m.handler(event, None)

    assert [call["MessageDeduplicationId"] for call in queue.calls] == ["exec-1:failure:copy_failed:user:carol"]
    assert out["execution"] == {"name": "exec-1"}


def test_an_export_that_covers_only_some_batches_fails_the_whole_request():
    """The silent success a shape check cannot catch (SPEC-160 review).

    An export can be perfectly well-formed and still account for fewer items than the manifest
    listed — a group this reader does not know about, a truncated write. Read as a clean run it
    would give every recipient a table over a dataset that may be missing objects, which is the
    one outcome this plane must never produce. So the counts must reconcile.
    """
    _setup(_export())

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}], item_count=99), None)
    assert caught.value.reason == "transfer_results_unreadable"


def test_a_stalled_queue_holds_the_copy_failure_notices_for_one_deadline(stalled_sends, caplog):
    """The notices share one budget: two start before its deadline and every later one is refused,
    where a budget per notice would start all five before the outcomes reach the finish Map."""
    names = [f"user{i}" for i in range(5)]
    clients._s3 = _FakeS3(
        _export(failures=[{"recipient": n, "kind": "user", "reason": "copy_failed"} for n in names])
    )
    event = _event([{"status": "ok", "recipient": _resolved(n)} for n in names])

    out = m.handler(event, None)

    assert [o["reason"] for o in out["outcomes"]] == ["copy_failed"] * 5
    assert stalled_sends.started == 2
    assert stalled_sends.reasons(caplog.records) == (
        ["notifications: a call ran past 0.05s"] * 2 + ["notifications ran out of time"] * 3
    )

