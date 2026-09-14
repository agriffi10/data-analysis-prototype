"""Unit tests for the notifications writer.

The S3 client is faked, on `cpcommon.clients`, which is also where `lambdas/conftest.py`'s
shared-layer snapshot restores it from. Nothing verifies a token any more, so there is no
verifier to fake: a user action carries the identity block `_identity` builds.
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
    w.UNTRUSTED_SENDER_ID = "AROAPORTAL"
    _ERRORS.clear()
    observability.error = lambda message, **fields: _ERRORS.append((message, fields))
    return s3


def _identity(actor="alice"):
    """The block the API stamps onto a user action. The create path carries none.

    Args:
      actor: The verified username it names.

    Returns:
      A body fragment carrying the block.

    Raises:
      None.
    """
    return {"identity": {"actor": actor, "delegated_by": None, "assurance": "interactive"}}


def _inbox(s3, username):
    raw = s3.store.get(("user-bucket", f"{username}/user_settings/notifications.json"))
    return json.loads(raw) if raw else None


# The two senders every test names explicitly. A create legitimately comes from an execution
# role. The user-action tests send as the portal role, the one sender the create guard refuses,
# so they are also the proof that the guard is create-only — in the running system that role
# holds no grant here and a user action arrives from the API's execution role.
SERVICE_SENDER = "AROASERVICE:producer"
PORTAL_SENDER = "AROAPORTAL:alice"

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
    # own layer and constrains nothing that arrives here: no SQS condition key reaches a message
    # body, and the sender check judges who sent a create, not what it carries. Refusing
    # dead-letters the one message; truncating would write a half-object into an inbox every
    # poll downloads whole.
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
    result = w.handler(_msg({"action": "markRead", "id": "a", **_identity()}, PORTAL_SENDER), None)
    by_id = {n["id"]: n for n in _inbox(s3, "alice")}
    assert by_id["a"]["read"] is True and by_id["b"]["read"] is False
    assert result["matched"] == 1


def test_mark_all_read():
    inbox = [
        {"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"},
        {"id": "b", "message": "b", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"},
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markAllRead", **_identity()}, PORTAL_SENDER), None)
    assert all(n["read"] for n in _inbox(s3, "alice"))


def test_a_user_action_with_no_identity_block_is_rejected():
    """Fail closed on the pre-cutover envelope, in this handler's own exception type.

    The old test named the missing ``idToken``; there is no token to miss now, and the message
    a user action arrives without is the block. The exception TYPE is what the SQS
    retry-into-DLQ contract is expressed in, so it is asserted rather than the wording alone.
    """
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "markAllRead"}, PORTAL_SENDER), None),
        w.AuthorizationError,
        "identity block",
    )


def test_a_create_with_no_identity_block_still_writes_the_inbox():
    """The trusted-producer path has never had an actor, and this spec does not give it one.

    Every failure notification in the system comes through here, written by the control-plane
    execution roles with a body ``username`` and no block. A ``trusted_actor`` hoisted above
    ``_resolve_username``'s branch — the obvious simplification, and the one a "one reader,
    every call site" sweep pushes toward — refuses every one of them. It would be silent, too:
    the producers notify best-effort, so archives and shares would complete and users would
    simply never be told.
    """
    s3 = _setup()

    w.handler(_msg({"action": "create", "username": "alice", "message": "hi"}, SERVICE_SENDER), None)

    assert len(_inbox(s3, "alice")) == 1


def test_a_create_carrying_a_block_still_writes_the_BODYS_username():
    """The create arm reads the body, and an identity block riding along does not redirect it.

    Not a hypothetical: the producers are execution roles, and if one ever started stamping a
    block the inbox must not silently move to whoever it named. The branch decides, not the
    presence of a field.
    """
    s3 = _setup()

    w.handler(
        _msg(
            {"action": "create", "username": "alice", "message": "hi", **_identity("mallory")},
            SERVICE_SENDER,
        ),
        None,
    )

    assert len(_inbox(s3, "alice")) == 1
    assert _inbox(s3, "mallory") is None


def test_a_mark_read_with_a_username_and_no_block_is_still_refused():
    """The body username is not a fallback on the user arm, even when it is the only name there."""
    _setup()
    _raises(
        lambda: w.handler(
            _msg({"action": "markAllRead", "username": "alice"}, PORTAL_SENDER), None
        ),
        w.AuthorizationError,
        "identity block",
    )


def test_a_user_action_ignores_a_body_username_and_writes_the_blocks_inbox():
    """Two different users, and the trusted one wins — now beside a field that is trusted.

    The body's ``username`` was always ignored on a user action. It matters more now than it
    did: it sits next to a field this handler DOES trust, so a reader that took the wrong one
    would write mallory's request into alice's inbox and look completely normal doing it.
    """
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})

    w.handler(
        _msg(
            {"action": "markRead", "id": "a", "username": "mallory", **_identity("alice")},
            PORTAL_SENDER,
        ),
        None,
    )

    assert _inbox(s3, "alice")[0]["read"] is True
    assert _inbox(s3, "mallory") is None


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
    control planes and the API. Recorded in docs/decisions/control-planes.md.

    If this starts failing, the writer became idempotent: revisit the decision and the
    delivery-doc note, do not delete the test.
    """
    s3 = _setup()
    record = {
        "body": json.dumps({"action": "create", "username": "alice", "message": "hi"}),
        "attributes": {"SenderId": SERVICE_SENDER},
    }

    w.handler({"Records": [record]}, None)
    w.handler({"Records": [record]}, None)  # same message, redelivered

    inbox = _inbox(s3, "alice")
    assert len(inbox) == 2
    assert inbox[0]["message"] == inbox[1]["message"] == "hi"
    assert inbox[0]["id"] != inbox[1]["id"]


# ── The create boundary: who may write to another user's inbox ───────────────


def _refusals():
    """The reason codes captured from observability.error this test."""
    return [fields.get("reason") for message, fields in _ERRORS if message == "create refused"]


def test_a_create_from_the_portal_role_is_refused_and_nothing_is_written():
    """The sender check itself.

    The writer takes the body's username for a create, which is right — a plane telling Bob
    that Alice sent him files writes the create itself, with no identity block, and Bob is not
    the caller it acted for. What was missing, while the portal role held a grant on this
    queue, is that it could send one too, because IAM cannot condition on a message body.
    SenderId can.
    """
    s3 = _setup()

    result = w.handler(
        _msg({"action": "create", "username": "victim", "message": "click here"}, PORTAL_SENDER),
        None,
    )

    assert _inbox(s3, "victim") is None, "a forged create reached an inbox"
    assert result["refused"] == w.CREATE_REFUSAL_UNTRUSTED
    assert _refusals() == [w.CREATE_REFUSAL_UNTRUSTED]


def test_a_bare_role_id_with_no_session_name_is_refused():
    """The comparison is on the role-id half, so a value with no half still resolves to one.

    Equality against the WHOLE SenderId would never match a real message and would read
    exactly like a control that works.
    """
    s3 = _setup()

    w.handler(_msg({"action": "create", "username": "victim", "message": "x"}, "AROAPORTAL"), None)

    assert _inbox(s3, "victim") is None
    assert _refusals() == [w.CREATE_REFUSAL_UNTRUSTED]


def test_a_refused_create_DROPS_rather_than_raising_even_with_no_username():
    """The refusal must not become a dead-letter, and this is the case that would.

    The guard sits above the username resolution, not inside the create branch. Lower, a
    forged create that simply omits `username` would reach "create requires a username" and
    RAISE — three invocations and one permanent message on a dead-letter queue that is
    deliberately undrained, per forged request, which is a way for whoever could send as the
    portal role to drown the only operator-facing signal this plane has.
    """
    s3 = _setup()

    result = w.handler(_msg({"action": "create", "message": "no username here"}, PORTAL_SENDER), None)

    assert result["refused"] == w.CREATE_REFUSAL_UNTRUSTED
    assert _inbox(s3, "victim") is None
    assert "count" not in result, "a refusal reported a write it did not make"


def test_the_untrusted_sender_id_is_wired_to_the_PORTAL_ROLES_UNIQUE_ID_end_to_end():
    """The infra half, pinned across all three hops rather than at the Lambda alone.

    lambda.tf on its own cannot see where the value comes from. A MISSING root wiring fails
    tofu validate, because the variable has no default — but a WRONG one does not: the role's
    ARN and its name live in the same module as the right value, and either would validate
    clean and then never match at runtime, which reads exactly like a control that works.
    """
    import os
    import re

    infra = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra")

    with open(os.path.join(infra, "modules", "notifications", "lambda.tf")) as handle:
        lambda_tf = handle.read()
    assert re.search(
        r"^\s*NOTIFICATIONS_UNTRUSTED_SENDER_ID\s*=\s*var\.portal_role_unique_id\s*$",
        lambda_tf,
        re.MULTILINE,
    ), "the writer must take the sender it refuses from var.portal_role_unique_id"

    with open(os.path.join(infra, "main.tf")) as handle:
        root = handle.read()
    assert re.search(
        r"^\s*portal_role_unique_id\s*=\s*module\.data\.portal_role_unique_id\s*$",
        root,
        re.MULTILINE,
    ), "the root must pass module.data.portal_role_unique_id to the notifications module"

    with open(os.path.join(infra, "modules", "data", "outputs.tf")) as handle:
        outputs = handle.read()
    # Split rather than match a brace-delimited block: the description legitimately contains
    # braces ("{unique_id}:{session-name}"), so a [^}]* block match stops inside the prose.
    parts = outputs.split('output "portal_role_unique_id"', 1)
    assert len(parts) == 2, "module.data must output the portal role's unique id"
    assert re.search(
        r"^\s*value\s*=\s*aws_iam_role\.portal\.unique_id\s*$", parts[1], re.MULTILINE
    ), "the output must be the role's unique_id — not its name, not its ARN"

    # The variable's own two guards, both silent-failure-shaped if removed. A default would let
    # a root that forgets the wiring deploy a writer that refuses every notification in the
    # product; the shape check is what catches a wire to the ARN or the name, which validate
    # accepts and which then never matches at runtime.
    with open(os.path.join(infra, "modules", "notifications", "variables.tf")) as handle:
        variables = handle.read()
    declared = variables.split('variable "portal_role_unique_id"', 1)
    assert len(declared) == 2, "the notifications module must declare portal_role_unique_id"
    block = declared[1].split("\nvariable ", 1)[0]
    assert not re.search(r"^\s*default\s*=", block, re.MULTILINE), (
        "portal_role_unique_id must take NO default — a root that forgets to wire it has to "
        "fail at plan, not deploy a writer that refuses every create"
    )
    assert "AROA" in block and "validation" in block, (
        "portal_role_unique_id must keep its validation block — the role's ARN and its name "
        "are the plausible mis-wires and both validate clean without it"
    )


def test_an_unhashable_action_reaches_the_writer_s_own_refusal():
    """A list HASHES on the way into the membership test, so before the type check it raised
    TypeError there — reported as an unexpected error rather than as the named refusal, which on
    this writer also decides whether the record is retried or dropped."""
    s3 = _setup()

    _raises(
        lambda: w.handler(_msg({"action": ["markRead"], "id": "n-1"}, PORTAL_SENDER), None),
        w.ValidationError,
        "unknown action: ['markRead']",
    )
    assert _inbox(s3, "alice") is None
