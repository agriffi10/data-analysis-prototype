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

#: Events captured from observability.error. Module-level rather than a fixture because this
#: file also runs as a plain script, where the __main__ runner calls each test with no
#: arguments and a fixture parameter would be a TypeError. _setup clears it per test; under
#: pytest, lambdas/conftest.py's shared-layer snapshot restores the patched module afterwards.
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


def test_create_uses_body_username_not_token():
    s3 = _setup()
    # create carries no idToken; the body username is authoritative for trusted producers.
    w.handler(_msg({"action": "create", "username": "bob", "message": "x"}, SERVICE_SENDER), None)
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
        }, SERVICE_SENDER),
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
        w.handler(_msg(body, SERVICE_SENDER), None)
    for note in _inbox(s3, "alice"):
        assert "link" not in note


def test_create_persists_a_supplied_payload():
    # The file-operations plane attaches the structured field a reader needs to ACT on a
    # notification: which request it was, and which items it could not do. Persisted verbatim —
    # the shape decision belongs at the reader, which rebuilds the row field by field.
    s3 = _setup()
    payload = {"requestId": "r-1", "operation": "move", "conflicts": [{"itemKey": "alice/a/"}]}
    w.handler(
        _msg({"action": "create", "username": "alice", "message": "Moved 2 items", "payload": payload}, SERVICE_SENDER),
        None,
    )
    assert _inbox(s3, "alice")[0]["payload"] == payload


def test_a_create_without_a_payload_writes_EXACTLY_the_keys_it_always_wrote():
    # The writer half of "a row lacking the field is unchanged and valid". Six other planes
    # write rows and none of them is modified by this spec, so the assertion is on the KEY SET
    # rather than on the payload's absence — a new key of any name would fail here, which is the
    # point: this record is read by browsers that predate the field.
    inbox = w.apply_create([], "no payload")
    assert set(inbox[0]) == {"id", "message", "read", "timestamp"}

    linked = w.apply_create([], "a link but no payload", "/files?prefix=alice/")
    assert set(linked[0]) == {"id", "message", "read", "timestamp", "link"}


def test_a_payload_that_is_not_a_populated_object_is_treated_as_absent():
    # Same rule the link follows: an empty or wrong-typed value is absent, never a falsy field
    # every reader then has to defend against.
    s3 = _setup()
    for body in (
        {"action": "create", "username": "alice", "message": "empty", "payload": {}},
        {"action": "create", "username": "alice", "message": "a list", "payload": [1, 2]},
        {"action": "create", "username": "alice", "message": "a string", "payload": "r-1"},
        {"action": "create", "username": "alice", "message": "null", "payload": None},
    ):
        w.handler(_msg(body, SERVICE_SENDER), None)
    for note in _inbox(s3, "alice"):
        assert "payload" not in note


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


def test_the_payload_ceiling_admits_what_a_producer_can_legitimately_send():
    # Guard-the-guard: a ceiling below the largest legitimate payload would refuse real
    # notifications, which presents as a plane that silently stops reporting. Measured against a
    # payload carrying the request, both spaces, a full-length destination prefix and one
    # conflicted item at S3's own key limit.
    legitimate = {
        "requestId": "0" * 36,
        "operation": "move",
        "source": {"kind": "personal", "name": "a" * 63},
        "destination": {"kind": "shared", "name": "b" * 63, "prefix": "p" * 1024},
        "conflicts": [{"itemKey": "k" * 1024, "kind": "folder", "targetName": "t" * 255}],
    }

    assert len(json.dumps(legitimate).encode()) < w.MAX_PAYLOAD_BYTES


def test_create_requires_message():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "create", "username": "alice"}, SERVICE_SENDER), None),
        w.ValidationError,
        "message",
    )


def test_corrupt_doc_treated_as_empty():
    s3 = _setup()
    s3.store[("user-bucket", "alice/user_settings/notifications.json")] = b"{not json"
    w.handler(_msg({"action": "create", "username": "alice", "message": "hi"}, SERVICE_SENDER), None)
    assert len(_inbox(s3, "alice")) == 1


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


def test_mark_read_absent_id_is_noop():
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markRead", "id": "missing", "idToken": "alice"}, PORTAL_SENDER), None)
    assert _inbox(s3, "alice")[0]["read"] is False


def test_a_markread_that_changed_nothing_is_distinguishable_from_one_that_worked():
    """The silent no-op is the exact signature of "mark as read did nothing", and it
    still writes the inbox and reports a count — so without `matched` the two outcomes
    are identical in the logs and the bug cannot be diagnosed from a live run."""
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    assert w.handler(_msg({"action": "markRead", "id": "missing", "idToken": "alice"}, PORTAL_SENDER), None)["matched"] == 0


def test_matched_is_absent_for_actions_that_cannot_miss():
    """create/markAllRead have no id to miss, so they carry no `matched` field at all."""
    _setup({("user-bucket", "alice/user_settings/notifications.json"): []})
    assert "matched" not in w.handler(_msg({"action": "markAllRead", "idToken": "alice"}, PORTAL_SENDER), None)
    assert "matched" not in w.handler(_msg({"action": "create", "username": "alice", "message": "m"}, SERVICE_SENDER), None)


def test_mark_all_read():
    inbox = [
        {"id": "a", "message": "a", "read": False, "timestamp": "2026-01-02T00:00:00.000Z"},
        {"id": "b", "message": "b", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"},
    ]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markAllRead", "idToken": "alice"}, PORTAL_SENDER), None)
    assert all(n["read"] for n in _inbox(s3, "alice"))


def test_user_action_ignores_body_username():
    # markRead carries a forged username; the token (verified -> "alice") wins.
    inbox = [{"id": "a", "message": "a", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    s3 = _setup({("user-bucket", "alice/user_settings/notifications.json"): inbox})
    w.handler(_msg({"action": "markRead", "id": "a", "username": "victim", "idToken": "alice"}, PORTAL_SENDER), None)
    assert _inbox(s3, "alice")[0]["read"] is True
    assert _inbox(s3, "victim") is None


def test_user_action_without_token_rejected():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "markAllRead"}, PORTAL_SENDER), None),
        w.AuthorizationError,
        "idToken",
    )


def test_unknown_action_rejected():
    _setup()
    _raises(
        lambda: w.handler(_msg({"action": "delete", "username": "alice"}, PORTAL_SENDER), None),
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
    """The boundary itself.

    The writer takes the body's username for a create, which is right — a plane telling Bob
    that Alice sent him files holds no token for Bob. What was missing is that the browser
    could send one too, because IAM cannot condition on a message body. SenderId can.
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


def test_a_role_whose_unique_id_merely_STARTS_the_same_is_not_refused():
    """Why the comparison is equality on the half and not startswith.

    A prefix test would refuse an unrelated role whose unique ID happens to share an opening,
    and the symptom would be one plane's notifications silently vanishing.
    """
    s3 = _setup()

    w.handler(_msg({"action": "create", "username": "alice", "message": "x"}, "AROAPORTALX:s"), None)

    assert _inbox(s3, "alice") is not None
    assert _refusals() == []


def test_a_create_from_a_service_principal_is_written():
    """The positive control. Seven execution roles send every create in the product."""
    s3 = _setup()

    w.handler(_msg({"action": "create", "username": "alice", "message": "done"}, SERVICE_SENDER), None)

    assert len(_inbox(s3, "alice")) == 1
    assert _refusals() == []


def test_the_session_name_half_is_never_examined():
    """Cognito's enhanced flow does not document what it puts after the colon.

    Pinning a literal there would couple this boundary to an undocumented value, so the
    refusal must hold across any of them.
    """
    for session in ("CognitoIdentityCredentials", "something-else-entirely"):
        s3 = _setup()

        w.handler(
            _msg({"action": "create", "username": "victim", "message": "x"}, f"AROAPORTAL:{session}"),
            None,
        )

        assert _inbox(s3, "victim") is None, f"the refusal did not hold for session {session!r}"


def test_a_record_with_no_attributes_at_all_is_refused_under_ITS_OWN_reason():
    """A check that cannot run must not report a pass, and must not look like an attack.

    No SenderId means the control has broken; a portal SenderId means somebody tried it on.
    Those are operationally opposite, and one reason code would make them one log line.
    """
    s3 = _setup()

    result = w.handler(
        {"Records": [{"messageId": "msg-1", "body": json.dumps(
            {"action": "create", "username": "victim", "message": "x"})}]},
        None,
    )

    assert _inbox(s3, "victim") is None
    assert result["refused"] == w.CREATE_REFUSAL_NO_SENDER
    assert w.CREATE_REFUSAL_NO_SENDER != w.CREATE_REFUSAL_UNTRUSTED


def test_the_three_refusal_reason_codes_are_distinct():
    """Guard-the-guard: three codes that collapsed to one value would pass every test above."""
    codes = {w.CREATE_REFUSAL_UNTRUSTED, w.CREATE_REFUSAL_NO_SENDER, w.CREATE_REFUSAL_UNCONFIGURED}
    assert len(codes) == 3, f"the reason codes collapsed: {codes}"
    assert all(codes)


def test_a_refused_create_DROPS_rather_than_raising_even_with_no_username():
    """The refusal must not become a dead-letter, and this is the case that would.

    The guard sits above the username resolution, not inside the create branch. Lower, a
    forged create that simply omits `username` would reach "create requires a username" and
    RAISE — three invocations and one permanent message on a dead-letter queue that is
    deliberately undrained, per forged request, which is a way for any signed-in user to
    drown the only operator-facing signal this plane has.
    """
    s3 = _setup()

    result = w.handler(_msg({"action": "create", "message": "no username here"}, PORTAL_SENDER), None)

    assert result["refused"] == w.CREATE_REFUSAL_UNTRUSTED
    assert _inbox(s3, "victim") is None
    assert "count" not in result, "a refusal reported a write it did not make"


def test_a_refusal_echoes_no_part_of_the_body():
    """The body is the untrusted thing the refusal exists over.

    Echoing it would move the injection from the victim's inbox to the operator's log rather
    than removing it.
    """
    _setup()
    forged = {
        "action": "create",
        "username": "victim",
        "message": "SECRETMESSAGE",
        "link": "/SECRETLINK",
        "payload": {"requestId": "SECRETPAYLOAD"},
    }

    w.handler(_msg(forged, PORTAL_SENDER), None)

    emitted = json.dumps(_ERRORS)
    for secret in ("SECRETMESSAGE", "SECRETLINK", "SECRETPAYLOAD", "victim"):
        assert secret not in emitted, f"the refusal event echoed {secret!r} from the body"


def test_the_refusal_event_carries_the_message_id():
    """Dropping means nothing accumulates to notice, so the event is the only account.

    Without a correlator an operator cannot tie one refusal to one attempt, which is also
    what the live check reads. messageId is service-stamped like SenderId, not body data.
    """
    _setup()

    w.handler(_msg({"action": "create", "username": "victim", "message": "x"}, PORTAL_SENDER), None)

    assert [fields.get("message_id") for _, fields in _ERRORS] == ["msg-1"]


def test_the_portal_roles_OWN_actions_are_unaffected():
    """The browser's two legitimate actions, from the very role the create guard refuses.

    Without this, "the boundary works" cannot be told apart from "the browser can no longer
    reach the queue at all".
    """
    s3 = _setup(
        {("user-bucket", "alice/user_settings/notifications.json"): [
            {"id": "a", "message": "m", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}
        ]}
    )

    assert w.handler(_msg({"action": "markRead", "id": "a", "idToken": "alice"}, PORTAL_SENDER), None)["matched"] == 1
    assert _inbox(s3, "alice")[0]["read"] is True
    w.handler(_msg({"action": "markAllRead", "idToken": "alice"}, PORTAL_SENDER), None)
    assert _refusals() == []


def test_with_the_check_UNCONFIGURED_every_create_is_refused_and_user_actions_still_work():
    """The runtime fail-closed, which covers the window where new code meets old infrastructure.

    The order of the checks is what makes this true rather than inverted: with the variable
    unset, an absent sender's empty role-id half compares EQUAL to the empty variable, so a
    guard that compared first would pass every service create and refuse every honest
    absence. The configuration is tested first for exactly that reason.
    """
    s3 = _setup()
    w.UNTRUSTED_SENDER_ID = ""

    for sender in (SERVICE_SENDER, PORTAL_SENDER, ""):
        result = w.handler(_msg({"action": "create", "username": "alice", "message": "x"}, sender), None)
        assert result["refused"] == w.CREATE_REFUSAL_UNCONFIGURED, f"sender {sender!r} was not refused"

    assert _inbox(s3, "alice") is None

    s3.store[("user-bucket", "alice/user_settings/notifications.json")] = json.dumps(
        [{"id": "a", "message": "m", "read": False, "timestamp": "2026-01-01T00:00:00.000Z"}]
    ).encode()
    assert w.handler(_msg({"action": "markRead", "id": "a", "idToken": "alice"}, PORTAL_SENDER), None)["matched"] == 1


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


def test_no_terraform_file_still_claims_the_browser_CANNOT_enqueue_a_create():
    """The false-comment sweep, which this spec is mostly about.

    The grant's own comment used to say the browser could not enqueue a create for another
    user. True of the design, false of the policy — the dangerous combination, because a
    reader checking the IaC is told the question has been answered. Two more files carried
    near-duplicates of it, reworded rather than copied, which is exactly why a sweep for one
    literal string missed them. All three are checked in one pass here so a correction cannot
    fix one copy and leave its twin standing.
    """
    import os

    infra = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra")
    files = {
        "modules/notifications/iam.tf": ["cannot enqueue a `create` for another user",
                                         "reserved for trusted producers granted SendMessage separately"],
        "modules/notifications/outputs.tf": ["(future)"],
        "outputs.tf": ["(future trusted-producer)"],
    }
    for relative, phrases in files.items():
        with open(os.path.join(infra, *relative.split("/"))) as handle:
            text = handle.read()
        for phrase in phrases:
            assert phrase not in text, (
                f"infra/{relative} still says {phrase!r} — the policy is unconditioned and the "
                "writer's sender check is what enforces the boundary"
            )

    with open(os.path.join(infra, "modules", "notifications", "iam.tf")) as handle:
        iam = handle.read()
    assert "SenderId" in iam, (
        "iam.tf must name what actually enforces the boundary, or a reader is left with an "
        "unconditioned grant and no explanation"
    )


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
