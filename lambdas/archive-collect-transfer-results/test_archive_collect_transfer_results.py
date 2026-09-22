"""Unit tests for the archive collect-transfer-results Lambda (SPEC-169 FR-004).

**This is the commit gate's own suite, and the whole spec turns on it.** The verdict it computes
decides whether a user's only copy of a folder is deleted, so every way of being short is driven
from a FIXTURED ``ResultWriter`` export rather than from a stubbed reader — the export's shape is
the thing that surprised this fleet once already (Step Functions files a child by its execution
STATUS, and the batch copier deliberately succeeds while carrying per-item failures).

The structural half of FR-004 AC2 — that no path in the ASL leads from a shortfall to the deletion
— is a property of the graph rather than of
this verb.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
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


def _succeeded_record(copied, failures=0, reason="copy_failed", folders=0, flagged=True):
    """One SUCCEEDED child record, in the shape Step Functions exports it.

    The batch verb's own output is a JSON STRING inside the record, which is the detail a reader
    written against a guess gets wrong.

    ``reason`` is a parameter because the copy verb now emits two: a failed copy and an item it
    declined to overwrite, which the collector counts apart. ``folders`` is how many of the
    failures echo a folder placeholder's flag; the rest echo a file's. ``flagged=False`` writes
    the records a copy verb from before the flag wrote, which carry no flag at all.
    """
    return {
        "Output": json.dumps({
            "copied": copied,
            "failures": [
                {"folder": index < folders, "reason": reason} if flagged else {"reason": reason}
                for index in range(failures)
            ],
        })
    }


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


def _event(item_count=8, object_count=8, results=True, file_count=None):
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
    if file_count is not None:
        event["transfer"]["fileCount"] = file_count
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
        "occupied": 0,
        "complete": True,
        "shown": {"copied": 8, "total": 8, "occupied": 0},
    }


def test_one_failed_item_out_of_thousands_refuses_the_whole_archive():
    """**The rule the feature rests on, and the number is deliberately lopsided.** 7,999 of 8,000
    objects copied is not "nearly done" when the next state deletes all 8,000 of the originals.

    The failure record carries no folder flag, as one from a copy verb older than the flag
    does, so its kind is unknown and the counts a person is shown are the object counts rather
    than a guess — even though the block says ten of the objects are placeholders."""
    _install(_export(succeeded=[_succeeded_record(7_999, failures=1, flagged=False)]))

    result = m.handler(_event(item_count=8_000, object_count=8_000, file_count=7_990), None)

    assert result["transferOutcome"]["complete"] is False
    assert result["transferOutcome"]["copied"] == 7_999
    assert result["transferOutcome"]["failed"] == 1
    assert result["transferOutcome"]["shown"] == {"copied": 7_999, "total": 8_000, "occupied": 0}


def test_an_unreadable_export_notifies_the_actor_and_leaves_the_source_alone(_no_real_notifications):
    """The source is untouched on this path, which is the property that matters. The partial copy
    is left to the archive bucket's own lifecycle, because a collector that cannot read the export
    cannot say what there is to roll back."""
    _install({})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "transfer_results_unreadable"
    assert [user for user, _ in _no_real_notifications] == ["alice"]


def test_items_left_alone_are_counted_apart_from_items_that_failed():
    """FR-004 AC1. Both counts make the verdict incomplete — the restore gate routes either to
    the arm that deletes nothing — so the split changes no decision. What it changes is the
    sentence: "we could not copy your file" and "your own newer file was in the way, so we left
    it" call for different next actions from the user."""
    _install(
        _export(
            succeeded=[
                _succeeded_record(3, failures=2, reason="destination_occupied_during_copy")
            ]
        )
    )

    result = m.handler(_event(item_count=5, object_count=5), None)

    assert result["transferOutcome"]["complete"] is False
    assert result["transferOutcome"]["copied"] == 3
    assert result["transferOutcome"]["occupied"] == 2


def test_a_mix_of_causes_counts_only_the_occupied_ones_as_occupied():
    """``{occupied}`` is at most ``{total} - {restored}`` and can be less, which is exactly why
    the body that names it says "of the rest" rather than accounting for the difference.

    Three of the six objects are folder placeholders. One copied, and two fell short — one a
    failed copy, one in a batch that never completed, whose flag the collector reads back off the
    batch's own input. So the counts a person is shown are the three files, one of which landed,
    plus the two placeholders that did not: 1 of 5. With the second half's flag lost, the
    verdict would fall back to the object counts and read 2 of 6."""
    placeholder_line = {"srcKey": "alice/empty/", "folder": True}
    _install(
        _export(
            succeeded=[
                _succeeded_record(2, failures=1, reason="destination_occupied_during_copy"),
                _succeeded_record(0, failures=2, reason="copy_failed", folders=1),
            ],
            failed=[{"Input": json.dumps({"Items": [placeholder_line]}), "Error": "States.Timeout"}],
        )
    )

    result = m.handler(_event(item_count=6, object_count=6, file_count=3), None)

    assert result["transferOutcome"]["failed"] == 4
    assert result["transferOutcome"]["occupied"] == 1
    assert result["transferOutcome"]["shown"] == {"copied": 1, "total": 5, "occupied": 1}


@pytest.mark.parametrize(
    "covered,shown",
    [(1, {"copied": 0, "total": 1, "occupied": 0}), (3, {"copied": 1, "total": 1, "occupied": 0})],
    ids=["an-export-short-of-the-manifest", "an-export-over-the-manifest"],
)
def test_an_export_that_miscounts_the_manifest_names_no_impossible_pair(covered, shown):
    """Both are wiring faults with no failure record to say which kind went missing, and both are
    incomplete. One file and one placeholder were planned. An item the export never covered is
    attributed to the file first, so the sentence reads 0 of 1 rather than "1 of 1"; an export
    covering more than was planned counts no shortfall at all, so it reads 1 of 1 rather than
    the "2 of 1" a negative shortfall would make."""
    _install(_export(succeeded=[_succeeded_record(covered)]))

    result = m.handler(_event(item_count=2, object_count=2, file_count=1), None)

    assert result["transferOutcome"]["complete"] is False
    assert result["transferOutcome"]["shown"] == shown


def test_the_archive_arm_reports_zero_occupied_rather_than_omitting_the_field():
    """A field present on one arm and absent on the other is a shape every reader has to branch
    on. The archive's manifest asks for no condition, so the count is zero by construction —
    which is a different statement from the key not being there."""
    _install(_export(succeeded=[_succeeded_record(8)]))

    result = m.handler(_event(), None)

    assert result["transferOutcome"]["occupied"] == 0
