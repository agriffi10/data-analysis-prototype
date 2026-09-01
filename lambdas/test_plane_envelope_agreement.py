"""What the API declares a caller may send, held against what each plane actually reads.

This is the guard no plane-side test can be: a plane's own suite drives envelopes the plane's own
test author wrote, so it cannot see the API refusing at the door a field the verb requires. That
failure is silent offline and total in production — every request of that shape refuses at the
plane, dead-letters, and the user is told their request could not be started.

Both directions are derived. The allowed-field planes publish a set, and it is compared against the
API's own declaration plus the two things the sender adds. The planes with no allowlist have their
read set extracted from their source by AST, and it must be a subset of the same. A hand-copied list
on either side would agree with itself.

The one exception is at the bottom of the file, and it is deliberate: which plane still admits its
old token field is history the contract no longer carries, so there is nothing to derive it from.
"""

import ast
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT / "api"))

from apicommon import contract

_DRAIN = _ROOT / "control-plane-dlq-drain"
sys.path.insert(0, str(_DRAIN))

import dlq_drain

_ALLOWLIST_PLANES = {
    "file-send": (
        "file-send-validate-authorize/file_send_validate_authorize.py",
        "_ALLOWED_FIELDS",
    ),
    "archive": (
        "archive-validate-authorize/archive_validate_authorize.py",
        "_ALLOWED_FIELDS",
    ),
    "file-ops": (
        "file-ops-validate-authorize/file_ops_validate_authorize.py",
        "_ALLOWED_FIELDS",
    ),
}

_NO_ALLOWLIST_VERBS = {
    "table-builder": "table-builder-validate-authorize/validate_authorize.py",
    "table-share": "table-share-validate-authorize/table_share_validate_authorize.py",
    "data-quality": "data-quality-validate-authorize/dq_validate_authorize.py",
}

#: Every DLQ the drain deliberately does not attach to, and WHY each one. A mapping rather than a
#: set, because the repair this guard invites is to widen a set named for one reason until it
#: holds queues that are there for another — and then the constant's name is a lie and the
#: assertion is a transcription of the production value rather than a check on it.
_UNDRAINED_BY_DESIGN = {
    "notifications": "the drain's only delivery channel IS this queue, so draining it is circular",
    "feedback": (
        "the drain notifies from the verified identity in the message body, and a feedback "
        "message carries none by design — draining it would notify from an untrusted field"
    ),
}

#: The shared-space validator, which cannot be a plain subset of the API's declaration because the
#: API is no longer its only producer. Held out by NAME, with the property that makes the exemption
#: safe asserted below rather than achieved by leaving a row out of a table.
_SHARED_SPACE_VERB = "shared-space-validate/validate.py"

#: The fields the shared-space plane reads that the API cannot send. Exactly one, and the count is
#: the guard: an exemption that grows silently is a hole, so this is set equality rather than a
#: subset test.
_OPERATOR_ONLY_FIELDS = frozenset({"origin"})

_NOTIFICATIONS_USER_ACTIONS = frozenset({"markRead", "markAllRead"})


def _routes_for(queue_id):
    """The enqueue routes that write one queue.

    Args:
      queue_id: The queue's registry id.

    Returns:
      The routes naming it.

    Raises:
      None.
    """
    return [route for route in contract.ENQUEUE_ROUTES if route.queue == queue_id]


#: The two field names the API used to forward a raw token in. It sends neither now and no plane
#: reads either — but a plane's allowed-field set may still ADMIT its own one, and that tolerance
#: is the point rather than an oversight: tightening the set turns a message enqueued before the
#: cutover into `malformed_event` instead of the `unauthorized` refusal that path is meant to
#: produce, which is a different reason code and a different notification decision.
#:
#: Tolerated, never required, and never enumerated per plane. Which planes still carry which field
#: is a fact about history that no longer lives in the contract, so asserting it would mean a
#: hand-maintained map — and the property actually wanted is weaker and checkable: everything the
#: API sends must be admitted, nothing else may be, and a leftover legacy name does not count as
#: "anything else".
LEGACY_ADMITTED = frozenset({"idToken", "actor"})


def _agrees(allowed, expected, label):
    """Asserts a plane admits everything the API sends and nothing but leftover legacy names.

    Args:
      allowed: The plane's own allowed-field set.
      expected: What the API can put on the wire for it.
      label: The plane (and mode) being checked, for the failure message.

    Returns:
      None.

    Raises:
      AssertionError: If the plane refuses a field the API sends, or admits an unrelated one.
    """
    assert expected <= allowed, (
        f"{label} REFUSES {sorted(expected - allowed)}, which the API sends — every request "
        "on this plane becomes a malformed_event"
    )
    assert allowed - expected <= LEGACY_ADMITTED, (
        f"{label} admits {sorted(allowed - expected - LEGACY_ADMITTED)}, which the API never "
        "sends — an admitted field with no producer is a contract nobody checks"
    )


def _declared_keys(queue_id):
    """Every top-level key a message on one queue may carry.

    The API's declared request fields, plus the two things the sender adds: the identity block, and
    whatever that route stamps for itself. It used to be three — the token a plane verified was the
    third, and there is no longer one.

    Args:
      queue_id: The queue's registry id.

    Returns:
      The union over every route writing that queue.

    Raises:
      None.
    """
    keys = set()
    for route in _routes_for(queue_id):
        node = contract.walk(route.request)
        keys |= {name for name, _node, _required in node.fields}
        keys |= {"identity"}
        keys |= set(route.stamped)
    return keys


def _module_constant(relative_path, name):
    """Reads one frozenset constant out of a verb's source, without importing the verb.

    Importing would pull in the verb's own layer and its module-scope clients, which is a lot of
    machinery to read one literal — and it would make this sweep fail for reasons that have nothing
    to do with what it asserts.

    Args:
      relative_path: The verb module, relative to this directory.
      name: The constant's name.

    Returns:
      The value, as a set of strings for a flat set, or a dict of sets for a per-mode dict.

    Raises:
      AssertionError: If the constant is not found.
    """
    tree = ast.parse((_ROOT / relative_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return _literal_sets(node.value, relative_path)
    raise AssertionError(f"{name} not found in {relative_path}")


def _literal_sets(node, relative_path):
    """Turns a frozenset literal, or a dict of them, into plain Python.

    Args:
      node: The assigned expression.
      relative_path: The module, for the message when a value is not literal.

    Returns:
      A set of strings, or a mapping of mode to set.

    Raises:
      AssertionError: If a value is neither, which means this sweep has stopped seeing the truth.
    """
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "frozenset":
        return {element.value for element in node.args[0].elts}
    if isinstance(node, ast.Dict):
        modes = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(value, ast.Attribute):
                modes[key.value] = set(dlq_import_restore_fields())
            else:
                modes[key.value] = _literal_sets(value, relative_path)
        return modes
    raise AssertionError(
        f"{relative_path} no longer declares a literal set this sweep can read"
    )


def dlq_import_restore_fields():
    """The restore mode's allowed fields, which live in the archive layer rather than the verb.

    Args:
      None.

    Returns:
      The field names.

    Raises:
      AssertionError: If the constant is not found.
    """
    return _module_constant("archive-common/arcommon/restore.py", "ALLOWED_FIELDS")


def _keys_read_by(relative_path):
    """Every top-level request key a verb reads, extracted from its source.

    Args:
      relative_path: The verb module, relative to this directory.

    Scoped to the request variable by NAME rather than to every mapping access in the module. A
    verb reads AWS responses, its own configuration and its own intermediate dicts with the same
    syntax, and a sweep that counted those would be answered by widening an ignore list until it
    asserted nothing.

    Args are read from ``req``/``event``/``request`` receivers only, which is what those verbs
    call the message.

    Returns:
      The top-level message keys the module reads.

    Raises:
      None.
    """
    tree = ast.parse((_ROOT / relative_path).read_text())
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            receiver = getattr(node.func, "value", None)
            attr = getattr(node.func, "attr", "")
            if attr == "get" and getattr(receiver, "id", "") in _REQUEST_NAMES:
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        read.add(arg.value)
            if (
                attr == "require"
                and node.args
                and getattr(node.args[0], "id", "") in _REQUEST_NAMES
            ):
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        read.add(arg.value)
        if (
            isinstance(node, ast.Subscript)
            and getattr(node.value, "id", "") in _REQUEST_NAMES
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            read.add(node.slice.value)
    return read


_REQUEST_NAMES = frozenset({"req", "event", "request"})


@pytest.mark.parametrize(
    "queue_id", sorted(_ALLOWLIST_PLANES), ids=sorted(_ALLOWLIST_PLANES)
)
def test_an_allowlist_plane_admits_exactly_what_the_api_may_send(queue_id):
    """A plane that refuses unknown top-level fields must admit every field the sender adds."""
    relative_path, name = _ALLOWLIST_PLANES[queue_id]
    allowed = _module_constant(relative_path, name)
    declared = _declared_keys(queue_id)

    if isinstance(allowed, dict):
        for mode, fields in allowed.items():
            route = next(r for r in _routes_for(queue_id) if r.id.endswith(mode))
            expected = (
                {name for name, _n, _r in contract.walk(route.request).fields}
                | {"identity"}
                | set(route.stamped)
            )
            _agrees(fields, expected, f"{queue_id}/{mode}")
    else:
        _agrees(allowed, declared, queue_id)


@pytest.mark.parametrize(
    "queue_id", sorted(_NO_ALLOWLIST_VERBS), ids=sorted(_NO_ALLOWLIST_VERBS)
)
def test_a_plane_without_an_allowlist_reads_nothing_the_api_refuses_at_the_door(
    queue_id,
):
    """The failure no plane-side test can see: the API refusing a field the verb requires."""
    read = _keys_read_by(_NO_ALLOWLIST_VERBS[queue_id])
    declared = _declared_keys(queue_id)

    assert read <= declared, (
        f"{queue_id} reads {sorted(read - declared)}, which the API will refuse at the door"
    )


def test_the_notifications_verb_is_exempt_from_the_subset_by_NAME_and_here_is_why():
    """Exempted deliberately, because the alternative repair hands a caller a forged create.

    The writer serves TWO producers: the browser's user actions, which come through this API, and
    the ``create`` arm, written by the seven execution roles that notify. Its read set is the union
    of both, so it can never be a subset of one producer's declared fields. The repair a build
    session reaches for — adding ``username``, ``message``, ``link`` and ``payload`` to the API's
    request type — would let any signed-in caller post a notification into anyone's inbox, and the
    boundary that refuses a forged create compares the sender's ROLE, which this API legitimately
    has.

    So the exemption is asserted rather than achieved by leaving a row out of a table, and what is
    asserted is the shape that makes it true: the API declares only the user-action arm.
    """
    assert "notifications" not in _NO_ALLOWLIST_VERBS
    route = next(r for r in contract.ENQUEUE_ROUTES if r.queue == "notifications")
    action = next(
        node
        for name, node, _r in contract.walk(route.request).fields
        if name == "action"
    )

    assert set(action.literals) == _NOTIFICATIONS_USER_ACTIONS
    assert "create" not in action.literals


def test_every_drained_queue_has_a_writer_and_the_undrained_ones_say_why():
    """Three assertions, and deliberately not set equality.

    Plain set equality between the routes and the drain's table fails on notifications, and the
    repair a build session reaches for — adding the row — silently re-opens the circularity the
    drain's only delivery channel creates.

    This used to also cross-check each domain's TOKEN FIELD against the drain's per-source
    column. That column is gone: the recipient comes from the one ``identity`` block every
    producer writes, so there is no per-domain disagreement left to keep the two tables honest
    about. What remains is the pairing that still has teeth — a drained queue nobody writes, a
    written queue nobody drains, and the deliberate exclusions.

    This walks the enqueue ROUTES, so it is blind to a queue that has no enqueue route — feedback
    is the first. That one is covered by ``test_feedback_module.py``, which walks what Terraform
    declares instead. Two populations, because neither alone is "every request DLQ".
    """
    for key in dlq_drain.SOURCES:
        assert _routes_for(key), f"{key} is drained but no route writes it"

    for route in contract.ENQUEUE_ROUTES:
        assert (
            route.queue in dlq_drain.SOURCES
            or route.queue in dlq_drain.UNDRAINED_QUEUES
        ), f"{route.queue} is neither drained nor deliberately undrained"

    assert set(_UNDRAINED_BY_DESIGN) == dlq_drain.UNDRAINED_QUEUES, (
        "a queue was added to or removed from UNDRAINED_QUEUES without a reason being written "
        f"down beside it: {sorted(dlq_drain.UNDRAINED_QUEUES ^ set(_UNDRAINED_BY_DESIGN))}"
    )
    # Key equality alone lets a queue be added to BOTH tables with an empty reason, which is the
    # repair this guard exists to refuse — the reason is the content, not the membership.
    empty = [queue for queue, reason in _UNDRAINED_BY_DESIGN.items() if not reason.strip()]
    assert empty == [], f"undrained with no reason given: {empty}"
    both = set(_UNDRAINED_BY_DESIGN) & set(dlq_drain.SOURCES)
    assert both == set(), (
        f"{sorted(both)} is drained AND named as deliberately undrained; the tables disagree and "
        "the drain follows SOURCES"
    )


#: What each allowlist plane admitted the day the API stopped sending a token, per mode where a
#: plane has two. A LITERAL, deliberately, and the only hand-maintained list in this file.
#:
#: The tolerance in ``_agrees`` says a leftover legacy name is permitted; FR-006 needs the stronger
#: statement that it is still THERE. Measured rather than derived, because the fact it pins —
#: which plane kept which field — is history the contract no longer carries, so there is nothing
#: left to derive it from. Rotting is the usual objection to a list like this and does not apply:
#: it is pinned to a moment that has passed, and the next spec to touch these sets is meant to
#: read this line and decide, which is exactly what a hand-maintained list is good at.
LEGACY_ADMITTED_TODAY = {
    "file-send": {"actor"},
    "file-ops": {"actor"},
    "archive": {"actor"},
}


@pytest.mark.parametrize("queue_id", sorted(_ALLOWLIST_PLANES), ids=sorted(_ALLOWLIST_PLANES))
def test_no_plane_tightened_its_allowed_fields_when_the_token_stopped_being_sent(queue_id):
    """The legacy field is still admitted, per plane, not merely permitted to be.

    A message enqueued before the cutover carries a flat token and no identity block. It must be
    refused as ``unauthorized`` by the actor reader — not as ``malformed_event`` by the
    allowed-field check, which happens FIRST and would produce a different reason code, a
    different notification decision, and a live criterion that silently stopped testing what it
    names.

    Asserted per plane because the fleet-level version of this was breakable: tightening one of
    the three left the whole file green, since ``_agrees`` only ever tolerated the field and the
    non-vacuity guard was satisfied by the other two.

    Args:
      queue_id: The allowlist plane being checked.

    Returns:
      None.

    Raises:
      AssertionError: If a plane stopped admitting the field its old envelope used.
    """
    relative_path, name = _ALLOWLIST_PLANES[queue_id]
    allowed = _module_constant(relative_path, name)
    sets = list(allowed.values()) if isinstance(allowed, dict) else [allowed]
    expected = LEGACY_ADMITTED_TODAY[queue_id]

    assert expected <= LEGACY_ADMITTED, f"{queue_id}: the pin names a non-legacy field"
    for fields in sets:
        assert expected <= fields, (
            f"{queue_id} no longer admits {sorted(expected - fields)} — a message enqueued "
            "before the cutover is now malformed_event rather than the unauthorized refusal "
            "that path is meant to produce"
        )


def test_every_allowlist_plane_is_pinned():
    """Guard the guard: a plane missing from the pin above is a plane nothing checks.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the pin and the plane map disagree.
    """
    assert set(LEGACY_ADMITTED_TODAY) == set(_ALLOWLIST_PLANES)


def test_the_shared_space_verb_is_exempt_by_NAME_and_here_is_why():
    """A second producer, and declaring its field on the API would hand the browser the door.

    This plane now takes requests from two places. The API is one, and everything it may send is
    declared. The other is the scheduled reader that turns an operator's CSV of ownership
    transfers into requests, and it marks its messages with a top-level ``origin`` the API has no
    way to produce.

    So the verb's read set can never be a subset of one producer's declared fields, exactly as the
    notifications writer's cannot. And the repair a build session reaches for — adding ``origin``
    to ``SharedSpaceEnqueueRequest`` so the subset test passes — would be the worst available
    outcome: the API refuses an undeclared body key, which is the ONLY reason a signed-in caller
    cannot post ``origin: operator`` today, and declaring it would delete that property to satisfy
    a test. The runtime ``SenderId`` comparison would then be the sole fence rather than the second
    one.

    What is asserted instead is the shape that makes the exemption safe:

    1. the plane reads EXACTLY one field the API cannot send, so the hole cannot widen unnoticed;
    2. that field is undeclarable through the API, so the browser cannot put it on the wire;
    3. everything else it reads is still a subset of what the API sends, which is the original
       property, unweakened.
    """
    read = _keys_read_by(_SHARED_SPACE_VERB)
    declared = _declared_keys("shared-space")

    assert read - declared == set(_OPERATOR_ONLY_FIELDS), (
        f"shared-space reads {sorted(read - declared)} that the API cannot send; the exemption "
        f"covers {sorted(_OPERATOR_ONLY_FIELDS)} and nothing else. A new one is a new producer, "
        "or a field the API should have declared."
    )
    assert _OPERATOR_ONLY_FIELDS.isdisjoint(declared), (
        f"{sorted(_OPERATOR_ONLY_FIELDS & declared)} is declared on the API's shared-space "
        "request, so a signed-in caller can now put it on the wire. The operator origin is "
        "trusted on the strength of the SenderId alone once that is true."
    )
    assert read - _OPERATOR_ONLY_FIELDS <= declared, (
        "shared-space reads something the API refuses at the door that is not the operator field"
    )
