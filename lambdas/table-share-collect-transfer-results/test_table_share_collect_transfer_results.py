"""Unit tests for the collect-transfer-results Lambda (SPEC-160 FR-004).

Attribution is where per-recipient isolation lives now that the fan-out is over
(recipient x object) pairs, so these tests are about who ends up with a table: a recipient with
one failed item does not, a recipient the guard already refused keeps its own reason, and an
export that cannot be attributed fails the whole request rather than reporting success.
Runnable under pytest or directly: python3 test_table_share_collect_transfer_results.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_collect_transfer_results as m
from cpcommon import clients
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
    m.notify.emit_notification = lambda user, message: sent.append((user, message))
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


def test_the_failed_item_count_is_reported_and_the_keys_are_not():
    """FR-004 AC6 — counts and names, never a list of failed keys."""
    _setup(_export(failures=[{"recipient": "carol", "kind": "user", "reason": "copy_failed"}] * 3))

    out = m.handler(_event([{"status": "ok", "recipient": _resolved("carol")}]), None)

    entry = out["outcomes"][0]
    assert entry["failedItems"] == 3
    assert "parquet" not in json.dumps(out["outcomes"])


def test_a_whole_batch_failure_is_attributed_to_its_recipients():
    _setup(_export(failed_batches=["bob"]))

    out = m.handler(
        _event([{"status": "ok", "recipient": _resolved("bob")}, {"status": "ok", "recipient": _resolved("carol")}]),
        None,
    )

    by_name = {e["name"]: e["status"] for e in out["outcomes"]}
    assert by_name == {"bob": "failed", "carol": "ok"}


def test_a_guard_refusal_keeps_its_own_reason():
    """FR-004 AC5 — attribution never overwrites an earlier terminal."""
    _setup(_export())
    refused = {
        "status": "failed",
        "recipient": {"kind": "user", "name": "carol"},
        "error": {"Error": "TerminalError", "Cause": json.dumps({
            "errorType": "TerminalError", "errorMessage": "conflict: a table named x exists"
        })},
    }

    out = m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}, refused]), None)

    by_name = {e["name"]: e for e in out["outcomes"]}
    assert by_name["carol"]["status"] == "failed"
    assert by_name["carol"]["reason"] == "conflict"
    assert by_name["carol"]["recipient"] is None


def test_a_refused_recipient_is_not_resurrected_by_a_clean_run():
    """It contributed no items, so it has no failed ones — which must not read as success."""
    _setup(_export())
    out = m.handler(
        _event([{"status": "failed", "recipient": {"kind": "space", "name": "team"}, "error": {}}], item_count=0),
        None,
    )
    assert [(e["name"], e["status"]) for e in out["outcomes"]] == [("team", "failed")]


def test_the_sender_is_told_about_a_copy_failure():
    """The notification a batch verb cannot send: the copy failure only has a recipient here."""
    sent = _setup(_export(failures=[{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]))

    m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}, {"status": "ok", "recipient": _resolved("carol")}]), None)

    assert len(sent) == 1
    user, message = sent[0]
    assert user == "alice"
    assert 'user "carol"' in message and "copying the data failed" in message
    assert "bob" not in message


def test_a_guard_refusal_is_not_notified_twice():
    """check-target-absent's own decorator already told the sender."""
    sent = _setup(_export())
    m.handler(_event([{"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "error": {}}]), None)
    assert sent == []


def test_an_empty_transfer_reads_no_export():
    """The every-recipient-conflicted path: no Map ran, so there is no run to read."""
    _setup({})
    out = m.handler(
        _event([{"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "error": {}}], item_count=0),
        None,
    )
    assert out["outcomes"][0]["status"] == "failed"


def test_a_missing_results_pointer_fails_the_whole_request():
    _setup(_export())
    event = _event([{"status": "ok", "recipient": _resolved("bob")}])
    event["mapRun"] = {"MapRunArn": "arn"}

    with pytest.raises(TerminalError) as caught:
        m.handler(event, None)
    assert caught.value.reason == "transfer_results_unreadable"


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


def test_a_user_and_a_space_of_the_same_name_are_attributed_separately():
    """A destination is a (kind, name) PAIR, and nothing stops a space being named after a user.

    Keyed on the name alone, one failed object in space "acme" would deny user "acme" a table they
    actually received — and hand them a failure notification for it.
    """
    _setup(_export(failures=[{"recipient": "acme", "kind": "space", "reason": "copy_failed"}]))

    out = m.handler(
        _event([
            {"status": "ok", "recipient": _resolved("acme", kind="user")},
            {"status": "ok", "recipient": _resolved("acme", kind="space")},
        ]),
        None,
    )

    by_kind = {e["kind"]: e["status"] for e in out["outcomes"]}
    assert by_kind == {"user": "ok", "space": "failed"}


def test_an_unreadable_export_fails_the_whole_request():
    """FR-004 AC7 — never a silent 'everything succeeded'."""
    _setup({})
    with pytest.raises(TerminalError) as caught:
        m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}]), None)
    assert caught.value.reason == "transfer_results_unreadable"


def test_an_omitted_payload_fails_the_whole_request():
    """FR-004 AC3 — unattributable is not 'no failures found'."""
    export = _export()
    export["r/SUCCEEDED_0.json"][0]["OutputDetails"] = {"Included": False}
    _setup(export)

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}]), None)
    assert caught.value.reason == "transfer_results_unreadable"


def test_every_entry_carries_every_key_the_pass_through_reads():
    """The finish Map echoes a non-ok entry field by field, and an ABSENT path in a Pass raises
    an uncatchable States.Runtime — so the shape has to be uniform, not merely correct."""
    _setup(_export(failures=[{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]))

    out = m.handler(
        _event([
            {"status": "ok", "recipient": _resolved("bob")},
            {"status": "ok", "recipient": _resolved("carol")},
            {"status": "failed", "recipient": {"kind": "space", "name": "team"}, "error": {"Error": "X"}},
        ]),
        None,
    )

    for entry in out["outcomes"]:
        assert set(entry) == {"kind", "name", "status", "reason", "failedItems", "recipient"}


def test_the_raw_error_is_decoded_here_and_not_carried_forward():
    """A payload decision, not tidying (SPEC-160 review).

    A raw {Error, Cause} runs to hundreds of bytes with its stack. Carried onward it would sit on
    the state three times over — guardResults, outcomes, and the finish Map's results — and 50
    conflicting recipients measured over the 256 KB limit, where the breach lands ON a Map and
    destroys every per-recipient outcome. The reason code is what a reader needs; the raw object
    stays in the execution history at the state that produced it.
    """
    _setup(_export())
    refused = {
        "status": "failed",
        "recipient": {"kind": "user", "name": "carol"},
        "error": {"Error": "TerminalError", "Cause": "x" * 4000},
    }

    out = m.handler(_event([refused], item_count=0), None)

    assert "guardResults" not in out, "the guard results were consumed; carrying them triples the Causes"
    assert "x" * 100 not in json.dumps(out)
    assert out["outcomes"][0]["reason"] == "TerminalError"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
