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
from cpcommon import clients
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
    def _check(code, ctx):
        """Asserts one origin refusal names its space and does not name an action nobody asked for.

        Args:
          code: The reason code expected.
          ctx: The validated context the handler produced.

        Returns:
          None.

        Raises:
          AssertionError: On the wrong code, a missing space, or a transfer-specific sentence.
        """
        assert ctx["refusal"]["code"] == code
        message = ctx["refusal"]["message"]
        assert "sales" in message, f"{code} names no space: {message}"
        # ACTION-NEUTRAL, now that the door admits three actions. These five reach the space's
        # OWNER, so a sentence saying "to transfer" tells them someone tried to transfer their
        # workspace when the forged request was an add — and the reason codes are identical
        # either way, which is exactly why asserting them is not enough.
        assert "transfer" not in message.lower(), (
            f"{code} tells the owner about a transfer nobody asked for: {message}"
        )

    for code, event in cases:
        _check(code, v.handler(event, None))

    config.TRANSFER_READER_ROLE_ID = ""
    _check("TransferOriginNotConfigured", v.handler(_operator_event(new_owner="bob", sender=""), None))

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


def test_the_operator_door_admits_exactly_three_actions_and_refuses_every_other_one():
    """The admitted set is asserted by EXACT CONTENTS, and the refused set is enumerated from the
    difference — and the first half is what makes the second mean anything.

    A test that only walked `VALID_ACTIONS - OPERATOR_ACTIONS` stays green when `delete` joins the
    admitted set, because the set it asserts over shrinks with it. So the door's own contents are
    pinned first, and the loop then covers whatever is left.
    """
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    assert frozenset(
        {"transfer_ownership", "add_members", "remove_members"}
    ) == config.OPERATOR_ACTIONS

    others = sorted(config.VALID_ACTIONS - config.OPERATOR_ACTIONS)
    assert others, "the enumeration found nothing, so this test asserts nothing"
    assert set(others) == {"create", "delete", "leave", "forget", "acknowledge_membership"}

    for action in others:
        ctx = v.handler(_operator_event(action=action, new_owner="bob"), None)
        assert ctx["refusal"]["code"] == "TransferOriginActionNotAllowed", (
            f"an operator-origin {action!r} was not refused"
        )


def test_the_sender_comparison_is_the_only_fence_left_in_front_of_a_member_action():
    """Before the door widened, a forged operator `add_members` was refused for naming an action
    the door did not admit. It is now admitted, so the SenderId comparison is the whole fence —
    and no test drove a MEMBER action against it until this one.
    """
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    for action in sorted(config.MEMBER_ACTIONS):
        ctx = v.handler(_operator_event(action=action, members=["mallory"], sender="AROAOTHER:s"), None)
        assert ctx["refusal"]["code"] == "TransferOriginUntrusted", action

    config.TRANSFER_READER_ROLE_ID = ""
    for action in sorted(config.MEMBER_ACTIONS):
        ctx = v.handler(_operator_event(action=action, members=["mallory"]), None)
        assert ctx["refusal"]["code"] == "TransferOriginNotConfigured", action


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


# ── FR-003 / FR-004: one member-refusal predicate, for both origins ──────────
#
# The owner-only branch in `authorize` used to be the only thing between any signed-in user and
# any space's roster. It now lives in `auth.member_refusal`, so every one of these asserts the
# REASON CODE by name — "the request did not succeed" is equally true of a predicate that never
# ran and a router that lost the branch.


def _member_event(action="add_members", actor="alice", members=("carol",), **kw):
    """A UI member-change envelope: a verified identity block and a members payload.

    Args:
      action: `add_members` or `remove_members`.
      actor: The verified username the identity block carries.
      members: The payload's member list, or None to omit the key entirely. Passed through
        UNCHANGED unless it is the tuple default — a `list()` around it would turn the non-list
        cases these tests exist for, a bare string most of all, into a list of characters that
        normalises to something and is allowed.
      **kw: Passed through to the envelope builder.

    Returns:
      The Pipe envelope.

    Raises:
      None.
    """
    if isinstance(members, tuple):
        members = list(members)
    return _event(action, actor=actor, members=members, **kw)


def test_a_non_owner_member_change_is_refused_by_code_and_travels_as_a_VALUE():
    """It reaches the requester, which it does not today: `authorize` raised, the validator's
    Catch carries no ResultPath, the seed nulls the actor and the notifier stays silent on one.
    A member change that refuses is currently a request the user watches disappear.
    """
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob", "mallory"])

    for action in sorted(config.MEMBER_ACTIONS):
        ctx = v.handler(_member_event(action, actor="mallory", members=["bob"]), None)
        assert ctx["refusal"]["code"] == "MemberNotOwner", action
        assert ctx["actor"] == "mallory", "the refusal must reach whoever asked"


def test_the_four_request_level_refusals_say_ONE_thing_to_a_requester_and_the_DETAIL_to_an_operator():
    """Four discriminating sentences, delivered into the inbox of whoever asked for any space name
    they care to try, is an existence oracle over every shared space — the disclosure this project
    already declined when it refused to publish a shared-space directory. The CODES stay distinct,
    so the run still records which fired; only the sentence collapses.
    """
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE

    def _seed(**fields):
        record = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}
        record.update(fields)
        s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()

    ui_messages, operator_messages = {}, {}

    # 1. unknown space: nothing seeded.
    ui = v.handler(_member_event(actor="alice"), None)["refusal"]
    op = v.handler(_operator_event(action="add_members", members=["carol"]), None)["refusal"]
    assert ui["code"] == op["code"] == "MemberSpaceUnknown"
    ui_messages[ui["code"]], operator_messages[op["code"]] = ui["message"], op["message"]

    # 2-4. the three that need a record.
    for code, seed, ui_actor in (
        ("MemberSpaceEmptied", {"owner": "", "emptiedAt": "t1", "members": []}, "alice"),
        ("MemberSpaceNotActive", {"status": "deleting"}, "alice"),
        ("MemberNotOwner", {}, "mallory"),
    ):
        _seed(**seed)
        ui = v.handler(_member_event(actor=ui_actor, members=["carol"]), None)["refusal"]
        assert ui["code"] == code, f"expected {code}, got {ui['code']}"
        ui_messages[code] = ui["message"]
        if code != "MemberNotOwner":
            op = v.handler(_operator_event(action="add_members", members=["carol"]), None)["refusal"]
            assert op["code"] == code
            operator_messages[code] = op["message"]

    assert len(ui_messages) == 4
    assert len(set(ui_messages.values())) == 1, (
        f"a requester can tell these four apart, which is an existence oracle: {ui_messages}"
    )
    assert "sales" in next(iter(ui_messages.values())), "the collapsed sentence still names the space"
    # The operator is entitled to the detail, and the three reachable as an operator differ.
    # Three, not four: `MemberNotOwner` is unreachable on the operator path by construction, since
    # `requester is None` is exactly what skips that check.
    assert len(set(operator_messages.values())) == len(operator_messages) == 3, operator_messages
    assert not set(operator_messages.values()) & set(ui_messages.values())


def test_a_members_list_that_normalises_to_NOTHING_is_refused_rather_than_a_silent_no_op():
    """A raw-shape test alone lets `["  "]` through to a verb that reports success having done
    nothing at all.

    The API's contract does refuse a browser's `members` that is not a list of strings, so the
    shapes below that a browser could never send are here for the OTHER producer: the operator
    reader builds its own body and nothing validates that one. `["  "]` and a `payload` carrying
    no `members` key reach the predicate from either side.
    """
    s3, *_ = install()
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    for payload in (None, [], ["   "], [12], "carol"):
        ctx = v.handler(_member_event(actor="alice", members=payload), None)
        assert ctx["refusal"]["code"] == "MemberTargetsMissing", repr(payload)


def test_removing_the_space_owner_is_refused_BY_NAME_rather_than_dropped_silently():
    """`normalize_members` drops the owner, so today the request succeeds having removed nobody
    and notified no one — and "remove the owner who left" is the single most likely thing an
    operator writes in this file. The comparison is in the NORMALISED form, or `Alice` against
    owner `alice` passes the predicate and is silently dropped by the verb instead.
    """
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    for spelling in ("alice", "Alice", "  ALICE  "):
        ctx = v.handler(_member_event("remove_members", actor="alice", members=[spelling]), None)
        assert ctx["refusal"]["code"] == "MemberRemoveOwner", spelling
        assert "alice" in ctx["refusal"]["message"]

    # The whole request refuses, rather than that one name being dropped and the rest served.
    ctx = v.handler(_member_event("remove_members", actor="alice", members=["bob", "alice"]), None)
    assert ctx["refusal"]["code"] == "MemberRemoveOwner"

    # The OWNER side of that comparison is normalised too, and this is the one input where the
    # predicate is strictly load-bearing over the verb: `normalize_members` compares a normalised
    # name against a RAW owner, so with the owner stored as `Alice` the verb does NOT drop them
    # and the removal would go through. Every fixture above seeds a lowercase owner, so without
    # this case `owner.strip().lower()` could be reduced to `owner` with the suite still green.
    odd = {"name": "sales", "owner": "Alice", "members": ["Alice", "bob"], "status": "active"}
    assert auth.member_refusal("Alice", "sales", "remove_members", ["alice"], odd)[0] == (
        "MemberRemoveOwner"
    )

    # An ADD naming the owner keeps today's behaviour: normalised out, idempotent success. Both
    # shapes are pinned, because they are not the same case — with `bob` beside them the add does
    # real work, while the owner ALONE reaches the verb and adds nobody. That second one is a
    # silent no-op and is allowed deliberately: the owner is already a member, and FR-004 keeps an
    # add of an existing member an idempotent success because replay safety is worth more than the
    # diagnostic. Refusing it would contradict that and break the derived request ids that rest on
    # it. Pinned rather than implied, so the decision is visible if someone later reads the no-op
    # as a defect.
    assert "refusal" not in v.handler(
        _member_event("add_members", actor="alice", members=["alice", "bob"]), None
    )
    assert "refusal" not in v.handler(
        _member_event("add_members", actor="alice", members=["alice"]), None
    )


def test_a_registry_whose_owner_is_not_a_STRING_refuses_rather_than_raising():
    """The owner is compared in its normalised form for the removal check, which calls a string
    method on it. A truthiness test alone would pass a number or a list straight into `.strip()`,
    and an AttributeError in the validator reaches nobody: the Catch nulls the actor and the
    notifier stays silent. Not attacker-reachable — the registry is plane-written from a
    catalog-checked username — so what this pins is that the failure stays a refusal.
    """
    install()
    for owner in (123, ["alice"], {"name": "alice"}, None):
        record = {"name": "sales", "owner": owner, "members": [], "status": "active"}
        code, _ = auth.member_refusal(None, "sales", "remove_members", ["alice"], record)
        assert code == "MemberSpaceEmptied", f"owner={owner!r} gave {code}"


def test_the_predicate_is_the_only_authority_on_the_two_member_actions():
    """An owner check written in both places is the complement that drifts. `authorize` must not
    decide these at all — and `OWNER_ONLY_ACTIONS` is pinned by exact contents so that removing
    its last member cannot pass as tidying.
    """
    install()
    assert frozenset({"delete"}) == config.OWNER_ONLY_ACTIONS

    record = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}
    for action in sorted(config.MEMBER_ACTIONS):
        assert auth.authorize(action, "sales", "mallory", record) is None, (
            f"authorize still decides {action}, so the owner check is written twice"
        )


def test_authorize_refuses_an_action_it_has_no_branch_for_rather_than_falling_through():
    """The fall-through used to be unreachable, so returning None from the bottom was harmless.
    Two actions are now deliberately allowed there and gated elsewhere, which makes losing the
    `member_refusal` call an open door rather than a refusal.
    """
    install()
    # Restored in a finally: the vocabulary is a module constant the conftest snapshot does not
    # cover, and leaking a synthetic action out of here reddens the wording table's own
    # enumeration in a different file.
    original = config.VALID_ACTIONS
    config.VALID_ACTIONS = frozenset(original | {"annex_space"})
    try:
        raises(
            lambda: auth.authorize("annex_space", "sales", "mallory", {"owner": "alice"}),
            auth.AuthorizationError,
            "unhandled action",
        )
    finally:
        config.VALID_ACTIONS = original


def test_a_message_declaring_ANY_origin_cannot_skip_the_owner_check():
    """The validator sets `requester = None` for any non-None origin, BEFORE `operator_refusal`'s
    verdict has been consulted. That is safe only while the member predicate runs inside the same
    `refusal is None` guard the transfer predicate sits in — called outside it, or with its result
    overwriting the origin refusal, a message declaring any origin string at all skips the check.
    """
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    for action in sorted(config.MEMBER_ACTIONS):
        ctx = v.handler(
            _event(action, identity=False, origin="anything", members=["mallory"], sender="x:y"),
            None,
        )
        assert ctx["refusal"]["code"] == "TransferOriginUnknown", (
            f"a member {action} declaring an unrecognised origin survived as "
            f"{ctx['refusal']['code']}"
        )


def test_an_operator_member_change_proceeds_where_the_same_change_from_a_non_owner_refuses():
    """Both halves are needed. The first alone passes with the owner check deleted; the second
    alone passes with the operator skip deleted."""
    s3, *_ = install()
    config.TRANSFER_READER_ROLE_ID = _READER_ROLE
    _seed_reg(s3, owner="alice", members=["alice", "bob"])

    for action in sorted(config.MEMBER_ACTIONS):
        allowed = v.handler(_operator_event(action=action, members=["bob"]), None)
        assert "refusal" not in allowed, f"an operator {action} was refused: {allowed.get('refusal')}"
        assert allowed["actor"] == "alice", "the operator's request is attributed to the owner"
        refused = v.handler(_member_event(action, actor="mallory", members=["bob"]), None)
        assert refused["refusal"]["code"] == "MemberNotOwner", action


def test_member_refusal_makes_no_aws_call_at_all():
    """Pure, like the two predicates beside it. A predicate that read anything would be a second
    authority on a question the validator has already loaded the answer to.
    """
    s3, glue, lf, cognito = install()
    calls = []
    for fake in (s3, glue, lf, cognito, clients._sqs):
        for name in [n for n in dir(fake) if not n.startswith("_") and callable(getattr(fake, n))]:
            def watch(*a, _n=name, **kw):
                calls.append(_n)
            setattr(fake, name, watch)

    record = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}
    assert auth.member_refusal("alice", "sales", "add_members", ["carol"], record) is None
    assert auth.member_refusal("mallory", "sales", "add_members", ["carol"], record)[0]
    assert auth.member_refusal(None, "sales", "remove_members", ["alice"], record)[0]
    assert calls == [], f"member_refusal called {calls}"


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
