"""What the API declares a caller may send, held against what each plane actually reads.

This is the guard no plane-side test can be: a plane's own suite drives envelopes the plane's own
test author wrote, so it cannot see the API refusing at the door a field the verb requires. That
failure is silent offline and total in production — every request of that shape refuses at the
plane, dead-letters, and the user is told their request could not be started.

Both directions are derived. The allowed-field planes publish a set, and it is compared against the
API's own declaration plus the three things the sender adds. The planes with no allowlist have their
read set extracted from their source by AST, and it must be a subset of the same. A hand-copied list
on either side would agree with itself.
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
    "shared-space": "shared-space-validate/validate.py",
    "table-builder": "table-builder-validate-authorize/validate_authorize.py",
    "table-share": "table-share-validate-authorize/table_share_validate_authorize.py",
    "data-quality": "data-quality-validate-authorize/dq_validate_authorize.py",
}

_TWO_PRODUCER_PLANES = {"notifications"}

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


def _declared_keys(queue_id):
    """Every top-level key a message on one queue may carry.

    The API's declared request fields, plus the three things the sender adds: the identity block,
    the token the plane still verifies, and whatever that route stamps for itself.

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
        keys |= {"identity", route.token_field}
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
                | {"identity", route.token_field}
                | set(route.stamped)
            )
            assert fields == expected, f"{queue_id}/{mode} disagrees with the API"
    else:
        assert allowed == declared, f"{queue_id} disagrees with the API"


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


def test_the_token_field_agrees_with_the_drain_and_notifications_is_not_a_row():
    """Three assertions, and deliberately not set equality.

    Plain set equality between the routes and the drain's table fails on notifications, and the
    repair a build session reaches for — adding the row — silently re-opens the circularity the
    drain's only delivery channel creates.
    """
    for key, source in dlq_drain.SOURCES.items():
        routes = _routes_for(key)
        assert routes, f"{key} is drained but no route writes it"
        assert {r.token_field for r in routes} == {source.token_field}, key

    for route in contract.ENQUEUE_ROUTES:
        assert (
            route.queue in dlq_drain.SOURCES
            or route.queue in dlq_drain.UNDRAINED_QUEUES
        ), f"{route.queue} is neither drained nor deliberately undrained"

    assert dlq_drain.UNDRAINED_QUEUES == _TWO_PRODUCER_PLANES


def test_the_token_is_still_being_sent_on_every_route():
    """A tripwire, not a requirement.

    It exists to fail if the plane-side half of the cutover is implemented here by mistake. The
    change that stops the token being sent deletes this test in the same commit — after the planes
    are already reading the identity block, never before.
    """
    from apicommon import enqueue as sender
    from apicommon.context import Redacted

    class _Ctx:
        """The two fields the message builder reads.

        Attributes:
          principal: A stand-in caller.
          bearer: A wrapped token that is not empty.
        """

        principal = type("P", (), {"username": "alice"})()
        bearer = Redacted("a-real-looking-token")

    assert {route.token_field for route in contract.ENQUEUE_ROUTES} == {
        "idToken",
        "actor",
    }
    for route in contract.ENQUEUE_ROUTES:
        message = sender.build_message(route, _Ctx(), {})
        assert isinstance(message.get(route.token_field), str), route.id
        assert message[route.token_field], f"{route.id} sends an empty token"


def test_no_verb_outside_the_api_reads_the_identity_block_yet():
    """ "Nothing on the plane side breaks" is only checkable while nothing depends on it."""
    readers = []
    for path in sorted(_ROOT.rglob("*.py")):
        if (
            "/api/" in str(path)
            or path.name.startswith("test_")
            or path.name == "conftest.py"
        ):
            continue
        if "identity" not in _keys_read_by(path.relative_to(_ROOT)):
            continue
        readers.append(str(path.relative_to(_ROOT)))

    assert readers == []
