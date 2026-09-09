"""One worst-case request per enqueue route, built once from the declared bounds.

Archive's, file-send's and file-ops' worst cases used to exist as three hand-built literals inside
three plane tests, and that is where the disagreement between them started: each modelled the parts
its own author was thinking about, so the three answers to "how big can this get" were three
different numbers and nobody owned the difference. The factory here is the one answer, built from
``apicommon.bounds`` — so a contract that grows a field fails to build its worst case rather than
silently shrinking it.

**The fill character is swept, not fixed, and an earlier draft of this file got that wrong.** The
claim it rested on was that a bound measured in serialized bytes makes link one independent of the
fill, so only the escape into the Pipe record could vary. That holds for the two planes whose caps
measure the same escaping the wire does. It does not hold for file-ops, whose cap measured
``ensure_ascii=False`` while the API sends ``ensure_ascii=True`` — a two-byte UTF-8 fill moved that
route's link one by nearly three times. So four fills are swept, each worst somewhere:

* ``k`` — the comfortable case, and the control that shows the others are not.
* ``"`` — the **escape-worst for the Pipe record**: two body bytes that become four in the record,
  a ratio of exactly 2.0, which nothing beats because ``json.dumps`` emits no raw control byte.
* ``\\x01`` — the escape-worst inside the body itself, six bytes a character.
* ``é`` — two UTF-8 bytes that the API escapes to six, which is the case no existing plane guard
  covered and the one that hid a live overshoot.

Attributes:
  FILLS: The characters every worst case is built from, in turn.
  ESCAPE_WORST_FILL: The one that maximises the Pipe record, pinned by a measurement below.
  PIPED_ROUTES: The enqueue routes whose messages traverse a Pipe and a state machine, derived
    from the Terraform rather than listed.
"""

import json
import os
import pathlib
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "api"))

from apicommon import bounds, contract
from apicommon.contract import TypeNode

REPO = pathlib.Path(_HERE).parent
MODULES = REPO / "infra" / "modules"

FILLS = ("k", '"', "\x01", "é")
ESCAPE_WORST_FILL = '"'


def _serialized(value: object) -> int:
    """The byte length of a value as ``enqueue.build_message`` puts it on the wire.

    Compact separators and ``ensure_ascii`` at its default, because that is what the sender does
    and a model that measured anything else would bound a quantity nothing produces.

    Args:
      value: Anything JSON-serialisable.

    Returns:
      The serialized byte length.

    Raises:
      None.
    """
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _queue_of(route_id: str) -> str:
    """The queue one enqueue route sends to.

    Args:
      route_id: The route's id.

    Returns:
      The queue's registry id.

    Raises:
      KeyError: If the id names no enqueue route.
    """
    return {route.id: route.queue for route in contract.ENQUEUE_ROUTES}[route_id]


def _stem(name: str) -> str:
    """One name for a plane, whether it was written as a queue id or a module directory.

    ``shared-space`` is the queue and ``shared-spaces`` the module, and the fleet already answers
    this question once in ``test_queue_writers`` — the same normalisation is used here rather than
    a mapping table, which would be a third place to get the pairing wrong.

    Args:
      name: A queue id or a module directory name.

    Returns:
      The stem both spellings agree on.

    Raises:
      None.
    """
    return name.replace("-", "_").rstrip("s")


def _piped_queues() -> frozenset[str]:
    """The queues a Pipe actually reads, from the Terraform that declares them.

    Derived rather than listed so ``notifications.enqueue`` is excluded by RULE — it drives a
    Lambda directly and has no Pipe — and a ninth pipe is included by the same rule the day it
    lands, without anyone remembering to widen a tuple here.

    Args:
      None.

    Returns:
      The queue ids whose messages traverse a Pipe.

    Raises:
      None.
    """
    modules = {_stem(path.parent.name) for path in MODULES.glob("*/pipe.tf")}
    return frozenset(
        route.queue for route in contract.ENQUEUE_ROUTES if _stem(route.queue) in modules
    )


PIPED_ROUTES = tuple(
    route for route in contract.ENQUEUE_ROUTES if route.queue in _piped_queues()
)


def _bound_bytes(route_id: str, path: str) -> int | None:
    """The byte bound covering one field, whichever side enforces it.

    A ``verb`` bound's number lives in the plane, so it is read from there. ``apicommon.bounds``
    deliberately does not import those modules — a plane's ``config`` raises at import on its own
    unset environment — and this file may, because the suite stands the layers up.

    Args:
      route_id: The enqueue route.
      path: The dotted field path.

    Returns:
      The bound in serialized bytes, or None when nothing covers the field.

    Raises:
      None.
    """
    bound = bounds.bound_for(route_id, path)
    if bound is None:
        return None
    if bound.max_bytes is not None:
        return bound.max_bytes
    module_path, _, constant = bound.owner.rpartition(".")
    value = getattr(__import__(module_path, fromlist=[constant]), constant)
    return value if isinstance(value, int) else None


def _filled(fill: str, budget: int) -> str:
    """The longest string of one character that serializes inside a budget.

    Args:
      fill: The character to repeat.
      budget: The serialized byte budget, quotes included.

    Returns:
      The string.

    Raises:
      None.
    """
    per_character = _serialized(fill) - 2
    return fill * max(1, (budget - 2) // per_character)


def _worst(node: TypeNode, route_id: str, path: str, fill: str) -> object:
    """The largest legal value for one node, at the bounds covering its path.

    Args:
      node: The normalised node to satisfy.
      route_id: The enqueue route being built for.
      path: The dotted path reaching this node.
      fill: The character every string is made of.

    Returns:
      A value the node accepts, at its bound.

    Raises:
      None.
    """
    if node.kind == "optional":
        return _worst(node.of[0], route_id, path, fill)
    if node.kind == "str":
        budget = _bound_bytes(route_id, path)
        return _filled(fill, budget) if budget else fill
    if node.kind == "literal":
        return max(node.literals, key=len)
    if node.kind == "int":
        return 2**53 - 1
    if node.kind == "float":
        return 1.5
    if node.kind == "bool":
        return True
    if node.kind == "none":
        return None
    if node.kind == "object":
        return {
            name: _worst(child, route_id, f"{path}.{name}" if path else name, fill)
            for name, child, _ in node.fields
        }
    element = _worst(node.of[0], route_id, f"{path}[]", fill)
    budget = _bound_bytes(route_id, path)
    if budget is None:
        return [element]
    items: list[object] = []
    while _serialized([*items, element]) <= budget:
        items.append(element)
    return items or [element]


def worst_case_body(route: contract.Route, fill: str) -> dict:
    """The largest body one route legally accepts, built from its declared bounds.

    Args:
      route: The enqueue route to build for.
      fill: The character every string is made of.

    Returns:
      The body, before the sender stamps its own fields onto it.

    Raises:
      None.
    """
    body = _worst(contract.walk(route.request), route.id, "", fill)
    assert isinstance(body, dict)
    return body


# ── The factory's own coverage, before anything is measured with it ──────────


def test_the_factory_builds_a_worst_case_for_every_enqueue_route():
    """Set equality against the derived tuple, not a count.

    A count is satisfied by a substitution — a route dropped and another added reads as unchanged —
    and ``ENQUEUE_ROUTES`` already derives itself from ``ROUTES``, so nothing here re-derives it.
    """
    built = {route.id for route in contract.ENQUEUE_ROUTES if worst_case_body(route, "k")}

    assert built == {route.id for route in contract.ENQUEUE_ROUTES}


def test_every_worst_case_is_a_request_the_route_actually_accepts():
    """A worst case the contract refuses bounds nothing.

    The whole point of the factory is that its output is LEGAL — the largest thing a caller can
    really send — so it is fed back through the route's own validator rather than assumed.
    """
    for route in contract.ENQUEUE_ROUTES:
        for fill in FILLS:
            body = worst_case_body(route, fill)

            assert contract.validate_request(route, body) is None, (
                f"{route.id}'s worst case at {fill!r} is not a request the contract accepts"
            )


def test_the_piped_subset_is_derived_from_the_pipes_terraform_declares():
    """Eight pipes, ten piped routes, one route excluded by rule.

    ``notifications.enqueue`` drives a Lambda directly, so links two and four do not apply to it.
    It is excluded because no ``pipe.tf`` names its queue, not because it is listed here.
    """
    assert len({path.parent.name for path in MODULES.glob("*/pipe.tf")}) == 8
    assert {route.id for route in contract.ENQUEUE_ROUTES} - {r.id for r in PIPED_ROUTES} == {
        "notifications.enqueue"
    }


def test_a_capped_plane_builds_its_worst_case_AT_its_own_cap():
    """Where a plane enforces a byte cap, the worst case is built at THAT, read from its config.

    A worst case built at the fleet cap instead would make the chain check ``X ≤ X`` on the three
    routes where a plane already refuses earlier.
    """
    from arcommon.config import ARCHIVE_MAX_ITEM_BYTES
    from focommon.config import FILE_OPS_MAX_SELECTION_BYTES
    from fscommon.config import SEND_MAX_ITEM_BYTES

    at_cap = {
        "archive.archive": ARCHIVE_MAX_ITEM_BYTES,
        "fileSend.enqueue": SEND_MAX_ITEM_BYTES,
        "fileOps.enqueue": FILE_OPS_MAX_SELECTION_BYTES,
    }

    for route_id, cap in at_cap.items():
        route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
        items = worst_case_body(route, "k")["source"]["items"]
        measured = _serialized(items)

        assert measured <= cap
        assert _serialized([*items, items[0]]) > cap, (
            f"{route_id}'s selection stops at {measured} of a {cap}-byte cap, so the worst case is "
            f"not at the cap and every measurement over it understates the real one"
        )


def test_a_route_with_no_plane_cap_builds_its_worst_case_at_the_FIELD_bounds():
    """The seven routes no plane cap covers, sized by their own fields.

    Built at the field bounds rather than at "the largest body the fleet cap admits", which would
    make the cap check that reads this ``X ≤ X`` on most of the fleet.
    """
    capped = {"archive.archive", "fileSend.enqueue", "fileOps.enqueue", "archive.restore"}
    uncapped = [r for r in contract.ENQUEUE_ROUTES if r.id not in capped]

    assert len(uncapped) == 7

    for route in uncapped:
        body = worst_case_body(route, "k")
        for path, _ in _string_paths(route):
            budget = _bound_bytes(route.id, path)
            value = _at(body, path)
            if budget is None or value is None:
                continue

            assert _serialized(value) > budget - 8, (
                f"{route.id}/{path} is built at {_serialized(value)} bytes against a {budget}-byte "
                f"bound — a field hard-coded small where its bound permits large is this factory's "
                f"blind spot, and every measurement built on it understates the real worst case"
            )


def test_the_escape_worst_fill_is_measured_rather_than_asserted():
    """WHICH character maximises the Pipe record, and by how much over the others.

    The record carries the body as an escaped JSON string, so what matters is not how big a
    character is in the body but how much it grows AGAIN on the way into the record. A quote costs
    two body bytes that become four; a control character costs six that become seven; an ordinary
    letter costs one that stays one. A factory filling with ``k`` would therefore build a record
    half the real worst case, and every link-two assertion over it would pass while saying nothing.
    """
    ratios = {}
    for fill in FILLS:
        body = json.dumps({"k": _filled(fill, 4096)}, separators=(",", ":"))
        ratios[fill] = _serialized(body) / len(body.encode("utf-8"))

    assert max(ratios, key=lambda fill: ratios[fill]) == ESCAPE_WORST_FILL
    assert ratios[ESCAPE_WORST_FILL] == pytest.approx(2.0, abs=0.01), (
        f"the escape-worst ratio measured {ratios[ESCAPE_WORST_FILL]}, not the 2.0 the model "
        f"reserves for it"
    )
    assert ratios["k"] == pytest.approx(1.0, abs=0.01)


def test_the_fills_disagree_about_which_is_worst_for_the_BODY():
    """Why four fills are swept rather than one, asserted rather than explained.

    The escape-worst fill for the RECORD is not the worst for the BODY: a control character and a
    two-byte UTF-8 character both cost six body bytes where a quote costs two and a letter costs
    one. A sweep that kept only the record's worst would stop measuring the body's.

    **``\\x01`` and ``é`` cost the same on the wire and are both kept anyway**, because they were
    measured differently one hop earlier: file-ops' selection cap used to count ``é`` as its two
    literal UTF-8 bytes while the API escaped it to six, and a selection built only from control
    characters would never have exposed that. One is the wire's worst case; the other is the
    regression fixture for the divergence, and they are not interchangeable.
    """
    body_cost = {fill: _serialized(fill) - 2 for fill in FILLS}

    assert body_cost["\x01"] == body_cost["é"] == 6
    assert body_cost["é"] > body_cost[ESCAPE_WORST_FILL] > body_cost["k"]
    assert len("é".encode()) == 2, (
        "the fixture for the measurement that diverged is no longer a two-byte character"
    )


def _string_paths(route: contract.Route) -> list[tuple[str, str]]:
    """Every declared string path on one route's request type.

    Args:
      route: The route whose request type to walk.

    Returns:
      The paths and their kinds.

    Raises:
      None.
    """
    found: list[tuple[str, str]] = []
    _collect(contract.walk(route.request), "", found)
    return [(path, kind) for path, kind in found if kind == "str"]


def _collect(node: TypeNode, prefix: str, found: list[tuple[str, str]]) -> None:
    """Collects every declared string and list path beneath one node.

    Args:
      node: The node to walk.
      prefix: The dotted path reaching it.
      found: The accumulator, appended to in place.

    Returns:
      None.

    Raises:
      None.
    """
    if node.kind in ("str", "list"):
        found.append((prefix, node.kind))
    if node.kind == "optional":
        _collect(node.of[0], prefix, found)
    elif node.kind == "list":
        _collect(node.of[0], f"{prefix}[]", found)
    elif node.kind == "object":
        for name, child, _ in node.fields:
            _collect(child, f"{prefix}.{name}" if prefix else name, found)


def _at(body: object, path: str) -> object:
    """The value one dotted path names, following the first element of any list.

    Args:
      body: The body to read.
      path: The dotted path, with ``[]`` for a list's element.

    Returns:
      The value, or None when the path is absent.

    Raises:
      None.
    """
    value: object = body
    for step in path.replace("[]", ".[]").split("."):
        if not step:
            continue
        if step == "[]":
            if not isinstance(value, list) or not value:
                return None
            value = value[0]
        elif isinstance(value, dict) and step in value:
            value = value[step]
        else:
            return None
    return value
