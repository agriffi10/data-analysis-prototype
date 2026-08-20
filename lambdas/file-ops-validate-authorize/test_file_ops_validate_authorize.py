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
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_validate_authorize as v
from cpcommon.errors import TerminalError
from focommon.config import FILE_OPS_MAX_ITEMS

SUBMITTED = "2020-01-01T00:00:00Z"


def _setup(actor="alice", spaces=None):
    """Stubs the boundary helpers: the verified actor and the known registry spaces."""
    v.auth.verified_username = lambda token, **kw: actor
    v.authz.reg.load = lambda name: (spaces or {}).get(name)
    v.notify.emit_notification = lambda *a, **kw: None


def _body(operation="copy", space=None, items=..., destination=..., **extra):
    body = {
        "requestId": "req-1",
        "actor": "tok",
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
    body.update(extra)
    return body


def _event(**kwargs):
    return [{"body": json.dumps(_body(**kwargs))}]


def _run(**kwargs):
    _setup(**{k: kwargs.pop(k) for k in ("actor", "spaces") if k in kwargs})
    return v._validate_and_authorize(_event(**kwargs))


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


def test_an_unknown_top_level_field_is_REJECTED_rather_than_ignored():
    """A field the producer thinks it is sending and this verb silently drops is a contract break
    that shows up as behaviour nobody asked for."""
    assert _refused(surprise="x") == "malformed_event"


@pytest.mark.parametrize("operation", ["shred", "", None, 3])
def test_an_operation_this_plane_does_not_serve_is_refused(operation):
    assert _refused(operation=operation) == "invalid_operation"


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


@pytest.mark.parametrize("field", ["destination", "onConflict", "submittedAt"])
def test_a_delete_carrying_a_copy_only_field_is_refused_rather_than_coerced(field):
    """A delete carrying an ``onConflict`` is a request whose author believed it would do
    something it cannot, and silently dropping the field would leave that belief intact."""
    body = _body(operation="delete")
    body[field] = "x" if field != "destination" else {"space": {}, "prefix": "p/"}

    _setup()
    with pytest.raises(TerminalError) as caught:
        v._validate_and_authorize([{"body": json.dumps(body)}])

    assert caught.value.reason == "unexpected_destination"


@pytest.mark.parametrize("conflict", ["", "OVERWRITE", None, True])
def test_a_missing_or_unrecognised_conflict_answer_is_refused(conflict):
    """Defaulting it would decide on the user's behalf what happens to a file they never saw."""
    assert _refused(onConflict=conflict) == "invalid_conflict"


@pytest.mark.parametrize(
    "value", ["", "not-a-time", "2020-01-01T00:00:00", "9999-01-01T00:00:00Z", None]
)
def test_a_submission_time_that_is_missing_naive_or_FUTURE_is_refused(value):
    """The future case is the one that matters: the plane only overwrites an object whose last
    modification precedes this instant, so a future timestamp makes every collision
    overwritable. It is the one field a caller could set to defeat a safety rule rather than
    merely to malform a request."""
    assert _refused(submittedAt=value) == "invalid_submitted_at"


# ── Authorization ────────────────────────────────────────────────────────────


def test_a_source_space_that_is_not_the_actors_is_refused():
    assert _refused(space={"kind": "personal", "name": "bob"}) == "forbidden"


def test_the_DESTINATION_is_authorized_independently():
    """Without this an actor could write into a space they may read nothing of."""
    reason = _refused(
        destination={"space": {"kind": "shared", "name": "secret"}, "prefix": "secret/x/"}
    )

    assert reason == "forbidden"


def test_a_destination_prefix_outside_its_own_space_is_refused():
    """Authorizing the SPACE is not the whole question. Without this a request naming a shared
    space the actor genuinely belongs to, with another member's prefix, would be a privileged
    cross-tenant write — the plane's own role doing what the browser's credentials never could.
    """
    reason = _refused(
        spaces={"sales": {"status": "active", "members": ["alice"]}},
        destination={"space": {"kind": "shared", "name": "sales"}, "prefix": "marketing/x/"},
    )

    assert reason == "forbidden"


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


def test_a_repeat_of_ONE_item_is_not_a_collision():
    """The normalised selection can carry the same key twice; that lands on itself, which is a
    no-op rather than a lost file."""
    result = _run(
        items=[{"kind": "file", "key": "alice/x.csv"}, {"kind": "file", "key": "alice/x.csv"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/c/"},
    )

    assert result["outcomes"] == []


# ── Per-item outcomes: the rest of the selection proceeds ────────────────────


def test_a_protected_folder_fails_ALONE_and_the_others_proceed():
    """Matching the browser: a select-all delete at a space root deletes what it may and reports
    the folders it may not. A whole-request refusal would delete nothing."""
    result = _run(
        operation="delete",
        items=[
            {"kind": "folder", "key": "alice/saved_queries/"},
            {"kind": "folder", "key": "alice/reports/"},
        ],
    )

    assert [o["outcome"] for o in result["outcomes"]] == ["protected"]
    assert result["outcomes"][0]["itemKey"] == "alice/saved_queries/"
    assert result["outcomes"][0]["reason"] == "source_folder_undeletable"


def test_the_same_key_is_a_NOOP_rather_than_an_error():
    """Matching the browser, which treats a move onto itself as doing nothing rather than as a
    failure."""
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/reports/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["outcomes"][0]["outcome"] == "noop"


def test_a_folder_moved_INTO_ITSELF_is_refused_per_item():
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/reports/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/reports/sub/"},
    )

    assert result["outcomes"][0]["outcome"] == "refused"
    assert result["outcomes"][0]["reason"] == "destination_inside_source"


def test_the_same_key_rule_is_decided_BEFORE_the_into_itself_rule():
    """The order is the rule. The subtree comparison matches the equal case too, so checking it
    first would turn a rename-to-the-same-name into an error rather than a no-op."""
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/reports/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["outcomes"][0]["outcome"] == "noop"


def test_a_CROSS_BUCKET_copy_is_not_reported_as_a_no_op():
    """The guard a mutation test found unprotected, and the scenario is reachable: nothing stops a
    shared space being named ``alice`` while a user is also called ``alice`` — the two live in
    separate namespaces under the same identifier rule.

    Source ``alice/`` in the user-space bucket, destination ``alice/`` in the shared-space bucket:
    every derived key equals its source key as a STRING, so without the same-bucket guard the whole
    copy reports ``noop`` and nothing is copied, silently.
    """
    result = _run(
        spaces={"alice": {"status": "active", "members": ["alice"]}},
        items=[{"kind": "file", "key": "alice/q1.csv"}],
        destination={"space": {"kind": "shared", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["outcomes"] == []
    assert result["source"]["bucket"] != result["destination"]["bucket"]


def test_a_CROSS_BUCKET_folder_is_not_reported_as_inside_itself():
    """The same string coincidence, on the other pairing rule."""
    result = _run(
        spaces={"alice": {"status": "active", "members": ["alice"]}},
        items=[{"kind": "folder", "key": "alice/reports/"}],
        destination={"space": {"kind": "shared", "name": "alice"}, "prefix": "alice/reports/sub/"},
    )

    assert result["outcomes"] == []


def test_the_SPACE_ROOT_is_refused_as_an_item():
    """The third way to select a protected folder, and the one no rule looks for.

    Every protected-location rule matches the named folder or something below it; none looks UP.
    A single item of ``alice/`` passes all of them while naming a subtree containing
    ``athenaresults/``, ``user_settings/``, ``archive/`` and every marker — a request this plane's
    own IAM refuses part-way through. The browser cannot express it, so refusing costs nothing.
    """
    assert _refused(operation="delete", items=[{"kind": "folder", "key": "alice/"}]) == "space_root_not_an_item"


def test_a_PROTECTED_source_is_reported_as_protected_rather_than_as_a_no_op():
    """The ordering the docstring now describes. ``move alice/archive/ -> alice/`` derives its own
    key, so a pairing-first order would answer "nothing happened" to a request the plane actually
    refuses — and two protected folders would answer the same request differently depending on
    which list they were on."""
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/archive/"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["outcomes"][0]["outcome"] == "protected"
    assert result["outcomes"][0]["reason"] == "source_folder_undeletable"


def test_a_destination_the_pickers_own_rules_forbid_is_refused():
    """The verb's WIRING of the destination rule, which the rule's own tests cannot cover."""
    reason = _refused(
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/shared_tables/"}
    )

    assert reason == "destination_folder_locked"


def test_a_folder_key_without_its_trailing_slash_is_normalised():
    """Load-bearing for every rule below it: an unslashed folder key would compare as a file and
    match a prefix rule it should not."""
    result = _run(
        operation="move",
        items=[{"kind": "folder", "key": "alice/reports"}],
        destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "alice/"},
    )

    assert result["source"]["items"][0]["key"] == "alice/reports/"
    assert result["outcomes"][0]["outcome"] == "noop"


def test_a_request_with_no_usable_id_is_refused():
    assert _refused(requestId="") == "malformed_event"


def test_a_copy_with_a_malformed_destination_is_refused():
    assert _refused(destination={"space": {"kind": "personal", "name": "alice"}}) == "invalid_destination"


def test_a_marker_file_is_refused_per_item_for_a_COPY_too():
    """The one place a copy is not free on this plane: copying a marker mints a new permanently
    undeletable object, because both bucket policies deny the basename at any depth."""
    result = _run(items=[{"kind": "file", "key": "alice/DO_NOT_DELETE.txt"}])

    assert result["outcomes"][0]["reason"] == "marker_not_deletable"


def test_copying_out_of_a_protected_folder_is_NOT_refused():
    """Picker-locked and undeletable, and copyable in the browser today. Refusing it here would
    silently remove a working capability."""
    result = _run(items=[{"kind": "file", "key": "alice/athenaresults/r.csv"}])

    assert result["outcomes"] == []


# ── Caps ─────────────────────────────────────────────────────────────────────


def test_too_many_items_is_refused_before_the_per_item_loop():
    items = [{"kind": "file", "key": f"alice/{n}.csv"} for n in range(FILE_OPS_MAX_ITEMS + 1)]

    assert _refused(items=items) == "too_many_items"


def test_a_selection_over_the_byte_cap_is_refused():
    """The count cannot stand in for this: S3 keys are arbitrary UTF-8 and JSON escaping expands
    a control character to six bytes, so a selection well inside the item cap can be several
    times the payload limit."""
    items = [{"kind": "file", "key": "alice/" + ("k" * 1000) + f"{n}"} for n in range(100)]

    assert _refused(items=items) == "selection_too_large"


@pytest.mark.parametrize("items", [None, [], "not-a-list", [{}], [{"kind": "dir", "key": "a"}]])
def test_a_malformed_selection_is_refused(items):
    assert _refused(items=items) in ("no_items", "invalid_items")


def test_an_unusable_target_name_is_refused_at_the_request():
    """The sharpest hole on this plane: an empty name derives to the destination prefix itself,
    which merges a folder's contents into the destination and then, for a move, deletes the
    source."""
    reason = _refused(items=[{"kind": "folder", "key": "alice/reports/", "targetName": ""}])

    assert reason == "invalid_target_name"


# ── The actor ────────────────────────────────────────────────────────────────


def test_nothing_from_the_untrusted_body_identifies_the_caller():
    """The body's own assertion about who sent it is worth nothing; the token is the only source."""
    _setup(actor="alice")
    body = _body()
    body["source"]["space"] = {"kind": "personal", "name": "mallory"}

    with pytest.raises(TerminalError) as caught:
        v._validate_and_authorize([{"body": json.dumps(body)}])

    assert caught.value.reason == "forbidden"


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
    produced = set(_run().keys()) | {"lock", "error", "execution", "raw"}

    assert read <= produced, f"the machine reads {sorted(read - produced)}, which this verb never emits"


def test_a_delete_supplies_those_paths_too():
    """The operation whose request carries three fewer fields. The machine no longer reads them,
    but the state has to stay one shape for the verbs that will."""
    result = _run(operation="delete")

    assert set(result) == set(_run().keys())
