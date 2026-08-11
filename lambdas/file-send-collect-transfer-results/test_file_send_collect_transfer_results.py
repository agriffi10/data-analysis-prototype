"""Unit tests for the file-send collect-transfer-results Lambda (SPEC-166 FR-003).

Attribution is where per-recipient isolation lives now that the fan-out is over
(recipient x object) pairs, so these tests are about who is told what: a recipient with one
failed item did not receive the send, a recipient the guard already refused keeps its own
reason, and an export that cannot be attributed fails the whole request rather than reporting
success. Runnable under pytest or directly:
python3 test_file_send_collect_transfer_results.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_collect_transfer_results as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError

_MANIFEST_KEY = "file-send/req-1/results/run/manifest.json"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


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


def _setup(objects=None):
    clients._s3 = _FakeS3(objects or {})
    sent = []
    m.notify.emit_notification = lambda user, message, **kw: sent.append((user, message))
    return sent


def _cleared(kind, name):
    return {
        "status": "ok",
        "recipient": {"kind": kind, "name": name, "destBucket": "user-bkt", "destRoot": f"{name}/"},
        "reason": "",
        "detail": "",
    }


def _refused(kind, name, reason, detail=""):
    return {
        "status": "failed",
        "recipient": {"kind": kind, "name": name},
        "reason": reason,
        "detail": detail,
    }


def _event(guard_results, item_count=2, map_run=True):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "items": []},
        "objectCount": 2,
        "guardResults": guard_results,
        "transfer": {
            "manifestBucket": "admin-bkt",
            "manifestKey": "file-send/req-1/transfer-manifest.jsonl",
            "resultsBucket": "admin-bkt",
            "resultsPrefix": "file-send/req-1/results",
            "itemCount": item_count,
        },
    }
    if map_run:
        event["mapRun"] = {"ResultWriterDetails": {"Bucket": "admin-bkt", "Key": _MANIFEST_KEY}}
    return event


def _succeeded(copied, failures=()):
    return [{"Output": json.dumps({"copied": copied, "failures": list(failures)})}]


def _export(records, group="SUCCEEDED"):
    return {
        _MANIFEST_KEY: {"ResultFiles": {group: [{"Key": f"file-send/req-1/results/{group}_0.json"}]}},
        f"file-send/req-1/results/{group}_0.json": records,
    }


def test_a_clean_transfer_leaves_every_recipient_ok():
    _setup(_export(_succeeded(2)))

    outcomes = m.handler(_event([_cleared("user", "bob")]), None)["outcomes"]

    assert outcomes == [
        {"kind": "user", "name": "bob", "status": "ok", "reason": "", "detail": "", "failedItems": 0}
    ]


def test_one_failed_item_fails_that_recipient_and_only_that_recipient():
    """FR-003 AC1. A recipient is ``ok`` only when NONE of its items failed: a folder silently
    short of a file is the outcome this plane must never report as a success."""
    _setup(_export(_succeeded(3, [{"recipient": "bob", "kind": "user", "reason": "copy_failed"}])))

    outcomes = m.handler(
        _event([_cleared("user", "bob"), _cleared("user", "carol")], item_count=4), None
    )["outcomes"]

    assert [(o["name"], o["status"], o["failedItems"]) for o in outcomes] == [
        ("bob", "failed", 1),
        ("carol", "ok", 0),
    ]


def test_a_failure_reported_by_a_SUCCEEDED_batch_is_still_a_failure():
    """The thing about this export that surprises: Step Functions files a child by its EXECUTION
    STATUS, and the batch copier deliberately succeeds while carrying per-item failures. A
    collector reading only FAILED_n.json reports universal success over an incomplete send."""
    _setup(_export(_succeeded(1, [{"recipient": "bob", "kind": "user", "reason": "copy_failed"}])))

    outcomes = m.handler(_event([_cleared("user", "bob")]), None)["outcomes"]

    assert outcomes[0]["status"] == "failed" and outcomes[0]["reason"] == "copy_failed"


def test_a_whole_batch_failure_is_attributed_from_its_input():
    """The other half: a child that died reported nothing per item, so every item it carried
    fails — including any it had already copied, because which of them landed is unknown."""
    _setup(
        _export(
            [
                {
                    "Input": json.dumps(
                        {"Items": [{"recipient": "bob", "kind": "user"}, {"recipient": "bob", "kind": "user"}]}
                    )
                }
            ],
            group="FAILED",
        )
    )

    outcomes = m.handler(_event([_cleared("user", "bob")]), None)["outcomes"]

    assert outcomes[0]["failedItems"] == 2


def test_attribution_never_overwrites_an_earlier_terminal():
    """FR-003 AC3. A refused recipient had no items in the manifest, so no item of its own
    failed — and reading that as success would resurrect a recipient the guard refused."""
    _setup(_export(_succeeded(2)))

    outcomes = m.handler(_event([_refused("user", "carol", "conflict", "notes.txt")]), None)["outcomes"]

    assert outcomes == [
        {
            "kind": "user",
            "name": "carol",
            "status": "failed",
            "reason": "conflict",
            "detail": "notes.txt",
            "failedItems": 0,
        }
    ]


def test_a_faulted_guard_item_has_its_raw_error_decoded_here():
    """The guard returns its EXPECTED refusals as data; its Map item's Catch produces the other
    shape for a fault nobody predicted, carrying the raw {Error, Cause}. Only
    cpcommon.errors.failure_reason may decode it — never ASL, where States.StringToJson raises an
    uncatchable States.Runtime on a Cause that is absent or not JSON."""
    _setup(_export(_succeeded(2)))
    faulted = {
        "status": "failed",
        "recipient": {"kind": "user", "name": "dave"},
        "error": {"Error": "Lambda.Unknown", "Cause": "not json at all"},
    }

    outcomes = m.handler(_event([faulted]), None)["outcomes"]

    assert outcomes[0]["reason"] == "Lambda.Unknown"
    assert "Cause" not in json.dumps(outcomes[0])


def test_a_recipient_and_a_space_of_the_same_name_are_attributed_separately():
    """A destination is the (kind, name) PAIR: nothing stops a shared space being named after a
    user, and counting on the name alone would deny one of them a copy the other lost."""
    _setup(_export(_succeeded(3, [{"recipient": "finance", "kind": "space", "reason": "copy_failed"}])))

    outcomes = m.handler(
        _event([_cleared("user", "finance"), _cleared("space", "finance")], item_count=4), None
    )["outcomes"]

    assert [(o["kind"], o["status"]) for o in outcomes] == [("user", "ok"), ("space", "failed")]


def test_an_export_short_of_the_manifests_items_fails_the_whole_request():
    """FR-003 AC5. An export can be well-formed and still cover only some of the batches, and a
    partial export read as a clean run tells every recipient the send went well without having
    checked."""
    _setup(_export(_succeeded(1)))

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([_cleared("user", "bob")], item_count=2), None)

    assert caught.value.reason == "transfer_results_unreadable"


def test_an_unattributable_record_fails_the_whole_request():
    """FR-003 AC2. A payload Step Functions omitted names nobody, so "no failures found" is not
    an answer anyone may act on."""
    _setup(_export([{"OutputDetails": {"Included": False}}]))

    with pytest.raises(TerminalError):
        m.handler(_event([_cleared("user", "bob")]), None)


def test_a_missing_export_pointer_fails_the_whole_request():
    _setup({})

    with pytest.raises(TerminalError):
        m.handler(_event([_cleared("user", "bob")], map_run=False), None)


def test_an_absent_results_manifest_fails_the_whole_request():
    """FR-003 AC5 again, from the other direction: absent rather than short. The Map Run has
    finished by the time this runs, so its export is not still being written."""
    _setup({})

    with pytest.raises(TerminalError):
        m.handler(_event([_cleared("user", "bob")]), None)


def test_a_request_where_every_recipient_conflicted_reaches_the_terminal_with_no_map_run():
    """FR-003 AC6. The Choice skipped the Map, so there is no export to read — and one shaping
    verb runs on both branches rather than two paths that can disagree."""
    _setup({})

    outcomes = m.handler(
        _event([_refused("user", "bob", "conflict", "notes.txt")], item_count=0, map_run=False), None
    )["outcomes"]

    assert [o["status"] for o in outcomes] == ["failed"]


@pytest.mark.parametrize("transfer", [None, {}, {"itemCount": 0}, {"itemCount": "2"}])
def test_an_accepted_recipient_with_no_reported_transfer_fails_the_whole_request(transfer):
    """The silent-universal-success hole, closed by the one invariant the event already carries.

    A missing or zero ``transfer`` block is indistinguishable from "the Choice legitimately
    skipped the Map" — except that the manifest builder CANNOT report zero items while a
    recipient cleared the guard: it writes a line per (accepted recipient x planned object) and
    the plan reader refuses an empty object list. So an accepted recipient with no transfer is a
    wiring fault, and reading it as "no failures" would tell that recipient's sender the send
    went well without a single S3 call having been made — which is what an unguarded version
    does, with no S3 fake installed at all."""
    _setup({})
    event = _event([_cleared("user", "bob")], map_run=False)
    if transfer is None:
        del event["transfer"]
    else:
        event["transfer"] = transfer

    with pytest.raises(TerminalError) as caught:
        m.handler(event, None)

    assert caught.value.reason == "transfer_results_unreadable"


def test_a_skipped_map_is_still_believable_when_nobody_was_accepted():
    """The other half of the same rule, so the guard above cannot be satisfied by refusing
    everything: the ordinary "everybody was already holding it" send reads no export and
    reports every refusal."""
    _setup({})

    outcomes = m.handler(
        _event([_refused("user", "bob", "conflict", "notes.txt")], item_count=0, map_run=False), None
    )["outcomes"]

    assert [o["reason"] for o in outcomes] == ["conflict"]


def test_the_outcomes_carry_counts_and_never_keys():
    """FR-003 AC4. This list rides the state through the terminal Pass states, and a failed-key
    list is the unbounded term that breaches the 256 KB payload limit — where the error lands ON
    the Map and destroys every per-recipient outcome it exists to preserve."""
    _setup(_export(_succeeded(1, [{"recipient": "bob", "kind": "user", "reason": "copy_failed"}])))

    outcomes = m.handler(_event([_cleared("user", "bob")]), None)["outcomes"]

    assert set(outcomes[0]) == {"kind", "name", "status", "reason", "detail", "failedItems"}
    assert "alice/" not in json.dumps(outcomes)


def test_every_recipient_appears_exactly_once():
    """FR-003 AC4. The summary reports every recipient once — a recipient missing from it is a
    person the sender is never told about."""
    _setup(_export(_succeeded(2)))
    guard = [_cleared("user", "bob"), _refused("user", "carol", "conflict"), _refused("user", "ghost", "unknown_user")]

    outcomes = m.handler(_event(guard), None)["outcomes"]

    assert [o["name"] for o in outcomes] == ["bob", "carol", "ghost"]


def test_the_guard_results_are_consumed_rather_than_carried():
    """They are this verb's input and the state's heaviest per-recipient term; every fact the
    summary needs has been copied into the outcomes by the time they are dropped."""
    _setup(_export(_succeeded(2)))

    result = m.handler(_event([_cleared("user", "bob")]), None)

    assert "guardResults" not in result
    assert result["requestId"] == "req-1"


def test_this_verb_notifies_nobody_about_a_recipient():
    """Per-recipient outcomes are told to the sender once, from the terminal summary (SPEC-167).
    Table-share notifies copy failures from HERE because it has no such producer; doing the same
    would make every copy failure two messages."""
    sent = _setup(_export(_succeeded(1, [{"recipient": "bob", "kind": "user", "reason": "copy_failed"}])))

    m.handler(_event([_cleared("user", "bob")]), None)

    assert sent == []


def test_a_whole_request_failure_still_notifies_the_sender():
    """The other side of the same rule: this IS a whole-request verb, and the machine's
    notify-failure state suppresses a terminal error precisely because it assumes the
    decorator already spoke."""
    sent = _setup({})

    with pytest.raises(TerminalError):
        m.handler(_event([_cleared("user", "bob")]), None)

    assert sent and sent[0][0] == "alice"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
