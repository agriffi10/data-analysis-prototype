"""Unit tests for the notifications writer.

Runs under pytest or as a plain script (`python3 test_notifications_writer.py`); the
JS CI does not run Python. The S3 client and token verification are faked — the client on
`cpcommon.clients` since SPEC-156 FR-004, which is also where `lambdas/conftest.py`'s
shared-layer snapshot restores it from.
"""

import json
import types

import notifications_writer as w
from cpcommon import clients, observability


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
    clients._s3 = s3
    w.USER_SPACE_BUCKET = "user-bucket"
    w.NOTIFICATIONS_MAX = 200
    # Fake token verification: idToken == username.
    w.verified_username = lambda token: token or _auth_fail()
    w.UNTRUSTED_SENDER_ID = "AROAPORTAL"
    _ERRORS.clear()
    observability.error = lambda message, **fields: _ERRORS.append((message, fields))
    return s3


def _auth_fail():
    raise w.AuthorizationError("missing idToken")


def _inbox(s3, username):
    raw = s3.store.get(("user-bucket", f"{username}/user_settings/notifications.json"))
    return json.loads(raw) if raw else None


# The two senders every test names explicitly. A create legitimately comes from an execution
# role; a user action legitimately comes from the browser, which is the role the create guard
# refuses — so the user-action tests below are also the proof that the guard did not catch them.
SERVICE_SENDER = "AROASERVICE:producer"
PORTAL_SENDER = "AROAPORTAL:CognitoIdentityCredentials"

#: Events captured from observability.error. Module-level rather than a fixture because the
#: __main__ runner below calls each test with no arguments, so a fixture parameter would be a
#: TypeError there. _setup clears it per test; under pytest, lambdas/conftest.py's shared-layer
#: snapshot restores the patched module afterwards.
_ERRORS = []


def _msg(body, sender):
    """Builds a one-record SQS event.

    ``sender`` is REQUIRED and has no default on purpose. What is under test is that a create
    is judged by the identity SQS stamped, so a default would be the thing under test wearing
    the costume of a convenience — and it would apply itself silently to every call site added
    later. Required means Python refuses the call site that forgets.
    """
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(body),
                "attributes": {"SenderId": sender},
            }
        ]
    }


def test_create_into_empty_inbox():
    s3 = _setup()
    w.handler(_msg({"action": "create", "username": "alice", "message": "hi"}, SERVICE_SENDER), None)
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
    w.handler(_msg({"action": "create", "username": "alice", "message": "new"}, SERVICE_SENDER), None)
    inbox = _inbox(s3, "alice")
    assert inbox[0]["message"] == "new" and inbox[1]["id"] == "old"


def test_an_OVERSIZE_payload_is_refused_rather_than_truncated():
    # THE ONLY SERVER-SIDE GATE THIS FIELD WILL EVER HAVE. A producer's own bound lives in its
    # own layer and constrains nothing that arrives here: the grant on this queue is
    # unconditioned, and while the sender check now bounds WHICH principals reach the writer,
    # IAM still bounds nothing about the message itself. Refusing dead-letters the one message;
    # truncating would write a half-object into an inbox every poll downloads whole.
    s3 = _setup()
    oversize = {"requestId": "r-1", "conflicts": ["k" * (w.MAX_PAYLOAD_BYTES + 1)]}

    _raises(
        lambda: w.handler(
            _msg({"action": "create", "username": "alice", "message": "big", "payload": oversize}, SERVICE_SENDER),
            None,
        ),
        w.ValidationError,
        "over the",
    )
    assert _inbox(s3, "alice") is None, "the inbox was written despite the refusal"


def test_cap_keeps_newest():
    w_max = 5
    existing = [
        {"id": f"n{i}", "message": str(i), "read": True, "timestamp": f"2026-01-{i:02d}T00:00:00.000Z"}
        for i in range(1, 11)
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): existing})
    w.NOTIFICATIONS_MAX = w_max
    w.handler(_msg({"action": "create", "username": "alice", "message": "newest"}, SERVICE_SENDER), None)
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
    result = w.handler(_msg({"action": "markRead", "id": "a", "idToken": "alice"}, PORTAL_SENDER), None)
    by_id = {n["id"]: n for n in _inbox(s3, "alice")}
    assert by_id["a"]["read"] is True and by_id["b"]["read"] is False
    assert result["matched"] == 1


def test_mark_all_read():
    inbox = [
        {"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"},
        {"id": "b", "message": "b", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"},
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markAllRead", "idToken": "alice"}, PORTAL_SENDER), None)
    assert all(n["read"] for n in _inbox(s3, "alice"))


def test_user_action_without_token_rejected():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "markAllRead"}, PORTAL_SENDER), None),
        w.AuthorizationError,
        "idToken",
    )


# ── SPEC-153 FR-005: the batch-size coupling is pinned on both sides ──────────


# ── SPEC-153 FR-010: what a redelivery does is stated, not assumed ────────────


# ── The create boundary: who may write to another user's inbox ───────────────


def _refusals():
    """The reason codes captured from observability.error this test."""
    return [fields.get("reason") for message, fields in _ERRORS if message == "create refused"]


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
