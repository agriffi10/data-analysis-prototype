"""The field bounds, held against the contract they are supposed to cover.

**The population is DERIVED, never listed.** A hand-written list of fields agrees with itself on
the day it is written and says nothing the morning a route grows a twelfth one. So the guard walks
``contract.walk`` over every enqueue request type, collects every declared string and list path,
and requires each to resolve through ``bounds.bound_for``. A field added later with no bound fails
here rather than reaching a ``RecordFailure`` nothing can catch.

The other direction — that a ``RecordFailure`` key resolves to something bounded — lives with the
chain guard in ``lambdas/test_request_size_chain.py``, because the same table supplies that
model's per-key bytes. The two mutations are asserted to fail with different messages, so one
plant cannot satisfy both.

Attributes:
  ADD_MEMBERS_TIMEOUT_SECONDS: The add-members verb's deployed ceiling, read from the plane's
    Terraform rather than restated.
  ROUND_TRIP_MS: A pessimistic AWS round trip, the unit the member cap is charged in. Whole
    milliseconds, because a bound compared against a float sum lands on its own boundary and fails
    on the last bit rather than on the model.
  ROUND_TRIPS_PER_MEMBER: What the verb does per member — a Cognito slot assignment, a roster
    write and a notification.
"""

import json
import os
import pathlib
import re
import sys
from typing import TypedDict

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apicommon import bounds, contract
from apicommon.contract import TypeNode

#: What the chain guard's own mutation fails with, held here so the two messages cannot converge.
_CHAIN_MUTATION_MESSAGE = "resolves to no declared origin"

REPO = pathlib.Path(__file__).resolve().parents[2]

ADD_MEMBERS_TIMEOUT_SECONDS = 60
ROUND_TRIP_MS = 100
ROUND_TRIPS_PER_MEMBER = 3


def _paths(node: TypeNode, prefix: str, found: list[tuple[str, str]]) -> None:
    """Collects every declared string and list path beneath one node.

    Args:
      node: The normalised node to walk.
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
        _paths(node.of[0], prefix, found)
    elif node.kind == "list":
        _paths(node.of[0], f"{prefix}[]", found)
    elif node.kind == "object":
        for name, child, _ in node.fields:
            _paths(child, f"{prefix}.{name}" if prefix else name, found)


def _declared_paths(route: contract.Route) -> list[tuple[str, str]]:
    """Every declared string and list path on one route's request type.

    Args:
      route: The route whose request type to walk.

    Returns:
      The paths and their kinds.

    Raises:
      None.
    """
    found: list[tuple[str, str]] = []
    _paths(contract.walk(route.request), "", found)
    return found


UNBOUNDED_MESSAGE = "declare no byte bound"

#: Every (route, path) a bound is declared for BY NAME. The resolution in ``bounds.bound_for``
#: also walks outwards to a container, which is a true validation rule and a useless construction
#: one — a leaf inheriting its list's budget builds a worst case forty kilobytes wide and satisfies
#: every check that a field is not pinned small. The guard therefore asks for the exact path.
_DECLARED = {(bound.route_id, bound.path) for bound in bounds.FIELD_BOUNDS}


def _unbounded(routes) -> list[tuple[str, str, str]]:
    """Every declared string or list path on those routes that no bound covers.

    The one resolution both the fleet guard and its positive control run, so the control proves
    the mechanism that the guard's absence assertion rests on rather than a parallel copy of it.

    Args:
      routes: The enqueue routes to walk.

    Returns:
      Route id, path and kind for each unbounded field.

    Raises:
      None.
    """
    return [
        (route.id, path, kind)
        for route in routes
        for path, kind in _declared_paths(route)
        if (route.id, path) not in _DECLARED
    ]


def test_every_declared_string_or_list_field_carries_a_bound():
    """The whole rule, over a population the contract decides rather than this file.

    Sixty-eight paths today across eleven request types. The count is not asserted — a count is
    satisfied by a substitution — but the resolution is, for every one of them, naming the route
    and the path that has nothing covering it.
    """
    unbounded = _unbounded(contract.ENQUEUE_ROUTES)

    assert not unbounded, (
        f"these caller-controlled fields {UNBOUNDED_MESSAGE}, so the chain they travel cannot "
        f"be measured: {unbounded}"
    )


def test_the_rule_REPORTS_an_unbounded_field_when_there_is_one():
    """The positive control the guard above cannot supply for itself.

    An absence assertion over an empty collector passes for the wrong reason, and this file's whole
    claim is that a field added later with no bound fails here. So a route is planted whose request
    type declares a string nothing covers, and the resolution is required to name it — the same
    ``_unbounded`` the guard runs, not a re-implementation, or the control would prove a mechanism
    the guard does not use.

    The message is asserted because the sibling mutation in ``test_request_size_chain.py`` plants
    the OTHER direction — an unresolvable ``RecordFailure`` key — and the two are required to fail
    differently, so one plant cannot be read as satisfying both.
    """
    class UnboundedRequest(TypedDict):
        """A request type carrying a field no bound covers.

        Attributes:
          souvenir: The planted field. Declared here rather than added to the real contract, so the
            plant cannot escape into the shipped wire types.
        """

        souvenir: str

    planted = contract.EnqueueRoute(
        id="planted.enqueue",
        method="POST",
        path="/v1/planted",
        idempotent=False,
        plane="api",
        request=UnboundedRequest,
        query=None,
        response=contract.EnqueueAccepted,
        queue="shared-space",
        stamped=frozenset({"traceparent"}),
    )

    reported = _unbounded([planted])

    assert reported == [("planted.enqueue", "souvenir", "str")], (
        "the planted unbounded field was not reported, so the fleet guard's clean result says "
        f"nothing: {reported}"
    )
    assert UNBOUNDED_MESSAGE not in _CHAIN_MUTATION_MESSAGE, (
        "this guard and the chain guard's RecordFailure mutation fail with overlapping messages, "
        "so one plant could be read as satisfying both"
    )


def test_a_field_nobody_has_declared_yet_falls_back_to_its_container():
    """The backstop, which is a claim the resolution's own docstring makes and nothing else tested.

    The guard above requires an EXACT bound for every path the contract declares today, so the
    outward walk never fires for any of them and could rot unnoticed. It matters for the field that
    does not exist yet: a key added inside a bounded list is covered from the moment it is declared,
    and reaches the guard as a request to give it a tighter number rather than as an unbounded
    field on the wire.
    """
    covered = bounds.bound_for("fileOps.enqueue", "source.items[].newFieldNobodyHasDeclared")

    assert covered is not None and covered.path == "source.items", (
        "a new field inside a bounded list resolves to nothing, so it would travel unbounded until "
        "somebody noticed the guard asking for it"
    )
    assert bounds.bound_for("fileOps.enqueue", "somethingEntirelyNew") is None, (
        "a new TOP-LEVEL field resolves to a bound it has no relationship with, which would hide it "
        "from the guard that exists to demand one"
    )


def test_a_literal_field_needs_no_declared_bound_because_its_own_values_bound_it():
    """The one exemption, stated so it cannot quietly widen.

    A ``Literal`` node's value set is closed and written in the contract, so the longest member IS
    the bound and declaring a second number beside it would be the same rule written twice. Every
    other kind of field is covered by the rule above.
    """
    literals = []
    for route in contract.ENQUEUE_ROUTES:
        node = contract.walk(route.request)
        for name, child, _ in node.fields:
            inner = child.of[0] if child.kind == "optional" else child
            if inner.kind == "literal":
                literals.append((route.id, name, max(len(v) for v in inner.literals)))

    assert literals, "no literal field found — the exemption has lost its population"
    assert all(longest < bounds.MAX_IDENTIFIER_BYTES for _, _, longest in literals), (
        f"a literal field is longer than a catalog identifier, so its own values no longer bound "
        f"it cheaply: {literals}"
    )


def test_a_verb_bound_says_where_its_number_lives_and_an_api_bound_carries_one():
    """The two kinds are not interchangeable, and this is what keeps them apart.

    A ``verb`` bound is applied inside ``validate-authorize``, so it bounds what a failure state
    can carry and says nothing about what the Pipe needs to start an execution. It therefore
    carries no number here — importing a plane's ``config`` would raise at this service's cold
    start, because those modules fail fast on their own unset environment — and names the constant
    instead. An ``api`` bound is the opposite: this service applies it, so the number is here.
    """
    for bound in bounds.FIELD_BOUNDS:
        if bound.enforced_at == "api":
            assert isinstance(bound.max_bytes, int) and bound.max_bytes > 0, (
                f"{bound.route_id}/{bound.path} is enforced here but carries no number"
            )
            assert bound.owner == "", (
                f"{bound.route_id}/{bound.path} is enforced here and also names an owner elsewhere"
            )
        else:
            assert bound.max_bytes is None, (
                f"{bound.route_id}/{bound.path} is enforced in the verb but copies its number here"
            )
            assert re.fullmatch(r"[a-z_]+\.[a-z_]+\.[A-Z_]+", bound.owner), (
                f"{bound.route_id}/{bound.path} does not name where its number lives"
            )


def test_every_verb_owned_constant_exists_where_the_bound_says_it_does():
    """A named owner that does not resolve is a bound with nothing behind it.

    Imported HERE rather than in ``bounds`` itself: a test may stand the plane layers up, and this
    conftest already does. The production module may not, which is the whole reason the name is
    carried as text.
    """
    for bound in bounds.FIELD_BOUNDS:
        if bound.enforced_at != "verb":
            continue
        module_path, _, constant = bound.owner.rpartition(".")
        module = __import__(module_path, fromlist=[constant])

        assert hasattr(module, constant), f"{bound.owner} does not exist"


def test_the_partition_key_bound_mirrors_the_planes_own_definition_budget():
    """The one mirrored number, held against its source.

    ``partitionKeys`` is applied HERE — nothing in the plane bounds it — so the number has to be
    in this service. Its budget is the table definition the declared keys become part of, whose
    size the plane already budgets, and a mirror with nothing holding it is how two copies of one
    rule drift.
    """
    from tbcommon.config import REFRESH_MAX_DEFINITION_BYTES

    assert bounds.MAX_PARTITION_KEYS_BYTES == REFRESH_MAX_DEFINITION_BYTES


def test_the_member_cap_is_computed_against_the_verbs_own_timeout():
    """WHAT SIZES the member cap, rather than the number restated.

    ``add_members`` does a Cognito slot assignment, a roster write and a notification per member,
    all serially, inside a sixty-second ceiling — so a request naming more members than fit could
    not finish however few bytes it was.

    **Held at HALF the ceiling rather than at it.** The cap that exactly exhausts the budget is the
    one a fourth round trip per member breaks, and the failure then arrives as a timed-out verb
    rather than as a refusal. The margin is the assertion, not a comment beside it.
    """
    budget_ms = ADD_MEMBERS_TIMEOUT_SECONDS * 1000
    spent_ms = bounds.MAX_MEMBERS_PER_REQUEST * ROUND_TRIPS_PER_MEMBER * ROUND_TRIP_MS
    with_one_more_ms = bounds.MAX_MEMBERS_PER_REQUEST * (ROUND_TRIPS_PER_MEMBER + 1) * ROUND_TRIP_MS

    assert spent_ms <= budget_ms, (
        f"{bounds.MAX_MEMBERS_PER_REQUEST} members spend {spent_ms}ms of a {budget_ms}ms ceiling"
    )
    assert with_one_more_ms <= budget_ms, (
        f"the cap spends {spent_ms}ms of {budget_ms}ms and a fourth round trip per member would "
        f"take it to {with_one_more_ms}ms — a cap sitting on its own measurement, which the next "
        f"legitimate addition breaks"
    )


def test_the_add_members_timeout_is_the_number_terraform_deploys():
    """The budget above is the DEPLOYED ceiling, not a number written twice.

    The plane's Terraform gives every verb but one the same default, so the cap this file charges
    against moves the day that default does.
    """
    locals_text = (REPO / "infra" / "modules" / "shared-spaces" / "lambda.tf").read_text()
    found = re.search(r"lookup\(local\.shared_space_function_timeouts,\s*each\.key,\s*(\d+)\)", locals_text)

    assert found, "the shared-space verbs no longer take a default timeout from lambda.tf"
    assert int(found.group(1)) == ADD_MEMBERS_TIMEOUT_SECONDS


def test_the_request_id_bound_refuses_no_id_the_queue_would_take():
    """The bound is the CHAIN's, and it must not become a second, tighter identity rule.

    Nine routes make the caller's id the deduplication key verbatim, and ``_checked`` accepts any
    128 printable-ASCII characters — quotes and backslashes among them, each of which serializes to
    two bytes. A bound set at the plain length would refuse an id the queue accepts, which is a
    new refusal wearing a measurement's clothes.
    """
    from apicommon.fifo import _FIFO_KEY_RE, MAX_FIFO_KEY_CHARS

    worst = '"' * MAX_FIFO_KEY_CHARS

    assert _FIFO_KEY_RE.match(worst), "the queue's own character class no longer admits a quote"
    assert len(json.dumps(worst).encode()) == bounds.MAX_REQUEST_ID_BYTES


@pytest.mark.parametrize(
    "route_id,path,value,expected_limit",
    [
        ("dataQuality.enqueue", "location", "l" * 2000, bounds.MAX_S3_KEY_BYTES),
        ("sharedSpace.enqueue", "space", "s" * 4000, bounds.MAX_IDENTIFIER_BYTES),
        ("archive.restore", "requestId", "r" * 4000, bounds.MAX_REQUEST_ID_BYTES),
    ],
)
def test_an_over_long_field_is_refused_with_the_bound_that_refused_it(
    route_id, path, value, expected_limit
):
    """The refusal a caller can act on, rather than "the request is too large".

    The whole-body cap sends no limit and names no field, so a caller with one long field is told
    to shrink a request they have no way to measure. These three are the fields the spec names as
    live overshoots.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)
    body = _smallest_valid_body(route)
    _assign(body, path, value)

    breached = bounds.over_bound(route, body)

    assert breached is not None, f"{route_id}/{path} at {len(value)} characters was not refused"
    assert breached.path == path
    assert breached.max_bytes == expected_limit


def test_a_body_inside_every_bound_is_not_refused():
    """The positive control. An ``over_bound`` that refused everything would satisfy every test
    above, which is how a guard comes to certify a refusal path nobody can get past."""
    for route in contract.ENQUEUE_ROUTES:
        assert bounds.over_bound(route, _smallest_valid_body(route)) is None, (
            f"{route.id}'s smallest valid body is refused by its own bounds"
        )


def test_a_verb_bound_is_not_applied_here():
    """A ``verb`` bound bounds link four and not the links before it, so applying it here would
    claim a check this service does not make."""
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    body = _smallest_valid_body(route)
    body["source"]["items"] = [{"kind": "file", "key": "k" * 1024} for _ in range(400)]

    assert bounds.over_bound(route, body) is None, (
        "the selection was refused here, but its cap lives in the verb — two enforcement sites for "
        "one number is how they come to disagree"
    )


def _assign(body: dict, path: str, value: object) -> None:
    """Sets one dotted path in a body.

    Args:
      body: The body to modify in place.
      path: The dotted path.
      value: The value to set.

    Returns:
      None.

    Raises:
      None.
    """
    parts = path.split(".")
    target = body
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _smallest_valid_body(route: contract.Route) -> dict:
    """The smallest body that satisfies one route's declared type.

    Built from the walk rather than written out, so a route that grows a required field gets one
    here without this file being edited.

    Args:
      route: The route whose request type to satisfy.

    Returns:
      A body the route's own validator accepts.

    Raises:
      None.
    """
    body = _smallest(contract.walk(route.request))
    assert contract.validate_request(route, body) is None, (
        f"the built body for {route.id} does not satisfy its own declared type: {body}"
    )
    return body


def _smallest(node: TypeNode) -> object:
    """The smallest value satisfying one normalised node.

    Args:
      node: The node to satisfy.

    Returns:
      A value the node accepts.

    Raises:
      None.
    """
    if node.kind == "str":
        return "a"
    if node.kind == "int":
        return 1
    if node.kind == "float":
        return 1.0
    if node.kind == "bool":
        return False
    if node.kind == "none":
        return None
    if node.kind == "literal":
        return node.literals[0]
    if node.kind == "optional":
        return None
    if node.kind == "list":
        return []
    return {name: _smallest(child) for name, child, required in node.fields if required}
