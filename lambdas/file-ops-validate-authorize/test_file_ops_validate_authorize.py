"""The file-operations front door: what it accepts, what it refuses, and which of the two.

Pure logic, AWS stubbed. The cases worth reading first are the ones about the SPLIT — a
whole-request raise versus a per-item outcome record — because getting that wrong in either
direction is a user-visible regression rather than a bug: refusing a whole select-all delete
because one folder is protected removes something the browser has always done, and carrying on
past a containment breach is a cross-tenant write.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_validate_authorize as v
from cpcommon.errors import TerminalError
from token_shapes import JWT_SHAPED

SUBMITTED = "2020-01-01T00:00:00Z"


def _setup(spaces=None):
    """Stubs the boundary helpers: the known registry spaces and the notification sink.

    The actor needs no stub — it comes from the identity block ``_body`` builds.
    """
    v.authz.reg.load = lambda name: (spaces or {}).get(name)
    v.notify.emit_notification = lambda *a, **kw: None


_JWT = JWT_SHAPED


def _body(
    operation="copy",
    space=None,
    items=...,
    destination=...,
    actor="alice",
    identity=True,
    flat_actor=None,
    **extra,
):
    body = {
        "requestId": "req-1",
        "operation": operation,
        "source": {
            "space": space if space is not None else {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/q1.csv"}] if items is ... else items,
        },
    }
    if operation != "delete":
        body["destination"] = (
            {"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/out/"}
            if destination is ...
            else destination
        )
        body["onConflict"] = "refuse"
        body["submittedAt"] = SUBMITTED
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    if flat_actor is not None:
        body["actor"] = flat_actor
    body.update(extra)
    return body


def _event(**kwargs):
    return [{"body": json.dumps(_body(**kwargs))}]


def _run(**kwargs):
    _setup(**{k: kwargs.pop(k) for k in ("spaces",) if k in kwargs})
    return v.handler(_event(**kwargs), None)


def _refusal(**kwargs):
    with pytest.raises(TerminalError) as caught:
        _run(**kwargs)
    return caught.value


def _refused(**kwargs):
    return _refusal(**kwargs).reason


# ── The contract ─────────────────────────────────────────────────────────────


def test_a_valid_copy_is_accepted_and_resolves_both_sides():
    result = _run()

    assert result["actor"] == {"username": "alice"}
    assert result["operation"] == "copy"
    assert result["source"]["root"] == "alice/"
    assert result["destination"]["prefix"] == "alice/out/"
    assert result["outcomes"] == []
    # The run's trace, which every later verb on this plane adopts.
    assert result["traceparent"].startswith("00-")


def test_the_copy_move_fields_are_NORMALISED_TO_NULL_for_a_delete():
    """Rejected on the way in, emitted as explicit nulls on the way out.

    The state stays one shape for all three operations, so no later state has to ask whether a
    field is there — and a Pass reading an absent path raises an uncatchable ``States.Runtime``,
    which is the failure this normalisation exists to make unreachable.
    """
    result = _run(operation="delete")

    assert result["destination"] is None
    assert result["onConflict"] is None
    assert result["submittedAt"] is None


# ── Authorization ────────────────────────────────────────────────────────────


def test_a_source_space_that_is_not_the_actors_is_refused():
    """Every key is INSIDE bob's root, so only the space check can refuse this.

    The fixture used to leave the items at alice's default, which meant containment refused the
    request whether or not the space check ran — measured by deleting that check and watching this
    file stay green. Both branches raise `forbidden` with the same deliberately uninformative
    detail (the space's existence is not disclosed), so the reason cannot discriminate them and
    the fixture has to.
    """
    assert (
        _refused(
            space={"kind": "personal", "name": "bob"},
            items=[{"kind": "file", "key": "bob/q1.csv"}],
            destination={"space": {"kind": "personal", "name": "bob"}, "prefix": "bob/out/"},
        )
        == "forbidden"
    )


# ── Containment: whole-request, every time ───────────────────────────────────


@pytest.mark.parametrize(
    "key",
    ["alice2/q1.csv", "bob/q1.csv", "alice/../bob/secrets.csv", "/etc/passwd"],
)
def test_a_key_outside_the_authorized_root_fails_the_WHOLE_request(key):
    """Not a per-item skip. A request naming a key outside the actor's own space is not a request
    with one bad row in it — there is no sensible partial execution of it."""
    assert _refused(items=[{"kind": "file", "key": key}]) == "forbidden"


def test_two_items_that_would_land_on_ONE_key_fail_the_whole_request():
    """Whole-request rather than per-item, because neither of the two colliding items is the
    wrong one: there is no item to fail and no way to choose.

    Today's browser catches this only by accident — the second item's existence probe finds the
    first item's freshly-written object — so under an overwrite answer one file would be lost and
    the request would report full success.
    """
    reason = _refused(
        items=[
            {"kind": "file", "key": "alice/a/x.csv"},
            {"kind": "file", "key": "alice/b/x.csv"},
        ],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/c/"},
    )

    assert reason == "colliding_item_names"


# ── Per-item outcomes: the rest of the selection proceeds ────────────────────


def test_a_folder_moved_INTO_ITSELF_is_refused_per_item():
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/reports/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/reports/sub/"},
    )

    assert result["outcomes"][0]["outcome"] == "refused"
    assert result["outcomes"][0]["reason"] == "destination_inside_source"


_SALES = {"sales": {"status": "active", "owner": "carol", "members": ["alice", "carol"]}}
_SALES_ROOT = {"space": {"kind": "shared", "name": "sales"}, "prefix": "sales/"}


@pytest.mark.parametrize(
    ("operation", "item", "on_conflict"),
    [
        ("move", {"kind": "folder", "key": "sales/stage/_data-quality-reports/"}, "refuse"),
        (
            "copy",
            {"kind": "folder", "key": "sales/stage/", "targetName": "_data-quality-reports"},
            "overwrite",
        ),
        ("copy", {"kind": "folder", "key": "sales/stage/", "targetName": "shared_tables"}, "overwrite"),
    ],
    ids=["move-a-nested-reports-folder-up", "copy-renamed-to-reports", "copy-renamed-to-shared-tables"],
)
def test_an_item_whose_OWN_KEY_lands_in_a_locked_folder_is_refused_and_its_sibling_proceeds(
    operation, item, on_conflict
):
    """The destination prefix is the space root, which is ordinary; the item's derived key is not.

    Each row was accepted with no refusal when only the prefix was judged, and in a shared space it
    let one member replace or add to another's data-quality reports.
    """
    result = _run(
        operation=operation,
        space={"kind": "shared", "name": "sales"},
        items=[item, {"kind": "file", "key": "sales/in/q1.csv"}],
        destination=_SALES_ROOT,
        onConflict=on_conflict,
        spaces=_SALES,
    )

    assert [(o["itemKey"], o["outcome"], o["reason"]) for o in result["outcomes"]] == [
        (item["key"], "protected", "destination_name_reserved")
    ]


def test_a_cross_space_copy_is_judged_at_the_destination_it_lands_in():
    """The derived rule is not one of the same-bucket pairing rules: personal into shared lands too."""
    result = _run(
        items=[{"kind": "folder", "key": "alice/stage/", "targetName": "_data-quality-reports"}],
        destination=_SALES_ROOT,
        spaces=_SALES,
    )

    assert result["outcomes"][0]["outcome"] == "protected"
    assert result["outcomes"][0]["reason"] == "destination_name_reserved"


_FINANCE = {"finance": {"status": "active", "owner": "carol", "members": ["alice", "carol"]}}


def test_the_derived_rule_is_judged_under_the_DESTINATION_space_s_kind_not_the_source_s():
    """A personal source into a shared nested ``system_settings/``: only the shared rule refuses it.

    The personal rule is root-anchored and passes the key, so the source's kind here lets the item
    go ahead and then meet the role's Deny at the write.
    """
    result = _run(
        items=[{"kind": "folder", "key": "alice/stage/", "targetName": "archive"}],
        destination={"space": {"kind": "shared", "name": "finance"}, "prefix": "finance/x/system_settings/"},
        spaces=_FINANCE,
    )

    assert result["outcomes"] == [
        {
            "itemKey": "alice/stage/",
            "label": "archive",
            "outcome": "protected",
            "reason": "destination_name_reserved",
        }
    ]


def test_an_item_both_locked_there_and_inside_itself_is_reported_as_locked():
    """The derived rule's seat is BEFORE into-itself, so the plane names the rule that refuses it."""
    result = _run(
        operation="move",
        space={"kind": "shared", "name": "finance"},
        items=[{"kind": "folder", "key": "finance/a/", "targetName": "archive"}],
        destination={"space": {"kind": "shared", "name": "finance"}, "prefix": "finance/a/system_settings/"},
        spaces=_FINANCE,
    )

    assert result["outcomes"][0]["outcome"] == "protected"
    assert result["outcomes"][0]["reason"] == "destination_name_reserved"


def test_a_copy_into_its_own_parent_is_still_a_no_op_rather_than_a_refusal():
    """The derived rule sits AFTER the no-op, which writes nothing and has no destination to judge."""
    result = _run(
        items=[{"kind": "folder", "key": "alice/shared_tables/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["outcomes"][0]["outcome"] == "noop"


def test_deleting_a_report_in_a_shared_space_is_refused_per_item():
    result = _run(
        operation="delete",
        space={"kind": "shared", "name": "sales"},
        items=[{"kind": "file", "key": "sales/_data-quality-reports/req-1/report.json"}],
        spaces=_SALES,
    )

    assert result["outcomes"][0]["outcome"] == "protected"
    assert result["outcomes"][0]["reason"] == "reports_folder_not_deletable"


# ── The contract with the state machine ──────────────────────────────────────


def test_the_output_supplies_every_path_the_MACHINE_reads_of_it():
    """The cross-check the neighbouring planes get from their `Validated` Pass, which this machine
    deliberately does not have.

    Without it the verb and the ASL drift silently in the worst direction: dropping ``requestId``
    from the output leaves every unit test green, and then every post-identity failure path raises
    an uncatchable ``States.Runtime`` BEFORE the notifier — so the user hears nothing about a
    request that already failed. Mutation-checked: removing a key from the emitted shape reddens
    this test and nothing else.

    Read from the rendered ASL rather than a hand-listed set, so a state that starts reading a new
    path is covered by existing rather than by being remembered.
    """
    import pathlib
    import re

    template = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra"
        / "modules"
        / "file-ops"
        / "state-machine.asl.json.tftpl"
    ).read_text()

    # READ paths only. A bare `$.x` search also matches every `ResultPath`, which is where a
    # state WRITES — `$.notifyError` is written by the notifier's own catch and read by nothing,
    # so counting it would demand the verb emit a field that exists to be created later.
    read = set(re.findall(r'"\w+\.\$": "\$\.(\w+)', template))
    read |= set(re.findall(r'"Variable": "\$\.(\w+)', template))

    # Paths a LATER state creates, each named with the state that emits it rather than pooled into
    # one allowance. A path that arrives here without a producer named is one nobody writes.
    created_later = {
        "lock": "AcquireLock",
        "error": "every Catch's ResultPath",
        "execution": "StampExecution",
        "guardPass": "SeedFirstGuardPass / SeedSecondGuardPass",
        "transfer": "BuildTransferManifest",
        "deletableCount": "CollectTransferResults",
    }
    produced = set(_run().keys()) | set(created_later)

    assert read <= produced, f"the machine reads {sorted(read - produced)}, which this verb never emits"


def test_the_SPACE_ROOT_is_refused_as_an_item():
    """The third way to select a protected folder, and the one no rule looks for.

    Every protected-location rule matches the named folder or something below it; none looks UP.
    A single item of ``alice/`` passes all of them while naming a subtree containing
    ``athenaresults/``, ``user_settings/``, ``archive/`` and every marker — a request this plane's
    own IAM refuses part-way through. The browser cannot express it, so refusing costs nothing.
    """
    assert _refused(operation="delete", items=[{"kind": "folder", "key": "alice/"}]) == "space_root_not_an_item"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation": "delete", "items": [{"kind": "folder", "key": "alice/"}]},
        {"operation": "delete", "space": {"kind": "personal", "name": "bob"}, "items": [{"kind": "file", "key": "bob/q1.csv"}]},
        {"operation": "rename"},
    ],
    ids=["space-root-not-an-item", "forbidden", "a-contract-refusal"],
)
def test_a_refusal_notifies_the_actor_WITH_the_request_id_their_browser_is_waiting_on(kwargs):
    """The browser settles its in-flight card by matching ``payload.requestId``, and a run refused
    here reaches no outcome producer — so a refusal without it holds the card, and the space's
    submit gate, until the card's own expiry.

    Driven through the handler on purpose. The emitter always forwarded an id it was given; this
    verb builds the emitter's event by hand and left the id out, and a test that handed the
    emitter a ready-made event could not see that.
    """
    _setup()
    sent = []
    v.notify.emit_notification = lambda user, text, **kw: sent.append((user, kw.get("payload")))

    with pytest.raises(TerminalError):
        v.handler(_event(**kwargs), None)

    assert sent == [("alice", {"requestId": "req-1"})], "the refusal cannot settle the card it answers"


@pytest.mark.parametrize("request_id", [None, 7], ids=["missing", "not-a-string"])
def test_a_request_with_no_usable_id_reaches_the_contracts_own_refusal_and_names_no_id(request_id):
    """The id is read before anything has checked it, so reading it must not be what fails: a
    subscript would turn the contract's refusal into an unexpected error and the actor would read
    the generic sentence. What the payload cannot use it drops, rather than forwarding it."""
    _setup()
    sent = []
    v.notify.emit_notification = lambda user, text, **kw: sent.append((user, kw.get("payload")))
    body = _body()
    if request_id is None:
        del body["requestId"]
    else:
        body["requestId"] = request_id

    with pytest.raises(TerminalError) as caught:
        v.handler([{"body": json.dumps(body)}], None)

    assert caught.value.reason == "malformed_event"
    assert sent == [("alice", None)]


def test_the_block_decides_the_actor_and_the_flat_field_beside_it_does_not():
    """The block wins, and the flat field must not — it can still hold a raw token.

    A message enqueued before the API stopped sending the token carries one there. This test used
    to assert that the block rides along and is ignored; it was inverted rather than deleted,
    because the property worth asserting is now the opposite one, and the flat field is still
    admitted by the allowlist, so a reader that preferred it would pass every other test here.
    """
    _setup()

    result = v.handler(_event(actor="alice", flat_actor=_JWT), None)

    assert result["operation"] == "copy"
    assert result["actor"] == {"username": "alice"}


def test_the_verb_refuses_a_message_with_no_identity_block():
    """Fail closed on the pre-cutover envelope: a flat token, and no block at all."""
    _setup()

    with pytest.raises(TerminalError) as raised:
        v.handler(_event(identity=False, flat_actor=_JWT), None)

    assert raised.value.reason == "unauthorized"
    assert "identity block" in raised.value.detail


@pytest.mark.parametrize("side", ["source", "destination"])
@pytest.mark.parametrize("kind", ["admin", "", None, 1, ["personal"]], ids=["unknown", "empty", "null", "int", "list"])
def test_the_space_kind_vocabulary_is_closed_on_both_sides(kind, side):
    """Every unknown kind must reach the plane's own refusal, an UNHASHABLE one included.

    A frozenset membership test hashes its left operand, so a request naming a list raised
    TypeError out of the check itself — reported as an unexpected fault, with this plane's
    named refusal never rendered.

    Driven from both sides deliberately. They share one ``_resolve``, so a source-only case
    would be named for a rule it half-covers — and this is the one plane that authorizes a
    destination independently, which is the whole reason that function takes a side.
    """
    _setup()
    space = {"kind": kind, "name": "alice"}
    event = (
        _event(space=space)
        if side == "source"
        else _event(destination={"space": space, "prefix": "alice/out/"})
    )

    with pytest.raises(TerminalError) as caught:
        v.handler(event, None)

    assert caught.value.reason == "forbidden"
    assert caught.value.detail == f"unknown {side} space kind {kind!r}"


def test_a_space_that_excludes_you_and_one_that_does_not_exist_read_the_same_sentence():
    """The anti-oracle rule this module names as its reason for existing, finally executed.

    The docstring said a test rendered both and compared; none did, and the whole shared-space
    branch ran in no test at all. Planting an existence oracle at the membership refusal left
    the suite green, which is what a documented guarantee with nothing behind it looks like.

    Three refusals, not two: another actor's personal space reaches a different branch again,
    and all three must be one sentence or the plane answers "is there a shared space called X?"
    for any name a caller cares to try.
    """
    excluded = _refusal(
        operation="delete",
        space={"kind": "shared", "name": "sales"},
        items=[{"kind": "file", "key": "sales/q1.csv"}],
        spaces={"sales": {"status": "active", "owner": "carol", "members": ["carol"]}},
    )
    absent = _refusal(
        operation="delete",
        space={"kind": "shared", "name": "ghost"},
        items=[{"kind": "file", "key": "ghost/q1.csv"}],
    )
    other = _refusal(
        operation="delete",
        space={"kind": "personal", "name": "bob"},
        items=[{"kind": "file", "key": "bob/q1.csv"}],
    )

    assert excluded.reason == absent.reason == other.reason == "forbidden"
    assert excluded.detail == absent.detail == other.detail


def test_a_shared_space_the_actor_belongs_to_resolves_to_the_SHARED_bucket():
    """The other half of the branch nothing executed: which bucket a shared source resolves in.

    Personal and shared are different buckets, so guessing wrong here reads one namespace at
    the other's address — and every existing case in this file named a personal space.
    """
    result = _run(
        operation="delete",
        space={"kind": "shared", "name": "sales"},
        items=[{"kind": "file", "key": "sales/q1.csv"}],
        spaces={"sales": {"status": "active", "owner": "carol", "members": ["alice", "carol"]}},
    )

    assert result["source"]["bucket"] == "shared-bkt"
    assert result["source"]["root"] == "sales/"


@pytest.mark.parametrize(
    ("kwargs", "reason", "detail"),
    [
        ({"operation": ["copy"]}, "invalid_operation", "unknown operation ['copy']"),
        ({"onConflict": ["refuse"]}, "invalid_conflict", "unknown conflict answer ['refuse']"),
        (
            {"items": [{"kind": ["file"], "key": "alice/q1.csv"}]},
            "invalid_items",
            "unknown item kind ['file']",
        ),
    ],
    ids=["operation", "on-conflict", "item-kind"],
)
def test_an_unhashable_vocabulary_field_reaches_this_plane_s_own_refusal(kwargs, reason, detail):
    """A list in any of the three HASHES on the way into its membership test, so before the type
    check each raised TypeError there — reported as an unexpected error, with the plane's own
    reason code never rendered onto the execution."""
    refusal = _refusal(**kwargs)

    assert refusal.reason == reason
    assert refusal.detail == detail
