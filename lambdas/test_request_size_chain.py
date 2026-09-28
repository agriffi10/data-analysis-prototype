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
import re
import shutil
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "api"))

from apicommon import bounds, contract, enqueue
from apicommon.contract import TypeNode
from cpcommon import config as cp_config
from cpcommon import errors as cp_errors

sys.path.insert(0, os.path.join(_HERE, "api"))
import test_bounds as _bounds_guard

REPO = pathlib.Path(_HERE).parent
MODULES = REPO / "infra" / "modules"

FILLS = ("k", '"', "\\", "\x01", "é")

#: A ceiling on how many elements a worst case will model. Not a bound on the product — it is a
#: circuit breaker: an unbounded list loop turned a raised byte bound into a hang, which reads as
#: an infrastructure fault rather than as the failing assertion it is.
_MAX_MODELLED_ITEMS = 5_000
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


#: What to build a field at when the plane bounds it with something that is not a number. A
#: regex has no length to read, and returning nothing made the factory fall back to a single
#: character — so `tableName` was modelled at 3 bytes where its own rule permits 65, in every
#: worst case on three routes. The model is the length the rule admits, and `_budget` refuses an
#: owner that is in neither this table nor an integer rather than shrinking silently.
NON_NUMERIC_OWNERS = {
    "cpcommon.config.CATALOG_IDENTIFIER_RE": bounds.MAX_IDENTIFIER_BYTES,
}


def _budget(route_id: str, path: str) -> tuple[int, str] | None:
    """The bound covering one field, with the unit its number is in.

    **The unit is returned rather than assumed, and an earlier draft assumed.** It read every
    owner constant as a byte budget, so ``SHARE_MAX_RECIPIENTS = 50`` — a COUNT — was spent as
    fifty bytes: one recipient serializes to about a hundred and fifty, so the list loop exited
    immediately and the worst case carried a single recipient. file-send's was understated by
    7,497 bytes and table-share's by sixteen times, in the model the fleet cap is derived from.

    A ``verb`` bound's number lives in the plane, so it is read from there. ``apicommon.bounds``
    deliberately does not import those modules — the API does not depend on the plane layers — and
    this file may, because a guard is not the service.

    Args:
      route_id: The enqueue route.
      path: The dotted field path.

    Returns:
      The number and its unit, or None when nothing covers the field.

    Raises:
      None.
    """
    bound = bounds.bound_for(route_id, path)
    if bound is None:
        return None
    if bound.max_bytes is not None:
        return bound.max_bytes, bound.measured
    module_path, _, constant = bound.owner.rpartition(".")
    value = getattr(__import__(module_path, fromlist=[constant]), constant)
    if isinstance(value, int):
        return value, bound.measured
    modelled = NON_NUMERIC_OWNERS.get(bound.owner)

    assert modelled is not None, (
        f"{bound.owner} is not a number and this file has no model for it, so every worst case "
        f"built for {route_id}/{path} would silently carry one character"
    )
    return modelled, bound.measured


def _filled(fill: str, budget: int, measured: str = "wire") -> str:
    """The longest string of one character that fits a budget, in that budget's own unit.

    Args:
      fill: The character to repeat.
      budget: The number the bound declares.
      measured: Its unit — ``wire`` for serialized bytes, ``value`` for the string's own UTF-8
        bytes, which is how S3 states a key length.

    Returns:
      The string.

    Raises:
      None.
    """
    if measured == "value":
        return fill * max(1, budget // len(fill.encode("utf-8")))
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
        budget = _budget(route_id, path)
        return _filled(fill, budget[0], budget[1]) if budget else fill
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
    budget = _budget(route_id, path)
    if budget is None:
        return [element]
    number, measured = budget
    if measured == "items":
        assert number < _MAX_MODELLED_ITEMS, (
            f"{route_id}/{path} admits {number} elements, which is a count bound that is not "
            f"bounding — and building it would spend gigabytes before any assertion could fail"
        )
        return [element] * number
    items: list[object] = []
    while _serialized([*items, element]) <= number and len(items) < _MAX_MODELLED_ITEMS:
        items.append(element)

    assert len(items) < _MAX_MODELLED_ITEMS, (
        f"{route_id}/{path} admits at least {_MAX_MODELLED_ITEMS} elements at its bound of "
        f"{number} — which is a bound that is not bounding, and without this the loop runs until "
        f"the suite is killed rather than failing"
    )
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
    #: The routes whose SELECTION a plane caps. ``archive.restore`` sat here once and does not
    #: belong: archive is a plane with a cap, but a restore carries no selection to cap — so the
    #: one route that most needs the blind-spot check below was the one excluded from it.
    capped = {"archive.archive", "fileSend.enqueue", "fileOps.enqueue"}
    uncapped = [r for r in contract.ENQUEUE_ROUTES if r.id not in capped]

    assert len(uncapped) == 8

    for route in uncapped:
        body = worst_case_body(route, "k")
        for path, _ in _string_paths(route):
            budget = _budget(route.id, path)
            value = _at(body, path)
            if budget is None or value is None:
                continue
            number, measured = budget
            built = len(value.encode("utf-8")) if measured == "value" else _serialized(value)

            assert built == number, (
                f"{route.id}/{path} is built at {built} against a bound of {number} ({measured}) — "
                f"a field hard-coded small where its bound permits large is this factory's blind "
                f"spot, and every measurement built on it understates the real worst case"
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

    The walk lives in ``test_bounds`` and is imported rather than copied: the two files ask the
    same question of the same contract, and two byte-identical walkers with nothing holding them
    equal is how one comes to see a shape the other does not.

    Args:
      node: The node to walk.
      prefix: The dotted path reaching it.
      found: The accumulator, appended to in place.

    Returns:
      None.

    Raises:
      None.
    """
    _bounds_guard._paths(node, prefix, found)


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


# ── The chain: links one, two and four, over every piped route ───────────────

#: How the value behind one ``RecordFailure`` key gets there. Six kinds, and the last three are
#: what an earlier draft of this table was missing: it declared only stamped literals, identity
#: fields and bounded contract fields, which parsed against the eight real templates is not total.
#: `envelope` is the forwarded batch, whose size IS link two and is summed as that rather than
#: twice. `derived` is a value a verb builds, which carries a bound of its own sized from the
#: bounded inputs it is built from. `error` is the Cause reservation.
ORIGIN_KINDS = ("stamped", "identity", "contract", "envelope", "derived", "error")

UNRESOLVED_MESSAGE = "resolves to no declared origin"

#: Every key of every plane's ``RecordFailure``, its origin kind, and the bytes it may cost the
#: state. A key with no entry fails the guard below naming its plane, so a plane that starts
#: carrying something new is caught rather than silently widening the failure state.
RECORD_FAILURE_ORIGINS = {
    "traceparent": ("stamped", 64),
    "execution": ("stamped", 128),
    "status": ("stamped", 16),
    "mode": ("stamped", 16),
    "action": ("contract", bounds.MAX_IDENTIFIER_BYTES),
    "format": ("contract", 16),
    "requestId": ("contract", bounds.MAX_REQUEST_ID_BYTES),
    "location": ("contract", bounds.MAX_S3_KEY_BYTES),
    "space": ("contract", bounds.MAX_IDENTIFIER_BYTES),
    "database": ("contract", bounds.MAX_IDENTIFIER_BYTES),
    "tableName": ("contract", bounds.MAX_IDENTIFIER_BYTES),
    "source": ("contract", 2 * bounds.MAX_IDENTIFIER_BYTES + 32),
    "actor": ("identity", 512),
    "username": ("identity", bounds.MAX_IDENTIFIER_BYTES),
    "raw": ("envelope", 0),
    "reportKey": ("derived", bounds.MAX_S3_KEY_BYTES),
    "tokens": ("derived", 3 * bounds.MAX_S3_KEY_BYTES),
    "error": ("error", 0),
}


def _record_failure_keys(plane: str, root: pathlib.Path = MODULES) -> set[str]:
    """The keys one plane's ``RecordFailure`` builds, parsed from its own template.

    Parsed rather than listed, so a plane naming a new field is included in the model without
    anyone remembering to add it here.

    Args:
      plane: The Terraform module's directory name.
      root: Where the modules live. Overridden only by the planted control, which patches a COPY
        of a real template so the plant cannot escape into a machine.

    Returns:
      The parameter names, with the ``.$`` suffix removed.

    Raises:
      KeyError: If the plane's machine has no ``RecordFailure`` state.
    """
    text = (root / plane / "state-machine.asl.json.tftpl").read_text()
    machine = json.loads(
        re.sub(r"\$\{[a-z_0-9]+\}", "PLACEHOLDER", re.sub(r":\s*\$\{[a-z_0-9]+\}", ": 0", text))
    )
    return {
        name.removesuffix(".$")
        for name in machine["States"]["RecordFailure"]["Parameters"]
    }


def _planes_with_a_failure_state() -> list[str]:
    """Every plane whose machine records a failure, from the templates.

    Args:
      None.

    Returns:
      The module directory names, sorted.

    Raises:
      None.
    """
    return sorted(
        path.parent.name
        for path in MODULES.glob("*/state-machine.asl.json.tftpl")
        if '"RecordFailure"' in path.read_text()
    )


def _unresolved(planes: list[str], root: pathlib.Path = MODULES) -> list[str]:
    """Every ``RecordFailure`` key across those planes that the origin table does not explain.

    The one resolution both the guard and its planted control run, so the control proves the
    mechanism the guard's absence assertion rests on rather than a parallel copy of it.

    Args:
      planes: The module directory names to check.
      root: Where the modules live.

    Returns:
      A ``plane/key`` string for each key with no declared origin.

    Raises:
      None.
    """
    return [
        f"{plane}/{key}"
        for plane in planes
        for key in sorted(_record_failure_keys(plane, root))
        if key not in RECORD_FAILURE_ORIGINS
    ]


def test_every_record_failure_key_resolves_to_a_declared_origin():
    """The other half of the bounds rule, asked of the templates rather than the contract.

    A field bound catches a caller's value before it travels. This catches the other direction: a
    plane putting something on its failure state that no bound explains, which is how the state
    grows past the limit with every guard still green.
    """
    unresolved = _unresolved(_planes_with_a_failure_state())

    assert not unresolved, (
        f"this RecordFailure key {UNRESOLVED_MESSAGE}, so nothing bounds what it costs the failure "
        f"state: {unresolved}"
    )


def test_the_origin_rule_REPORTS_a_key_it_cannot_explain():
    """The planted control for the guard above, whose clean result is otherwise unfalsifiable.

    Planted into a COPY of a real template rather than the tree, so the plant cannot escape into a
    machine. The message is asserted, and asserted to differ from the field-bounds guard's, because
    the two mutations are the two directions of one rule and a plant satisfying both would let one
    stand in for the other.
    """
    plane = _planes_with_a_failure_state()[0]

    assert not _unresolved([plane]), "the control's own plane is not clean before the plant"

    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        shutil.copytree(MODULES / plane, root / plane)
        template = root / plane / "state-machine.asl.json.tftpl"
        planted, substitutions = re.subn(
            r'("RecordFailure"\s*:\s*\{(?:[^{]|\{(?!"Parameters))*?"Parameters"\s*:\s*\{)',
            r'\1"Souvenir": "planted",',
            template.read_text(),
            count=1,
        )

        assert substitutions == 1, (
            "the plant matched nothing, so a green result below would say the guard is vacuous "
            "when the truth is that the fixture never landed"
        )
        template.write_text(planted)

        assert "Souvenir" in _record_failure_keys(plane, root), (
            "the plant landed somewhere the parser does not read, so the result below says nothing"
        )
        assert _unresolved([plane], root) == [f"{plane}/Souvenir"]

    assert UNRESOLVED_MESSAGE != "declare no byte bound", (
        "this guard and the field-bounds guard fail with the same message, so one plant could be "
        "read as satisfying both"
    )


def test_every_declared_origin_kind_is_one_of_the_six_and_every_entry_is_USED():
    """The kinds are a closed set, so `derived` cannot quietly become an escape hatch.

    And every entry answers for a key some plane actually names. An unused row is a byte figure
    nothing measures — it costs the model nothing today and silently sizes the reservation the day
    a plane adopts that key, which is the wrong moment to discover it was guessed at.
    """
    named = {key for plane in _planes_with_a_failure_state() for key in _record_failure_keys(plane)}

    for key, (kind, cost) in RECORD_FAILURE_ORIGINS.items():
        assert kind in ORIGIN_KINDS, f"{key} declares an origin kind outside the closed set: {kind}"
        assert cost >= 0, f"{key} declares a negative cost"

    assert set(RECORD_FAILURE_ORIGINS) == named, (
        f"the origin table and the templates disagree — declared but unnamed: "
        f"{sorted(set(RECORD_FAILURE_ORIGINS) - named)}; named but undeclared: "
        f"{sorted(named - set(RECORD_FAILURE_ORIGINS))}"
    )


def _stamped_and_identity(route: contract.Route) -> dict:
    """What the sender adds to a caller's body, at its largest.

    Args:
      route: The enqueue route.

    Returns:
      The stamped fields and the identity block, sized at their own reservations.

    Raises:
      None.
    """
    stamped = {name: "m" * 16 for name in route.stamped if name != "traceparent"}
    return {
        **stamped,
        "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01",
        "identity": {
            "actor": "a" * 63,
            "delegated_by": "a" * 63,
            "assurance": "interactive",
        },
    }


def link_one(route: contract.Route, fill: str) -> int:
    """The caller's body as the sender serializes it onto the queue.

    Args:
      route: The enqueue route.
      fill: The character every string is made of.

    Returns:
      The serialized byte length of the stamped message.

    Raises:
      None.
    """
    return _serialized({**worst_case_body(route, fill), **_stamped_and_identity(route)})


def _record(body: str) -> list:
    """The Pipes SQS record one message arrives as, at its realistic worst.

    Every field the service actually sends, not the two-key stub one plane guard used: all eight
    pipes are ``batch_size = 1`` with no ``input_template``, so this shape is what
    ``StartExecution`` receives. The body sits inside it as an ESCAPED JSON string, which is the
    link an obvious model leaves out — every quote the body already spent two bytes on costs four
    here.

    **Modelled, not measured.** No captured Pipes record exists in this repository, so the field
    set is written from the service's documented shape and sized at each field's own maximum. Its
    passing is evidence about the model, not about a record anyone has seen.

    Args:
      body: The serialized message body.

    Returns:
      The forwarded batch, as a structure.

    Raises:
      None.
    """
    return [
        {
            "messageId": "0" * 36,
            "receiptHandle": "r" * 1024,
            "body": body,
            "attributes": {
                "ApproximateReceiveCount": "1",
                "SentTimestamp": "1757000000000",
                "SequenceNumber": "1" * 20,
                "MessageGroupId": "g" * 128,
                "SenderId": "AROA" + "A" * 17 + ":" + "s" * 64,
                "MessageDeduplicationId": "d" * 128,
                "ApproximateFirstReceiveTimestamp": "1757000000000",
            },
            "messageAttributes": {},
            "md5OfBody": "0" * 32,
            "eventSource": "aws:sqs",
            "eventSourceARN": "arn:aws:sqs:eu-west-2:123456789012:dat-prod-requests.fifo",
            "awsRegion": "eu-west-2",
        }
    ]


def link_two(route: contract.Route, fill: str) -> int:
    """The execution input the Pipe hands to ``StartExecution``.

    Args:
      route: The enqueue route.
      fill: The character every string is made of.

    Returns:
      The serialized byte length of the forwarded batch.

    Raises:
      None.
    """
    body = json.dumps(
        {**worst_case_body(route, fill), **_stamped_and_identity(route)}, separators=(",", ":")
    )
    return _serialized(_record(body))


def link_four(route: contract.Route, plane: str, fill: str) -> int:
    """The ``RecordFailure`` state, as that plane's template actually builds it.

    Three terms: the forwarded envelope, which IS link two and is counted once as that; every
    other key the template names, at the bound its origin declares; and the error, reserved at
    what an escaped ``Cause`` costs on a state.

    Args:
      route: The enqueue route.
      plane: The Terraform module whose template to read.
      fill: The character every string is made of.

    Returns:
      The serialized byte length of the failure state.

    Raises:
      None.
    """
    keys = _record_failure_keys(plane)
    envelope = link_two(route, fill) if "raw" in keys else 0
    literals = sum(
        RECORD_FAILURE_ORIGINS[key][1] + len(key) + 4
        for key in keys
        if RECORD_FAILURE_ORIGINS[key][0] not in ("envelope", "error")
    )
    error = cp_config.CAUSE_RESERVATION_BYTES if "error" in keys else 0
    return envelope + literals + error + 2


def _plane_of(route: contract.Route) -> str:
    """The Terraform module serving one enqueue route's queue.

    Args:
      route: The enqueue route.

    Returns:
      The module's directory name.

    Raises:
      StopIteration: If no module's name stems to that queue's.
    """
    return next(
        path.parent.name
        for path in MODULES.glob("*/pipe.tf")
        if _stem(path.parent.name) == _stem(route.queue)
    )


@pytest.mark.parametrize("route", PIPED_ROUTES, ids=lambda route: route.id)
def test_every_link_of_the_chain_fits_the_state_limit(route):
    """The whole chain, for every piped route, against ONE constant.

    Three plane guards used to compute overlapping parts of this and disagree about the fourth
    link — one of them measured it against a model an order of magnitude too small. This is the
    one model, and the constant comes from ``cpcommon.config`` rather than a fourth private copy.
    """
    plane = _plane_of(route)
    limit = cp_config.STATE_PAYLOAD_LIMIT_BYTES

    for fill in FILLS:
        measured = {
            "link one, the caller's stamped body": link_one(route, fill),
            "link two, the Pipe's forwarded record": link_two(route, fill),
            "link four, the RecordFailure state": link_four(route, plane, fill),
        }
        for name, size in measured.items():
            assert size < limit, (
                f"{route.id} at {fill!r}: {name} reaches {size:,} bytes against a {limit:,}-byte "
                f"limit — States.DataLimitExceeded, which no Catch in the fleet names, so the user whose "
                f"request failed is told nothing"
            )


# ── The reservations, and the caps that follow from them ─────────────────────


def _realistic_cause() -> str:
    """A Lambda error ``Cause`` in the shape this fleet actually produces.

    **Constructed, not captured**, written from the shape Lambda documents and the fleet's own
    ``TerminalError`` detail cap. The assertions below are chosen to be falsifiable anyway: they
    measure the ESCAPE RATIO and the bytes per character, which are properties of the encoding
    rather than of this particular string, so a real capture would have to disagree about JSON
    escaping to disagree with them. Real Causes have since been captured from failed production
    executions, refusals and a timeout — any signed-in session can provoke one through the API —
    and they are all ASCII and escape at under 1.08, inside the reservation;
    ``docs/testing/sessions.md`` holds the reading.

    Args:
      None.

    Returns:
      The serialized Cause document, as Lambda returns it.

    Raises:
      None.
    """
    return json.dumps(
        {
            "errorMessage": "create_failed: " + ("x" * cp_errors.MAX_DETAIL_CHARS),
            "errorType": "TerminalError",
            "requestId": "0" * 36,
            "stackTrace": [
                '  File "/var/task/file_send_copy_objects.py", line 214, in _copy\n    raise\n'
            ]
            * 8,
        }
    )


def test_the_cause_reservation_is_measured_against_the_encoding_it_reserves_for():
    """WHY the reservation is twice the documented length, measured rather than asserted.

    32,768 is a maximum length in CHARACTERS on the execution-history event shapes — not a byte
    quota on a state — and a Cause is a JSON document sitting inside a JSON string on the state, so
    it is escaped there like every other value. Reserving it unescaped would exempt the one value
    in the model most certainly escaped.

    **Asserting that a captured Cause FITS would prove nothing**: a real one runs to a couple of
    thousand characters and fits a 32 KiB, a 36 KiB and a 66 KiB reservation identically. What is
    falsifiable is the ratio, so that is what is measured.
    """
    cause = _realistic_cause()
    on_the_state = len(json.dumps(cause).encode("utf-8"))

    assert on_the_state > len(cause), "a Cause on a state is not being escaped at all"
    assert cp_config.CAUSE_RESERVATION_BYTES == 2 * cp_config.CAUSE_MAX_CHARS
    assert on_the_state / len(cause) <= cp_config.CAUSE_RESERVATION_BYTES / cp_config.CAUSE_MAX_CHARS, (
        f"a realistic Cause escapes at {on_the_state / len(cause):.3f}x, over the "
        f"{cp_config.CAUSE_RESERVATION_BYTES / cp_config.CAUSE_MAX_CHARS}x the reservation allows"
    )
    assert len(cause.encode("utf-8")) == len(cause), (
        "the Cause carries a multi-byte character, so counting its characters is no longer "
        "counting its bytes and the reservation's units have drifted"
    )


def test_the_reservations_cover_what_the_artifacts_actually_produce():
    """The two numbers ``enqueue`` declares, held against the things it cannot read.

    The image carries ``lambdas/`` and not ``infra/``, so that module cannot sum eight Terraform
    templates at import. It declares a reservation and this measures it — which is not ``X == X``,
    because the quantity measured comes from artifacts the module never sees.
    """
    largest = max(
        sum(
            RECORD_FAILURE_ORIGINS[key][1] + len(key) + 4
            for key in _record_failure_keys(plane)
            if RECORD_FAILURE_ORIGINS[key][0] not in ("envelope", "error")
        )
        for plane in _planes_with_a_failure_state()
    )

    assert largest <= enqueue.MAX_RECORD_FAILURE_LITERAL_BYTES, (
        f"the largest plane's RecordFailure literals reach {largest} bytes against a "
        f"{enqueue.MAX_RECORD_FAILURE_LITERAL_BYTES}-byte reservation"
    )

    overhead = _serialized(_record("")) - _serialized("")

    assert overhead <= enqueue.MAX_PIPE_RECORD_OVERHEAD_BYTES, (
        f"the modelled Pipes record costs {overhead} bytes beside the body, against a "
        f"{enqueue.MAX_PIPE_RECORD_OVERHEAD_BYTES}-byte reservation"
    )


@pytest.mark.parametrize("route", contract.ENQUEUE_ROUTES, ids=lambda route: route.id)
def test_every_routes_worst_legal_request_passes_the_cap(route):
    """The cap has to admit what every route legally accepts, or it refuses correct requests.

    Built from the factory rather than from the cap, so this is not ``X ≤ X``: seven of the eleven
    routes are sized by their own field bounds and know nothing about ``MAX_MESSAGE_BYTES``.
    """
    for fill in FILLS:
        body = json.dumps(
            {**worst_case_body(route, fill), **_stamped_and_identity(route)},
            separators=(",", ":"),
        )

        assert len(body.encode("utf-8")) <= enqueue.MAX_MESSAGE_BYTES, (
            f"{route.id} at {fill!r} builds a legal request of {len(body.encode('utf-8')):,} bytes "
            f"that the {enqueue.MAX_MESSAGE_BYTES:,}-byte cap refuses"
        )


def test_the_two_lowered_caps_are_as_high_as_the_chain_permits():
    """A ``≤`` check stays green at a cap set far too low, so the two numbers are pinned TIGHT.

    Both came down from 96 KiB. Left there the chain breaches; set at 8 KiB the chain fits and so
    would any smaller number, and nothing in a fits-the-limit assertion would ever say so. This
    asserts the other side: one whole kibibyte more and the chain no longer fits, so the caps are
    the largest round unit the limit admits rather than a comfortable number under it.
    """
    from arcommon import config as ar_config
    from fscommon import config as fs_config

    for route_id, module, name in (
        ("archive.archive", ar_config, "ARCHIVE_MAX_ITEM_BYTES"),
        ("fileSend.enqueue", fs_config, "SEND_MAX_ITEM_BYTES"),
    ):
        route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
        original = getattr(module, name)
        try:
            setattr(module, name, original + 1024)
            over = max(
                len(
                    json.dumps(
                        {**worst_case_body(route, fill), **_stamped_and_identity(route)},
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                for fill in FILLS
            )
        finally:
            setattr(module, name, original)

        assert over > enqueue.MAX_MESSAGE_BYTES, (
            f"{name} could be a kibibyte higher and still fit the chain, so it is lower than the "
            f"limit requires and the reduction is costing users capacity for nothing"
        )


# ── What was live before this spec, characterised so the suite carries the reason ────


#: The message cap before it was re-derived: the SQS message limit less the identity block.
OLD_MAX_MESSAGE_BYTES = 262_144 - 512

#: The archive and file-send selection caps before the fourth link was modelled honestly.
OLD_SELECTION_CAP_BYTES = 96 * 1024

#: Fields a route gained after the old caps were characterised. The figures the register quotes
#: describe the body as it was, so the characterisation leaves these out rather than re-quoting a
#: number for a request that never existed at those caps.
FIELDS_ADDED_SINCE_THE_OLD_CAPS = {"archive.archive": ("archiveName",)}


def test_a_body_at_the_OLD_cap_produced_a_record_over_the_state_limit():
    """The first live overshoot: the cap admitted a message no execution could start from.

    ``MAX_MESSAGE_BYTES`` was the SQS limit less the identity block, which bounds what the QUEUE
    accepts and says nothing about what Step Functions will start an execution with. A body at
    that cap, escaped into the Pipe's record, is more than twice the state limit.
    """
    wrapper = len(json.dumps({"k": ""}, separators=(",", ":")).encode("utf-8")) - 2
    body = json.dumps(
        {"k": _filled(ESCAPE_WORST_FILL, OLD_MAX_MESSAGE_BYTES - wrapper)}, separators=(",", ":")
    )
    record = _serialized(_record(body))

    assert len(body.encode("utf-8")) <= OLD_MAX_MESSAGE_BYTES, (
        "the fixture is not a body the old cap admitted, so it characterises nothing"
    )
    assert record > cp_config.STATE_PAYLOAD_LIMIT_BYTES, (
        "a body at the old cap now fits the record, so this characterisation has gone stale and "
        "the reason the cap moved needs re-deriving rather than re-reading"
    )
    assert enqueue.MAX_MESSAGE_BYTES < OLD_MAX_MESSAGE_BYTES


@pytest.mark.parametrize(
    "route_id,plane,field",
    [
        ("dataQuality.enqueue", "data-quality", "location"),
        ("sharedSpace.enqueue", "shared-spaces", "space"),
    ],
)
def test_an_unbounded_caller_string_breached_the_failure_state(route_id, plane, field):
    """The second and third: a caller string nothing bounded, named on a ``RecordFailure``.

    Neither plane's ``validate-authorize`` checked a length, and neither field had a bound
    anywhere, so a caller could put a quarter-megabyte string on a ``Pass`` with no ``Catch``.
    The state breaches, ``NotifyFailure`` never runs, and a user whose request failed is told
    nothing — which is the failure this whole arc exists to close.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
    unbounded = "u" * (256 * 1024)
    keys = _record_failure_keys(plane)

    assert field in keys, f"{plane}'s RecordFailure no longer names {field}"

    literals = sum(
        RECORD_FAILURE_ORIGINS[key][1] + len(key) + 4
        for key in keys
        if RECORD_FAILURE_ORIGINS[key][0] not in ("envelope", "error")
    )
    unbounded_state = literals - RECORD_FAILURE_ORIGINS[field][1] + len(unbounded) + 2

    assert unbounded_state > cp_config.STATE_PAYLOAD_LIMIT_BYTES
    assert bounds.bound_for(route.id, field) is not None, (
        f"{field} has lost its bound, so the breach characterised here is live again"
    )
    assert bounds.over_bound(route, {**worst_case_body(route, "k"), field: unbounded}) is not None


def _accented_file_ops_selection() -> list:
    """The selection that passed file-ops' old measurement and breached the chain.

    ONE definition, because two tests characterise it from different angles — what the two
    measurements disagreed by, and what the register quotes — and written twice they can be edited
    apart, leaving one of them describing a request that no longer exists.

    Args:
      None.

    Returns:
      Forty-nine folders whose keys and target names are accented characters.

    Raises:
      None.
    """
    return [{"kind": "folder", "key": "é" * 512, "targetName": "é" * 127} for _ in range(49)]


def test_an_accented_file_ops_selection_breached_what_its_own_cap_measured():
    """The fourth, which the spec did not name because nobody had measured it.

    file-ops' selection cap counted the selection with non-ASCII LEFT LITERAL, on the reasoning
    that the browser sends literal UTF-8 and the Pipe keeps it literal. Both halves are true and
    the conclusion was not: the API re-serialises the body with the default escaping one hop
    before the Pipe. So an accented selection passed the cap at roughly a third of what it cost
    on the wire, and its failure state was over the limit.
    """
    accented = _accented_file_ops_selection()
    literal = len(json.dumps(accented, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    on_the_wire = _serialized(accented)

    from focommon.config import FILE_OPS_MAX_SELECTION_BYTES

    assert literal <= FILE_OPS_MAX_SELECTION_BYTES, (
        "the fixture no longer passes the cap as it used to be measured, so it characterises a "
        "request the plane would have refused anyway"
    )
    assert on_the_wire > 2.5 * literal, (
        f"an accented selection costs {on_the_wire} on the wire against {literal} measured "
        f"literally — if that ratio has collapsed, the two measurements no longer disagree and "
        f"this characterisation is describing something that cannot happen"
    )

    body = json.dumps({"items": accented}, separators=(",", ":"))
    failure_state = _serialized(_record(body)) + cp_config.CAUSE_RESERVATION_BYTES

    assert failure_state > cp_config.STATE_PAYLOAD_LIMIT_BYTES


def test_the_overshoot_the_register_cites_is_the_one_this_model_computes(monkeypatch):
    """The figures the register and the delivery doc quote, computed rather than transcribed.

    An earlier pair was measured before the recipients-count and identifier-unit corrections and
    was wrong by up to 8 KB — in the direction that justified a user-visible capacity cut, written
    into two production docstrings where nothing could contradict it. The numbers live here now,
    so a change to the model reddens this and whoever fixes it sees the prose that quotes it.
    """
    from arcommon import config as ar_config
    from fscommon import config as fs_config

    current = worst_case_body

    def _as_it_was(route, fill):
        body = current(route, fill)
        for field in FIELDS_ADDED_SINCE_THE_OLD_CAPS.get(route.id, ()):
            body.pop(field, None)
        return body

    monkeypatch.setitem(globals(), "worst_case_body", _as_it_was)

    breaches = {}
    for route_id, module, name, plane in (
        ("archive.archive", ar_config, "ARCHIVE_MAX_ITEM_BYTES", "archive"),
        ("fileSend.enqueue", fs_config, "SEND_MAX_ITEM_BYTES", "file-send"),
    ):
        route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
        original = getattr(module, name)
        try:
            setattr(module, name, OLD_SELECTION_CAP_BYTES)
            breaches[plane] = max(link_four(route, plane, fill) for fill in FILLS)
        finally:
            setattr(module, name, original)

    assert breaches == {"archive": 263_533, "file-send": 271_446}, (
        f"the overshoot at the old caps is now {breaches}. The pair is quoted in "
        f"docs/decisions/control-planes.md and nowhere else — correct it there, and check whether "
        f"the model moved for a reason or by accident before you do"
    )
    assert all(size > cp_config.STATE_PAYLOAD_LIMIT_BYTES for size in breaches.values())


def test_the_accented_file_ops_figures_are_the_ones_the_register_cites():
    """The same, for the fourth overshoot, which no spec named.

    Three numbers travel together in the prose — what the old measurement counted, what the wire
    actually spends, and how far over the limit the failure state lands — and a reader can only
    check the middle one against the other two if all three come from one place.
    """
    accented = _accented_file_ops_selection()
    plane_measured = len(
        json.dumps(accented, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    on_the_wire = _serialized(accented)
    body = json.dumps({"items": accented}, separators=(",", ":"))
    failure_state = _serialized(_record(body)) + cp_config.CAUSE_RESERVATION_BYTES

    assert (plane_measured, on_the_wire) == (64_730, 189_974)
    assert failure_state - cp_config.STATE_PAYLOAD_LIMIT_BYTES == 27_151


def test_the_factorys_non_string_defaults_are_the_LARGEST_the_contract_allows():
    """FR-002's blind spot is a field pinned small, and three defaults were unguarded.

    Measured before this existed: building an ``optional`` as ``None``, a ``literal`` at its
    SHORTEST member and an ``int`` as ``1`` each left the whole battery green — and the first of
    those shrinks ``notifications.enqueue``'s worst case by 78%, because its only declared field
    is optional. A worst case that quietly omits what a caller may legally send understates every
    measurement built on it.
    """
    notifications = next(r for r in contract.ENQUEUE_ROUTES if r.id == "notifications.enqueue")
    built = worst_case_body(notifications, "k")

    assert built["id"] is not None, (
        "an optional field is built absent, so the worst case is missing everything a caller may "
        "legally send but need not"
    )

    conversion = next(r for r in contract.ENQUEUE_ROUTES if r.id == "resultsConversion.enqueue")
    literals = contract.walk(conversion.request)
    declared = {name: node for name, node, _ in literals.fields}
    built_conversion = worst_case_body(conversion, "k")

    assert built_conversion["format"] == max(declared["format"].literals, key=len), (
        "a literal field is built at something other than its longest member"
    )

    table_build = next(r for r in contract.ENQUEUE_ROUTES if r.id == "tableBuild.create")
    digits = worst_case_body(table_build, "k")["partitionKeys"][0]["digits"]

    assert digits > 2**32, (
        f"an int field is built as {digits}, which costs a handful of bytes where JSON permits "
        f"many more — the term is small, and so is the point at which it stops being small"
    )


def test_a_verb_bounded_name_is_modelled_at_the_length_its_RULE_permits():
    """The regex-owner case, which silently built one character.

    ``tableName``'s owner is ``CATALOG_IDENTIFIER_RE`` — a pattern, not a number — so the budget
    lookup returned nothing and the string branch fell back to a single character. Three routes
    carried a 3-byte table name in every worst case where the rule permits 65.
    """
    for route_id in ("tableBuild.create", "tableBuild.refresh", "tableShare.enqueue"):
        route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
        built = worst_case_body(route, "k")["tableName"]

        assert _serialized(built) == bounds.MAX_IDENTIFIER_BYTES, (
            f"{route_id}'s worst case carries a {_serialized(built)}-byte tableName where the "
            f"catalog rule permits {bounds.MAX_IDENTIFIER_BYTES}"
        )


#: The browser services that cap a selection by size, and therefore have to measure the selection
#: the way the API serialises it.
_SELECTION_SERVICES = (
    "apps/portal/src/features/archive/archive.service.ts",
    "apps/portal/src/features/file-send/fileSend.service.ts",
    "apps/portal/src/features/file-browser/fileOps.service.ts",
)


def test_every_browser_selection_cap_measures_what_the_API_SENDS():
    """One helper for the three planes that cap a selection, and none of them rolling its own.

    `JSON.stringify` leaves non-ASCII literal and the API escapes it, so a browser measuring the
    literal form under-counts an accented key threefold. On file-ops that was live: the selection
    passed both caps and its failure state went over the state limit, where nothing notifies. The
    other two had the same divergence and were saved only by the API's new cap refusing the
    request — which is a legible 413 rather than silence, but it is the same defect.

    Asserted over the POPULATION rather than on the one plane that was broken, because the reason
    it was broken is that each service answered the question for itself.
    """
    offenders = {}
    for relative in _SELECTION_SERVICES:
        source = (REPO / relative).read_text()
        if "wireBytes(" not in source:
            offenders[relative] = "does not measure with the shared helper"
        elif re.search(r"TextEncoder\(\)\.encode\(JSON\.stringify", source):
            offenders[relative] = "still measures the literal form somewhere"

    assert not offenders, (
        f"a browser selection cap measures something other than what the API sends: {offenders}"
    )


def test_the_shared_helper_is_declared_once():
    """A second copy of the escaping is a second answer to one question.

    file-ops carried a private copy for exactly as long as it was the only plane fixed; the guard
    above would pass with three private copies that disagree, so the population is held to ONE
    definition.
    """
    definitions = [
        path
        for path in (REPO / "apps/portal/src").rglob("*.ts")
        if "function wireBytes" in path.read_text()
    ]

    assert [p.name for p in definitions] == ["wireBytes.ts"], (
        f"wireBytes is defined in {[str(p) for p in definitions]} — one escaping rule, one home"
    )
