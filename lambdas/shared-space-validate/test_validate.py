"""Unit tests for the validate-authorize Lambda.

The actor needs no stub: it is read out of the identity block the API stamps, which this
harness builds. Every envelope still carries the advisory flat ``actor`` the producer writes,
set to a DIFFERENT user, so each case also asserts the block wins over the field beside it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import auth
import cache
import validate as v
from fakes import install, raises

import config

_PENDING_KEY = ("user-bkt", "alice/user_settings/shared-connections.json")


def _event(
    action="create",
    space="sales",
    actor="alice",
    members=None,
    identity=True,
    origin=None,
    new_owner=None,
    sender=None,
):
    body = {
        "schemaVersion": 1,
        "requestId": "r1",
        "action": action,
        "actor": "spoofed",
        "space": space,
    }
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    if origin is not None:
        body["origin"] = origin
    if members is not None:
        body["payload"] = {"members": members}
    if new_owner is not None:
        body["payload"] = {"newOwner": new_owner}
    record = {"body": json.dumps(body)}
    if sender is not None:
        record["attributes"] = {"SenderId": sender}
    return [record]


def _seed_reg(s3, name="sales", owner="alice", members=("alice", "bob")):
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active"}
    ).encode()


def test_validate_create_emits_context_with_the_blocks_actor():
    install()
    ctx = v.handler(_event("create", "sales", actor="alice"), None)
    assert ctx == {
        "action": "create",
        "actor": "alice",
        "space": "sales",
        "payload": {},
        "registry": None,
        "requestId": "r1",
    }
    # Neither key is seeded on the happy path, and that is load-bearing rather than tidy:
    # `IsPresent` is TRUE for a field that is present and null, so a null `refusal` here would
    # route EVERY request on this plane into the router's refusal branch.
    assert "refusal" not in ctx
    assert "origin" not in ctx


def test_validate_rejects_non_owner_before_context():
    s3, *_ = install()
    _seed_reg(s3, members=["alice"])
    raises(
        lambda: v.handler(_event("delete", "sales", actor="mallory"), None),
        auth.AuthorizationError,
        "owner-only",
    )


def test_validate_refuses_a_message_with_no_identity_block():
    """Fail closed on the pre-cutover envelope, in this plane's own exception type.

    The old test here proved a forged TOKEN was refused, which cannot fail once no token is
    read — so it is re-expressed rather than deleted. The envelope this builds is exactly the
    one a message enqueued before the flip carries: a flat ``actor`` naming somebody, and no
    block. It must be refused, and the refusal must not fall back to that name.
    """
    install()
    raises(
        lambda: v.handler(_event("create", identity=False), None),
        auth.AuthorizationError,
        "identity block",
    )


# Intent recording: the durable pending cache entry + start notification (create/delete).


# ── FR-002: who may transfer, and to whom ────────────────────────────────────
#
# Every one of these is a RETURN VALUE rather than a raise, and asserted BY REASON CODE and by the
# member it names. A raise here reaches ValidateFailureSeed, which nulls the actor and the space,
# and the notifier treats a null actor as no trustworthy recipient — so a raised refusal is a
# refusal nobody is told about.

_READER_ROLE = "AROAEXAMPLETRANSFERREADER"


def _refusal(event):
    """Runs the validator and returns the refusal on the context it produced.

    Args:
      event: The Pipe envelope.

    Returns:
      The refusal mapping, or None when the request was accepted.

    Raises:
      None.
    """
    return v.handler(event, None).get("refusal")


def test_a_non_owner_is_refused_by_name_and_the_record_is_untouched():
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob", "mallory"])
    before = dict(s3.store)

    refusal = _refusal(_event("transfer_ownership", actor="mallory", new_owner="bob"))

    assert refusal["code"] == "TransferNotOwner"
    assert s3.store == before, "a refused transfer writes nothing"


def test_a_target_who_is_not_a_member_is_refused_and_the_refusal_names_them():
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    refusal = _refusal(_event("transfer_ownership", actor="alice", new_owner="stranger"))

    assert refusal["code"] == "TransferTargetNotMember"
    assert "stranger" in refusal["message"], "the owner cannot act on a refusal that names nobody"


def test_transferring_to_the_current_owner_is_refused_as_a_no_op():
    """Otherwise the pair of notifications goes out for a transfer that did not happen."""
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    refusal = _refusal(_event("transfer_ownership", actor="alice", new_owner="alice"))

    assert refusal["code"] == "TransferTargetIsOwner"
    assert "alice" in refusal["message"]


def test_a_pending_member_is_an_ACCEPTABLE_target():
    """Pending records that they have not signed in, not their entitlement — access was granted at
    add time. Refusing would make a space untransferable for a reason its owner cannot fix."""
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])
    record = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    record["acknowledged"] = []  # bob has never signed in
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()

    assert _refusal(_event("transfer_ownership", actor="alice", new_owner="bob")) is None


def test_a_space_that_is_not_active_is_refused():
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])
    record = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    record["status"] = "provisioning"
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()

    assert _refusal(_event("transfer_ownership", actor="alice", new_owner="bob"))["code"] == (
        "TransferSpaceNotActive"
    )


def test_an_emptied_space_says_it_was_DELETED_rather_than_that_nobody_is_a_member():
    """The state a delete leaves: active, no owner, blank roster, an emptied stamp.

    Both refusals would be true. Only one is the true sentence, and the emptied case is
    distinguishable before the membership check runs — which is the only reason it can be said.
    """
    s3, *_ = install()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {
            "name": "sales",
            "members": [],
            "acknowledged": [],
            "status": "active",
            "emptiedAt": "2026-02-01T00:00:00Z",
            "previousOwner": "alice",
        }
    ).encode()

    refusal = _refusal(_event("transfer_ownership", actor="alice", new_owner="bob"))

    assert refusal["code"] == "TransferSpaceEmptied"
    assert "deleted" in refusal["message"]


# ── FR-008: the operator-origin boundary ─────────────────────────────────────


def _operator_event(action="transfer_ownership", sender=f"{_READER_ROLE}:session", **kw):
    """Builds an operator-origin envelope: an origin, no identity block, and a stamped sender.

    Args:
      action: The action to request.
      sender: The SenderId SQS would have stamped.
      **kw: Passed through to the envelope builder.

    Returns:
      The Pipe envelope.

    Raises:
      None.
    """
    return _event(action, identity=False, origin="operator", sender=sender, **kw)


def test_an_operator_message_from_the_reader_role_is_accepted_and_records_its_origin():
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(_operator_event(new_owner="bob"), None)

    assert "refusal" not in ctx
    assert ctx["origin"] == "operator"
    assert ctx["actor"] == "alice", (
        "the notifiable party is the space's own owner: `operator` passes the catalog rule and "
        "would address a real user's prefix, and the writer validates no username"
    )


def test_an_operator_message_from_any_other_principal_is_refused_not_dropped():
    """Unlike the notifications boundary this queue is drained, and a forgery has a named victim —
    so the refusal has to reach NotifyFailure rather than be logged and swallowed."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(_operator_event(new_owner="bob", sender="AROASOMEONEELSE:session"), None)

    assert ctx["refusal"]["code"] == "TransferOriginUntrusted"
    assert ctx["actor"] == "alice", "the owner is told somebody tried"
    # The whole justification for routing this to the notifier rather than dropping it is that the
    # forgery has a NAMED victim. A sentence that names no space tells them nothing they can act
    # on, and only an assertion on the rendered text catches that — the code is right either way.
    assert "sales" in ctx["refusal"]["message"], ctx["refusal"]["message"]


def test_an_operator_message_with_no_sender_at_all_is_refused():
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(_event("transfer_ownership", identity=False, origin="operator", new_owner="bob"), None)

    assert ctx["refusal"]["code"] == "TransferOriginUntrusted"


def test_an_unset_reader_role_reports_ITSELF_rather_than_blaming_the_message():
    """Order copied from the notifications boundary: the configuration is tested before the
    sender, so a deploy that never wired the role id cannot come back as `sender-id-absent` and
    describe a broken message where the truth is a broken deploy."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = ""
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(_operator_event(new_owner="bob", sender=""), None)

    assert ctx["refusal"]["code"] == "TransferOriginNotConfigured"


def test_the_comparison_is_against_the_role_ID_half_and_not_a_name_or_an_ARN():
    """SenderId carries neither a role name nor an ARN, so a comparison against one silently never
    matches. The session half is never examined, and equality — not a prefix — is what is used."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    assert "refusal" not in v.handler(
        _operator_event(new_owner="bob", sender=f"{_READER_ROLE}:a-different-session"), None
    ), "the session half must not be compared"

    for wrong in (
        "shared-space-transfer-reader-role",                      # the role NAME
        "arn:aws:iam::1:role/shared-space-transfer-reader-role",  # the role ARN
        f"{_READER_ROLE}EXTRA:session",                           # a role whose id merely starts the same
    ):
        ctx = v.handler(_operator_event(new_owner="bob", sender=wrong), None)
        assert ctx["refusal"]["code"] == "TransferOriginUntrusted", f"{wrong!r} was accepted"


def test_a_message_carrying_BOTH_an_origin_and_an_identity_block_is_refused():
    """Refused rather than resolved to one of them: two credentials on one message is a caller and
    a service disagreeing about which door this came through."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(
        _event(
            "transfer_ownership",
            actor="alice",
            identity=True,
            origin="operator",
            new_owner="bob",
            sender=f"{_READER_ROLE}:session",
        ),
        None,
    )

    assert ctx["refusal"]["code"] == "TransferOriginBothCredentials"


def test_an_unrecognised_origin_fails_closed():
    """An unknown origin is refused rather than treated as an ordinary UI request, the way an
    unknown assurance is."""
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    ctx = v.handler(
        _event("transfer_ownership", identity=False, origin="cron", new_owner="bob", sender="x:y"),
        None,
    )

    assert ctx["refusal"]["code"] == "TransferOriginUnknown"
    assert "sales" in ctx["refusal"]["message"]
    # The trace records the origin that was DECLARED. Recording it as `operator` would describe an
    # operator request that never happened.
    assert ctx["origin"] == "cron"


def test_every_operator_refusal_names_the_space_it_is_about(captured_events):
    """All five reach the same notifier and the same named victim — the space's own owner.

    Enumerated rather than sampled: two of the five had rendered-text assertions and three did
    not, so reverting those three to an empty space left the suite green while the owner received
    `That request to transfer "" ...`. The reason codes are identical either way, which is exactly
    why asserting them is not enough.

    The trace assertion rides here because it is a DIFFERENT SINK from the context's `origin`
    field: a test reading the context cannot see what the span recorded.
    """
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    cases = [
        ("TransferOriginUntrusted", _operator_event(new_owner="bob", sender="AROAOTHER:s")),
        ("TransferOriginActionNotAllowed", _operator_event(action="delete")),
        ("TransferOriginBothCredentials",
         _event("transfer_ownership", actor="alice", identity=True, origin="operator",
                new_owner="bob", sender=f"{_READER_ROLE}:s")),
        ("TransferOriginUnknown",
         _event("transfer_ownership", identity=False, origin="cron", new_owner="bob", sender="x:y")),
    ]
    for code, event in cases:
        ctx = v.handler(event, None)
        assert ctx["refusal"]["code"] == code
        assert "sales" in ctx["refusal"]["message"], f"{code} names no space: {ctx['refusal']['message']}"

    config.TRANSFER_READER_ROLE_ID = ""
    ctx = v.handler(_operator_event(new_owner="bob", sender=""), None)
    assert ctx["refusal"]["code"] == "TransferOriginNotConfigured"
    assert "sales" in ctx["refusal"]["message"]

    origins = {
        event["fields"]["origin"]
        for event in captured_events.events
        if "origin" in (event.get("fields") or {})
    }
    assert origins == {"operator", "cron"}, (
        f"the span recorded {origins}: it must carry the origin that was DECLARED, not the one "
        "this service accepts — a refused `cron` message logged as `operator` describes a request "
        "that never happened"
    )


def test_the_operator_door_is_open_for_transfer_ONLY_enumerated_over_every_action():
    """Enumerated from the action vocabulary itself, so an action added later arrives here without
    anyone remembering to add it — and arrives refused, which is the safe default."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    others = sorted(config.VALID_ACTIONS - {"transfer_ownership"})
    assert others, "the enumeration found nothing, so this test asserts nothing"

    for action in others:
        ctx = v.handler(_operator_event(action=action, new_owner="bob"), None)
        assert ctx["refusal"]["code"] == "TransferOriginActionNotAllowed", (
            f"an operator-origin {action!r} was not refused"
        )


def test_an_operator_transfer_skips_only_the_owner_check_and_enforces_every_other_one():
    """FR-008: skipping the owner check is the door's purpose; skipping anything else is a hole."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE

    _seed_reg(s3, name="sales", owner="alice", members=["alice", "bob"])
    assert _refusal(_operator_event(new_owner="stranger"))["code"] == "TransferTargetNotMember"
    assert _refusal(_operator_event(new_owner="alice"))["code"] == "TransferTargetIsOwner"

    record = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    record["status"] = "deleting"
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()
    assert _refusal(_operator_event(new_owner="bob"))["code"] == "TransferSpaceNotActive"


if __name__ == "__main__":
    fns = [v_ for k, v_ in sorted(globals().items()) if k.startswith("test_") and callable(v_)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} validate tests passed.")
    sys.exit(0)


def test_the_deleting_card_names_the_verb_it_belongs_to():
    # The screen offers a retry on a card stuck in this state, and a card that does not say
    # which verb it came from is retried as a CREATE — the one verb that cannot work on a name
    # already taken. Its refusal then overwrites the discriminator, after which nothing can
    # enqueue a delete and the workspace is stranded.
    s3, *_ = install()
    cache.write_owner_deleting("alice", "sales")

    entry = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"][0]

    assert entry["status"] == "deleting" and entry["failedAction"] == "delete"
