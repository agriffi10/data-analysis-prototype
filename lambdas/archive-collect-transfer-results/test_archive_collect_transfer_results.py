"""Unit tests for the archive collect-transfer-results Lambda (SPEC-169 FR-004).

**This is the commit gate's own suite, and the whole spec turns on it.** The verdict it computes
decides whether a user's only copy of a folder is deleted, so every way of being short is driven
from a FIXTURED ``ResultWriter`` export rather than from a stubbed reader — the export's shape is
the thing that surprised this fleet once already (Step Functions files a child by its execution
STATUS, and the batch copier deliberately succeeds while carrying per-item failures).

The structural half of FR-004 AC2 — that no path in the ASL leads from a shortfall to the deletion
— lives in ``test_state_machine_archive.py``, because it is a property of the graph rather than of
this verb.

Runnable under pytest or directly: python3 test_archive_collect_transfer_results.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_collect_transfer_results as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_RESULTS = f"archive/{_REQUEST_ID}/results/abcdef"


class _FakeS3:
    """Serves a Map Run's exported results out of an in-memory bucket."""

    def __init__(self, objects):
        self._objects = objects
        self.gets = []

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")

        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._objects[Key])}


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


def _succeeded_record(copied, failures=0):
    """One SUCCEEDED child record, in the shape Step Functions exports it.

    The batch verb's own output is a JSON STRING inside the record, which is the detail a reader
    written against a guess gets wrong.
    """
    return {
        "Output": json.dumps({
            "copied": copied,
            "failures": [
                {"recipient": None, "kind": None, "reason": "copy_failed"} for _ in range(failures)
            ],
        })
    }


def _failed_record(items):
    """One FAILED child record: no usable output, so attribution comes from its INPUT."""
    return {"Input": json.dumps({"Items": [{"srcKey": f"alice/f{i}.csv"} for i in range(items)]})}


def _export(succeeded=(), failed=()):
    """A whole ResultWriter export — the run manifest plus the group files it lists."""
    objects = {}
    result_files = {}
    if succeeded:
        objects[f"{_RESULTS}/SUCCEEDED_0.json"] = json.dumps(list(succeeded)).encode()
        result_files["SUCCEEDED"] = [{"Key": f"{_RESULTS}/SUCCEEDED_0.json", "Size": 1}]
    if failed:
        objects[f"{_RESULTS}/FAILED_0.json"] = json.dumps(list(failed)).encode()
        result_files["FAILED"] = [{"Key": f"{_RESULTS}/FAILED_0.json", "Size": 1}]
    objects[f"{_RESULTS}/manifest.json"] = json.dumps({"ResultFiles": result_files}).encode()
    return objects


def _install(objects):
    fake = _FakeS3(objects)
    clients._s3 = fake
    return fake


def _event(item_count=8, object_count=8, results=True):
    event = {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": f"personal/alice/archive/{_REQUEST_ID}/"},
        "objectCount": object_count,
        "totalBytes": 1234,
        "transfer": {
            "manifestBucket": "admin-bkt",
            "manifestKey": f"archive/{_REQUEST_ID}/e1/transfer-manifest.jsonl",
            "resultsBucket": "admin-bkt",
            "resultsPrefix": f"archive/{_REQUEST_ID}/results",
            "itemCount": item_count,
        },
    }
    if results:
        event["mapRun"] = {
            "ResultWriterDetails": {"Bucket": "admin-bkt", "Key": f"{_RESULTS}/manifest.json"}
        }
    return event


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


# ── The one verdict the deletion hangs on ────────────────────────────────────


def test_a_complete_transfer_commits():
    """Every object copied: the gate's committing arm, and the only route to a deletion."""
    _install(_export(succeeded=[_succeeded_record(8)]))

    result = m.handler(_event(), None)

    assert result["transferOutcome"] == {
        "copied": 8,
        "failed": 0,
        "expected": 8,
        "complete": True,
    }


def test_one_failed_item_out_of_thousands_refuses_the_whole_archive():
    """**The rule the feature rests on, and the number is deliberately lopsided.** 7,999 of 8,000
    objects copied is not "nearly done" when the next state deletes all 8,000 of the originals."""
    _install(_export(succeeded=[_succeeded_record(7_999, failures=1)]))

    result = m.handler(_event(item_count=8_000, object_count=8_000), None)

    assert result["transferOutcome"]["complete"] is False
    assert result["transferOutcome"]["copied"] == 7_999
    assert result["transferOutcome"]["failed"] == 1


def test_a_failure_reported_inside_a_SUCCEEDED_record_is_still_a_failure():
    """**The half of the export a reader written against a guess misses.** Step Functions files a
    child by its execution STATUS, and the batch copier deliberately SUCCEEDS while carrying
    per-item failures — so a collector reading only FAILED_n.json reports universal success over
    an incomplete archive, and here that reported success is a deletion."""
    fake = _install(_export(succeeded=[_succeeded_record(3, failures=1)]))

    result = m.handler(_event(item_count=4, object_count=4), None)

    assert any("SUCCEEDED" in key for key in fake.gets), "the succeeded half was never read"
    assert result["transferOutcome"]["complete"] is False


def test_a_whole_batch_that_failed_is_attributed_from_its_input():
    """A batch that failed as a whole reported nothing per item, so which of its items landed is
    genuinely unknown — every one of them counts as failed, which is fail-closed on purpose."""
    _install(_export(succeeded=[_succeeded_record(4)], failed=[_failed_record(4)]))

    result = m.handler(_event(item_count=8, object_count=8), None)

    assert result["transferOutcome"] == {
        "copied": 4,
        "failed": 4,
        "expected": 8,
        "complete": False,
    }


def test_an_export_that_accounts_for_fewer_items_than_the_manifest_is_a_shortfall():
    """FR-004 AC2's second half: a count mismatch with NO reported failures. It takes the
    rollback branch rather than raising, because the outcome is identical — the archive copy is
    partial, so it is removed and the source is left where it was."""
    _install(_export(succeeded=[_succeeded_record(6)]))

    result = m.handler(_event(item_count=8, object_count=8), None)

    assert result["transferOutcome"]["complete"] is False
    assert result["transferOutcome"]["failed"] == 2


def test_a_manifest_that_disagrees_with_the_plan_is_refused():
    """A check file-send cannot make: there a manifest line is one (recipient, object) pair, so
    the two counts differ by design. Here they are the same number written twice, and a
    disagreement means the manifest was built from something other than the plan this run
    expanded — the one shape where every downstream count agrees with itself and is wrong."""
    _install(_export(succeeded=[_succeeded_record(8)]))

    with pytest.raises(TerminalError) as err:
        m.handler(_event(item_count=8, object_count=9), None)

    assert err.value.reason == "transfer_results_unreadable"


@pytest.mark.parametrize("count", [0, None, -1, True])
def test_an_unusable_item_count_is_refused_rather_than_read_as_nothing_to_do(count):
    """Reached only after the Map has run, so "no items" is not a state this verb can be in — an
    archive of nothing is refused at the Choice before it (FR-001 AC6)."""
    _install(_export(succeeded=[_succeeded_record(1)]))

    with pytest.raises(TerminalError):
        m.handler(_event(item_count=count), None)


def test_a_missing_results_pointer_is_refused_rather_than_read_as_success():
    """The run has finished by the time this verb is invoked, so an absent pointer is a fault
    rather than a race — and reading it as "no failures found" would delete the source without a
    single S3 call having been made."""
    _install(_export(succeeded=[_succeeded_record(8)]))

    with pytest.raises(TerminalError) as err:
        m.handler(_event(results=False), None)

    assert err.value.reason == "transfer_results_unreadable"


def test_an_omitted_child_payload_is_unattributable_and_refuses():
    """Step Functions exports ``Included: false`` when a payload is too large. Those items cannot
    be accounted for, and "no failures found" over them is the silent success this whole gate
    exists to prevent."""
    export = _export(succeeded=[{"OutputDetails": {"Included": False}, "Output": ""}])
    _install(export)

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "transfer_results_unreadable"


def test_an_unreadable_export_notifies_the_actor_and_leaves_the_source_alone(_no_real_notifications):
    """The source is untouched on this path, which is the property that matters. The partial copy
    is left to the archive bucket's own lifecycle, because a collector that cannot read the export
    cannot say what there is to roll back."""
    _install({})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "transfer_results_unreadable"
    assert [user for user, _ in _no_real_notifications] == ["alice"]


def test_the_request_travels_through_so_the_committing_arm_can_use_it():
    """The record, the deletion and the receipt all read the archive destination, the source and
    the counts off the state."""
    _install(_export(succeeded=[_succeeded_record(8)]))

    result = m.handler(_event(), None)

    assert result["archive"]["root"].endswith("/")
    assert result["source"]["name"] == "alice"
    assert result["objectCount"] == 8


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
