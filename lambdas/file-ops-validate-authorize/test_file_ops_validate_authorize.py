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


def _refused(**kwargs):
    with pytest.raises(TerminalError) as caught:
        _run(**kwargs)
    return caught.value.reason


# ── The contract ─────────────────────────────────────────────────────────────


def test_a_valid_copy_is_accepted_and_resolves_both_sides():
    result = _run()

    assert result["actor"] == {"username": "alice"}
    assert result["operation"] == "copy"
    assert result["source"]["root"] == "alice/"
    assert result["destination"]["prefix"] == "alice/out/"
    assert result["outcomes"] == []


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
        "raw": "the failure seeds",
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


def test_the_block_decides_the_actor_and_the_flat_field_beside_it_does_not():
    """The block wins, and the flat field must not — it holds a raw token until the cutover.

    This was SPEC-200's "the block rides along and is ignored". Inverted rather than deleted:
    the property worth asserting is now the opposite one, and the flat field is still admitted
    by the allowlist, so a reader that preferred it would pass every other test in this file.
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
