"""Unit tests for the notifications writer.

Runs under pytest or as a plain script (`python3 test_notifications_writer.py`); the
JS CI does not run Python. The S3 client and token verification are faked.
"""

import json
import types

import notifications_writer as w


def _raises(fn, exc_type, match=None):
    try:
        fn()
    except exc_type as exc:
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}, none raised")


class FakeNoSuchKey(Exception):
    pass


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d


class FakeS3:
    def __init__(self):
        self.store = {}
        self.exceptions = types.SimpleNamespace(NoSuchKey=FakeNoSuchKey)

    def get_object(self, Bucket, Key):
        if (Bucket, Key) in self.store:
            return {"Body": _Body(self.store[(Bucket, Key)])}
        raise FakeNoSuchKey()

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else Body.encode()
        return {}


def _setup(monkey_store=None):
    s3 = FakeS3()
    if monkey_store:
        for (bucket, key), value in monkey_store.items():
            s3.store[(bucket, key)] = json.dumps(value).encode()
    w._s3 = s3
    w.USER_SPACE_BUCKET = "user-bucket"
    w.NOTIFICATIONS_MAX = 200
    # Fake token verification: idToken == username.
    w.verified_username = lambda token: token or _auth_fail()
    return s3


def _auth_fail():
    raise w.AuthorizationError("missing idToken")


def _inbox(s3, username):
    raw = s3.store.get(("user-bucket", f"{username}/user_settings/notifications.json"))
    return json.loads(raw) if raw else None


def _msg(body):
    return {"Records": [{"body": json.dumps(body)}]}


def test_create_into_empty_inbox():
    s3 = _setup()
    w.handler(_msg({"action": "create", "username": "alice", "message": "hi"}), None)
    inbox = _inbox(s3, "alice")
    assert len(inbox) == 1
    note = inbox[0]
    assert note["message"] == "hi" and note["read"] is False
    assert note["id"] and note["timestamp"]


def test_create_prepends_newest_first():
    s3 = _setup(
        {("user-bucket", "alice/user_settings/notifications.json"): [
            {"id": "old", "message": "old", "read": True, "timestamp": "2026-01-01T00:00:00.000Z"}
        ]}
    )
    w.handler(_msg({"action": "create", "username": "alice", "message": "new"}), None)
    inbox = _inbox(s3, "alice")
    assert inbox[0]["message"] == "new" and inbox[1]["id"] == "old"


def test_create_uses_body_username_not_token():
    s3 = _setup()
    # create carries no idToken; the body username is authoritative for trusted producers.
    w.handler(_msg({"action": "create", "username": "bob", "message": "x"}), None)
    assert _inbox(s3, "bob") is not None
    assert _inbox(s3, "alice") is None


def test_create_persists_a_supplied_link():
    # SPEC-113 FR-008: the record gains ONE optional field so a notification can deep-link
    # to the report it is about.
    s3 = _setup()
    w.handler(
        _msg({
            "action": "create",
            "username": "alice",
            "message": "Data quality check finished",
            "link": "/data-quality/alice/req-1",
        }),
        None,
    )
    assert _inbox(s3, "alice")[0]["link"] == "/data-quality/alice/req-1"


def test_create_without_a_link_writes_no_link_key():
    # The existing producers (table-builder, table-share, the shared-space verbs) supply
    # no link and must keep writing byte-identical records. An empty or non-string value
    # is treated the same as absent rather than written as a falsy link the browser would
    # have to defend against.
    s3 = _setup()
    for body in (
        {"action": "create", "username": "alice", "message": "no link"},
        {"action": "create", "username": "alice", "message": "empty", "link": ""},
        {"action": "create", "username": "alice", "message": "wrong type", "link": 42},
    ):
        w.handler(_msg(body), None)
    for note in _inbox(s3, "alice"):
        assert "link" not in note


def test_create_requires_message():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "create", "username": "alice"}), None),
        w.ValidationError,
        "message",
    )


def test_corrupt_doc_treated_as_empty():
    s3 = _setup()
    s3.store[("user-bucket", "alice/user_settings/notifications.json")] = b"{not json"
    w.handler(_msg({"action": "create", "username": "alice", "message": "hi"}), None)
    assert len(_inbox(s3, "alice")) == 1


def test_cap_keeps_newest():
    w_max = 5
    existing = [
        {"id": f"n{i}", "message": str(i), "read": True, "timestamp": f"2026-01-{i:02d}T00:00:00.000Z"}
        for i in range(1, 11)
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): existing})
    w.NOTIFICATIONS_MAX = w_max
    w.handler(_msg({"action": "create", "username": "alice", "message": "newest"}), None)
    inbox = _inbox(s3, "alice")
    assert len(inbox) == w_max
    assert inbox[0]["message"] == "newest"
    # Oldest (2026-01-01..) dropped; the most recent timestamps survive.
    assert all(n["message"] != "1" for n in inbox)


def test_mark_read_flips_matching_id():
    inbox = [
        {"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"},
        {"id": "b", "message": "b", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"},
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    result = w.handler(_msg({"action": "markRead", "id": "a", "idToken": "alice"}), None)
    by_id = {n["id"]: n for n in _inbox(s3, "alice")}
    assert by_id["a"]["read"] is True and by_id["b"]["read"] is False
    assert result["matched"] == 1


def test_mark_read_absent_id_is_noop():
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markRead", "id": "missing", "idToken": "alice"}), None)
    assert _inbox(s3, "alice")[0]["read"] is False


def test_a_markread_that_changed_nothing_is_distinguishable_from_one_that_worked():
    """The silent no-op is the exact signature of "mark as read did nothing", and it
    still writes the inbox and reports a count — so without `matched` the two outcomes
    are identical in the logs and the bug cannot be diagnosed from a live run."""
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    assert w.handler(_msg({"action": "markRead", "id": "missing", "idToken": "alice"}), None)["matched"] == 0


def test_matched_is_absent_for_actions_that_cannot_miss():
    """create/markAllRead have no id to miss, so they carry no `matched` field at all."""
    _setup({("user-bucket", "alice/user_settings/notifications.json"): []})
    assert "matched" not in w.handler(_msg({"action": "markAllRead", "idToken": "alice"}), None)
    assert "matched" not in w.handler(_msg({"action": "create", "username": "alice", "message": "m"}), None)


def test_mark_all_read():
    inbox = [
        {"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"},
        {"id": "b", "message": "b", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"},
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markAllRead", "idToken": "alice"}), None)
    assert all(n["read"] for n in _inbox(s3, "alice"))


def test_user_action_ignores_body_username():
    # markRead carries a forged username; the token (verified -> "alice") wins.
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markRead", "id": "a", "username": "victim", "idToken": "alice"}), None)
    assert _inbox(s3, "alice")[0]["read"] is True
    assert _inbox(s3, "victim") is None


def test_user_action_without_token_rejected():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "markAllRead"}), None),
        w.AuthorizationError,
        "idToken",
    )


def test_unknown_action_rejected():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "delete", "username": "alice"}), None),
        w.ValidationError,
        "unknown action",
    )


def test_non_json_body_rejected():
    _setup()
    _raises(
        lambda: w.handler({"Records": [{"body": "{not json"}]}, None),
        w.ValidationError,
        "valid JSON",
    )


def test_empty_event_rejected():
    _setup()
    _raises(lambda: w.handler({"Records": []}, None), w.ValidationError, "no SQS records")


# ── SPEC-153 FR-005: the batch-size coupling is pinned on both sides ──────────


def test_a_multi_record_event_raises_instead_of_dropping_records():
    """The handler's single-record assumption is now enforced, not assumed.

    It used to take ``records[0]`` and discard the rest, which is correct ONLY because the
    Terraform below sets ``batch_size = 1``. Nothing connected the two halves — ``grep -rn
    batch_size lambdas/`` returned zero hits — so a one-line infra edit would have silently
    dropped every notification but the first, in the channel that IS the completion channel
    for four asynchronous control planes (SPEC-114).

    Failing loudly is not a delivery guarantee and must not be read as one: this queue's DLQ
    is the ONE that SPEC-126 deliberately leaves undrained (circular — the drain delivers
    through this same queue), so the batch waits there for an operator rather than becoming a
    notification. What the raise buys is that a `batch_size` edit shows up as invocation
    errors and a filling DLQ instead of as notifications that quietly never arrive.
    """
    s3 = _setup()
    body = json.dumps({"action": "create", "username": "alice", "message": "hi"})

    _raises(
        lambda: w.handler({"Records": [{"body": body}, {"body": body}]}, None),
        w.ValidationError,
        "batch_size = 1",
    )

    assert _inbox(s3, "alice") is None  # nothing partially written


def test_the_notifications_event_source_mapping_still_sets_batch_size_one():
    """The infra half of the coupling above.

    The handler is written for exactly one record per invocation. If this value ever moves,
    the handler now raises rather than dropping — but the intended fix is to keep it at 1
    and change the handler deliberately, so this test fails first and says why.

    SCOPE: this is the only ``aws_lambda_event_source_mapping`` in the repo. The four
    ``batch_size = 1`` values under ``infra/modules/*/pipe.tf`` are EventBridge Pipes whose
    target is a state machine, not a Lambda handler — no handler assumes a single record
    there — and they are asserted separately below so a batching Pipe cannot appear unnoticed.
    """
    import os
    import re

    infra = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", "modules"
    )
    with open(os.path.join(infra, "notifications", "lambda.tf")) as handle:
        tf = handle.read()
    assert re.search(r"^\s*batch_size\s*=\s*1\s*$", tf, re.MULTILINE), (
        "notifications/lambda.tf must keep batch_size = 1 — notifications_writer.handler "
        "processes exactly one record per invocation"
    )


def test_no_other_event_source_mapping_batches():
    """Guards the scope comment above rather than trusting it.

    Counts the event-source mappings and Pipe batch sizes across every module, and requires
    every one of them to be 1. A new mapping — or a Pipe raised to a batch — fails here and
    has to state which handler it belongs to.
    """
    import glob
    import os
    import re

    infra = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", "modules"
    )
    sizes = []
    mappings = 0
    # Both depths: modules/<name>/*.tf AND infra/*.tf. A mapping added at the root would
    # otherwise be invisible to the test whose whole job is guarding a scope claim.
    roots = glob.glob(os.path.join(infra, "*", "*.tf")) + glob.glob(
        os.path.join(infra, "..", "*.tf")
    )
    for path in sorted(roots):
        with open(path) as handle:
            text = handle.read()
        mappings += len(re.findall(r'resource\s+"aws_lambda_event_source_mapping"', text))
        sizes += [(os.path.basename(os.path.dirname(path)), v)
                  for v in re.findall(r"^\s*batch_size\s*=\s*(\d+)\s*$", text, re.MULTILINE)]

    assert mappings == 1, f"a new Lambda event-source mapping appeared ({mappings} found)"
    assert len(sizes) >= 5, f"the batch_size sweep found only {sizes} — did the shape change?"
    assert all(v == "1" for _, v in sizes), f"a batching source appeared: {sizes}"


# ── SPEC-153 FR-010: what a redelivery does is stated, not assumed ────────────


def test_ACCEPTED_a_redelivered_create_writes_a_SECOND_inbox_entry():
    """Today's behaviour, accepted by decision — not an oversight, and not a bug report.

    These pipelines are at-least-once. ``apply_create`` mints ``uuid.uuid4().hex`` per
    invocation, so the same SQS message delivered twice (a visibility-timeout redelivery,
    which FIFO's 5-minute producer-side ``MessageDeduplicationId`` window does not bound)
    lands as two inbox rows for one event. ``dqcommon.index_store`` handles the equivalent
    case by replacing the row and has a test saying so; the user-facing inbox does not.

    ACCEPTED because the blast radius is one duplicated line in a read-only list — no
    access is granted, nothing is overwritten, and the user can dismiss it — while the fix
    with real teeth is a producer-supplied idempotency key, a contract change across four
    control planes and the browser producer. Recorded in decisions.md.

    If this starts failing, the writer became idempotent: revisit the decision and the
    delivery-doc note, do not delete the test.
    """
    s3 = _setup()
    record = {"body": json.dumps({"action": "create", "username": "alice", "message": "hi"})}

    w.handler({"Records": [record]}, None)
    w.handler({"Records": [record]}, None)  # same message, redelivered

    inbox = _inbox(s3, "alice")
    assert len(inbox) == 2
    assert inbox[0]["message"] == inbox[1]["message"] == "hi"
    assert inbox[0]["id"] != inbox[1]["id"]


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"ok   {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
