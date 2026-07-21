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
    w.verified_username = lambda token: token if token else _auth_fail()
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
    w.handler(_msg({"action": "markRead", "id": "a", "idToken": "alice"}), None)
    by_id = {n["id"]: n for n in _inbox(s3, "alice")}
    assert by_id["a"]["read"] is True and by_id["b"]["read"] is False


def test_mark_read_absent_id_is_noop():
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markRead", "id": "missing", "idToken": "alice"}), None)
    assert _inbox(s3, "alice")[0]["read"] is False


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
