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
    Terraform rather than restated. It is the premise the mirrored member cap rests on: the
    derivation this file mirrors charges that ceiling, so a Terraform change that moved it would
    invalidate a number neither module would notice.
"""

import ast
import dataclasses
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

REPO = pathlib.Path(__file__).resolve().parents[2]


def _chain_guard_message() -> str:
    """The failure message the chain guard's own mutation produces.

    Read from that module rather than restated, because the assertion these two feed is that the
    messages DIFFER — and two literals written in one file agree or differ by typing, not by
    anything either guard does.

    Args:
      None.

    Returns:
      The chain guard's unresolved-origin message.

    Raises:
      None.
    """
    sys.path.insert(0, str(REPO / "lambdas"))
    import test_request_size_chain

    return test_request_size_chain.UNRESOLVED_MESSAGE


#: Resolved LAZILY, inside the one test that needs it. At module scope the two guards import each
#: other — this file for the walk, that one for this message — and the chain guard could not be run
#: on its own at all: collection died on a partially initialised module. Whole-tree collection hid
#: it, because ``lambdas/api/`` sorts first.

ADD_MEMBERS_TIMEOUT_SECONDS = 60


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
    assert UNBOUNDED_MESSAGE not in _chain_guard_message(), (
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
    carries no number here and names the constant instead — the API does not depend on the plane
    layers, and copying their numbers in would be one rule in two places. An ``api`` bound is the
    opposite: this service applies it, so the number is here.
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
        assert bound.measured in ("wire", "value", "items"), (
            f"{bound.route_id}/{bound.path} declares an unknown unit {bound.measured!r} — three "
            f"different questions look alike as integers, and one spent a count as bytes"
        )
        if bound.measured == "items":
            assert bound.path.endswith(("members", "recipients", "columnIndexes")), (
                f"{bound.route_id}/{bound.path} is counted in items but is not a list this "
                f"service counts"
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


def test_the_column_choice_cap_is_the_planes_own_result_width():
    """One number, two homes, held equal — the mirror ``Bound.owner`` forbids importing away.

    A request may name at most as many columns as the result it names them from can have, and
    the plane already refuses a result wider than its states can carry. Two independent answers
    to that one question would let the API admit a list describe-results could only refuse, which
    is a request accepted at the door and dead-lettered afterwards.

    The UNIT is asserted beside the number, because they are the pair this table's whole rule
    turns on: a list of 1,500 small integers is a count, and read as a byte budget it would admit
    roughly a hundred and fifty of them.
    """
    from rccommon.config import MAX_RESULT_COLUMNS

    assert bounds.MAX_COLUMN_INDEXES_PER_REQUEST == MAX_RESULT_COLUMNS
    declared = bounds.bound_for("resultsConversion.enqueue", "columnIndexes")
    assert declared is not None
    assert declared.max_bytes == MAX_RESULT_COLUMNS
    assert declared.measured == "items"
    assert declared.enforced_at == "api", (
        "a verb bound would be applied after the Pipe had already had to start an execution "
        "with the list on it, which is the thing the chain is measured against"
    )


def test_the_member_cap_MIRRORS_the_fleets_existing_derivation():
    """One question, one answer — held against the copy that already existed.

    The add-members verb's capacity was already derived, in ``transfer_reader``, from the same
    60-second ceiling: per-member round trips PLUS the per-roster-member fan-out, which a simpler
    model drops. A second derivation written here came out at 100 against its 44, and the two
    would have disagreed silently — the API admitting a request the operator CSV path already
    refuses as unable to finish inside the verb's timeout.

    Mirrored rather than imported because ``transfer_reader`` is a function module, not a shared
    layer, and this service cannot import it. The mirror is what makes the copy safe.
    """
    reader = _transfer_reader_constants()

    assert reader["MAX_MEMBERS_PER_MESSAGE"] == bounds.MAX_MEMBERS_PER_REQUEST, (
        f"the API admits {bounds.MAX_MEMBERS_PER_REQUEST} members per request and the operator "
        f"path derives {reader['MAX_MEMBERS_PER_MESSAGE']} — two answers to one question, and the "
        f"looser one lets a request through that cannot finish"
    )


def test_the_member_bound_is_a_COUNT_because_a_byte_bound_cannot_be_one():
    """The unit matters here more than the number, and getting it wrong bounded nothing.

    Usernames are 3 to 63 characters, so an allowance sized for full-length names admits many
    times more short ones — measured, roughly two thousand against a cap of forty-four. A count
    is the only unit that expresses "how many members will this verb process".
    """
    bound = bounds.bound_for("sharedSpace.enqueue", "payload.members")
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "sharedSpace.enqueue")
    body = _smallest_valid_body(route)

    assert bound is not None and bound.measured == "items"

    body["payload"] = {"members": ["abc"] * (bounds.MAX_MEMBERS_PER_REQUEST + 1)}
    breached = bounds.over_bound(route, body)

    assert breached is not None and breached.path == "payload.members", (
        "a roster one over the cap, of the shortest legal names, is not refused — which is exactly "
        "what a byte bound did here"
    )

    body["payload"] = {"members": ["a" * 63] * bounds.MAX_MEMBERS_PER_REQUEST}

    assert bounds.over_bound(route, body) is None, (
        "a full-length roster AT the cap is refused, so the count bound has become a byte bound "
        "by another name"
    )


def _transfer_reader_constants() -> dict:
    """The shared-space transfer reader's module-level numbers, parsed rather than imported.

    Parsed because importing a function module from a test drags its whole environment in, and
    because the value wanted is a literal the module computes at import — reading it with ``ast``
    is the same answer without the dependency.

    **Only arithmetic over names already resolved is evaluated**, decided by walking the node
    types rather than by attempting it and catching what fails. A blind ``except`` here would make
    an assignment this cannot read indistinguishable from one that is not there, and the caller's
    whole purpose is to notice when a constant it mirrors has moved.

    Args:
      None.

    Returns:
      The module's numeric constants by name. Floats are kept as well as integers: the
      derivation this mirrors multiplies its ceiling by a fraction, and dropping the fraction
      leaves the constant that depends on it unresolvable.

    Raises:
      None.
    """
    source = (REPO / "lambdas" / "shared-space-transfer-reader" / "transfer_reader.py").read_text()
    namespace: dict[str, float] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not _is_arithmetic(node.value, namespace):
            continue
        value = eval(  # noqa: S307
            compile(ast.Expression(node.value), "<transfer_reader>", "eval"), {"int": int}, dict(namespace)
        )
        if isinstance(value, (int, float)):
            namespace[target.id] = value
    return namespace


def _is_arithmetic(node: ast.expr, known: dict) -> bool:
    """Whether an expression is arithmetic over numbers and names already resolved.

    Args:
      node: The expression to judge.
      known: The names resolved so far.

    Returns:
      True if evaluating it can only do arithmetic.

    Raises:
      None.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float))
    if isinstance(node, ast.Name):
        return node.id in known
    if isinstance(node, ast.UnaryOp):
        return _is_arithmetic(node.operand, known)
    if isinstance(node, ast.BinOp):
        return _is_arithmetic(node.left, known) and _is_arithmetic(node.right, known)
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and not node.keywords
            and all(_is_arithmetic(argument, known) for argument in node.args)
        )
    return False


def test_the_add_members_timeout_is_the_number_terraform_DEPLOYS():
    """The premise under the mirrored member cap, held against the Terraform.

    The derivation this file mirrors charges the add-members verb's ceiling. That ceiling is a
    row in the plane's Terraform verb map, not a constant either module can see, so a change to it
    would invalidate a number in two places and go unnoticed in both.

    The row is matched at the start of a line and must be the only one, so a commented-out old
    row or a duplicate left by an edit cannot stand in for the number Terraform deploys.
    """
    plane_tf = (REPO / "infra" / "plane-shared-spaces.tf").read_text()
    rows = re.findall(
        r'^[^\S\n]*"add-members"\s*=\s*\{[^}\n]*\btimeout\s*=\s*(\d+)', plane_tf, re.MULTILINE
    )

    assert len(rows) == 1, f"the shared-space verb map has {len(rows)} add-members rows, expected one"
    assert int(rows[0]) == ADD_MEMBERS_TIMEOUT_SECONDS, (
        "add-members deploys a different timeout, so the mirrored member cap is derived from the "
        "wrong number"
    )
    assert _transfer_reader_constants()["ADD_MEMBERS_TIMEOUT_SECONDS"] == ADD_MEMBERS_TIMEOUT_SECONDS, (
        "the derivation this file mirrors charges a different ceiling than the one deployed"
    )


def test_the_request_id_bound_refuses_no_id_the_queue_would_take():
    """The bound is the CHAIN's, and it must not become a second, tighter identity rule.

    Nine routes make the caller's id the deduplication key verbatim, and ``_checked`` accepts any
    128 printable-ASCII characters — quotes and backslashes among them, each of which serializes to
    two bytes. A bound set at the plain length would refuse an id the queue accepts, which is a
    new refusal wearing a measurement's clothes.
    """
    from cpcommon.config import FIFO_KEY_RE, MAX_FIFO_KEY_CHARS

    worst = '"' * MAX_FIFO_KEY_CHARS

    assert FIFO_KEY_RE.fullmatch(worst), "the queue's own character class no longer admits a quote"
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


#: What kind of field each name-shape is, and therefore which constant its bound must be. The
#: table is what makes a single mis-wired row visible: swapping one path's constant for another
#: real one — a destination prefix bounded by the identifier rule, say — is an eightfold-tighter
#: bound that refuses legitimate requests, and every other guard here passes on it, because each
#: only asks whether SOME bound resolves.
_KIND_BY_SUFFIX = (
    ("requestId", "MAX_REQUEST_ID_BYTES", "wire"),
    ("archiveId", "MAX_REQUEST_ID_BYTES", "wire"),
    ("archiveName", "MAX_ARCHIVE_NAME_BYTES", "wire"),
    ("submittedAt", "MAX_TIMESTAMP_BYTES", "wire"),
    ("location", "MAX_S3_KEY_BYTES", "value"),
    ("prefix", "MAX_S3_KEY_BYTES", "value"),
    ("key", "MAX_S3_KEY_BYTES", "value"),
    ("bucket", "MAX_BUCKET_NAME_BYTES", "wire"),
    ("space", "MAX_IDENTIFIER_BYTES", "wire"),
    ("name", "MAX_IDENTIFIER_BYTES", "wire"),
    ("database", "MAX_IDENTIFIER_BYTES", "wire"),
    ("table", "MAX_IDENTIFIER_BYTES", "wire"),
    ("queryExecutionId", "MAX_IDENTIFIER_BYTES", "wire"),
    ("format", "MAX_IDENTIFIER_BYTES", "wire"),
    ("intervalUnit", "MAX_IDENTIFIER_BYTES", "wire"),
    ("id", "MAX_IDENTIFIER_BYTES", "wire"),
    ("newOwner", "MAX_IDENTIFIER_BYTES", "wire"),
    ("members[]", "MAX_IDENTIFIER_BYTES", "wire"),
    ("range[]", "MAX_IDENTIFIER_BYTES", "wire"),
    ("values[]", "MAX_PARTITION_VALUE_BYTES", "value"),
)


def test_each_bound_carries_the_constant_its_KIND_of_field_calls_for():
    """The per-row wiring, which every other guard in this file is blind to.

    They all ask whether a path resolves to SOME bound. None asks whether it is the right one, so
    a row pointing at a neighbouring constant — or raised to a billion, which removes the bound in
    all but name — passes them. Measured before this existed: 37 of 68 single-row plants survived
    the whole battery.

    **The UNIT is checked as well as the number**, because it is the axis this whole spec turns on
    and it was the half nothing held: ``space.prefix`` could be flipped from the value's own bytes
    to the serialized form with the entire suite green, which is exactly the mistake file-ops
    shipped — a key bounded on its escaped size refuses a third of what S3 allows.

    The mapping is by name-shape because that is what a reader checks a row against anyway: a
    field called ``destination.prefix`` is a key, and a key is bounded by S3's key length. A row
    whose leaf name matches no shape here is skipped rather than guessed at, and those are listed
    so the skip cannot quietly grow.

    **What this is not**: a fence against a two-place edit. Retuning a row AND its entry here
    together passes, for the four leaves that appear on exactly one row — ``newOwner``, ``id``,
    ``table`` and ``archiveId``. The ones that appear on several are self-anchoring, because
    retuning the table reddens the other rows sharing the leaf. And ``MAX_BUCKET_NAME_BYTES``
    happens to equal ``MAX_IDENTIFIER_BYTES``, so a bucket row wired to the identifier constant is
    invisible here — both are 63 characters plus quotes, and the two would have to diverge before
    this could tell them apart. What it catches is the single mis-wired row, which is the mistake
    that actually happened.

    **A list and its elements are different rows and must stay distinguishable**: the leaf keeps
    its ``[]``, so ``payload.members`` (a count of people) and ``payload.members[]`` (one username)
    do not collapse onto one expectation. Stripping it made them collide, which would have let
    either take the other's constant.
    """
    unchecked = []
    for bound in bounds.FIELD_BOUNDS:
        if bound.enforced_at != "api":
            continue
        leaf = bound.path.rsplit(".", 1)[-1]
        kind = next((row for row in _KIND_BY_SUFFIX if leaf == row[0]), None)
        if kind is None:
            unchecked.append(bound.path)
            continue
        _, expected, unit = kind

        assert bound.max_bytes == getattr(bounds, expected), (
            f"{bound.route_id}/{bound.path} is a {leaf!r} and carries {bound.max_bytes}, but that "
            f"kind of field is bounded by {expected} = {getattr(bounds, expected)}"
        )
        assert bound.measured == unit, (
            f"{bound.route_id}/{bound.path} is a {leaf!r} measured in {bound.measured!r}, not the "
            f"{unit!r} that kind of field is stated in — and the unit is the axis this whole rule "
            f"turns on: a key bounded on its serialized form refuses a third of what S3 allows"
        )

    assert sorted(set(unchecked)) == [
        "columnIndexes",
        "partitionKeys",
        "partitionKeys[].range",
        "partitionKeys[].values",
        "payload.members",
    ], (
        f"the set of paths this rule cannot judge by name has changed: {sorted(set(unchecked))}. "
        f"All five are CONTAINERS, whose bound is a capacity rather than a kind of value — a "
        f"sixth entry means a leaf has slipped out of the rule."
    )


def test_a_wire_bound_charges_the_escaping_the_API_actually_sends():
    """The measurement `over_bound` makes, pinned — because getting it wrong is this spec's bug.

    file-ops counted its selection with non-ASCII left literal while the API escapes it, and that
    divergence hid a live overshoot. The same mistake here would be invisible: switching
    ``over_bound`` to ``ensure_ascii=False`` passed every other test in this file.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "sharedSpace.enqueue")
    bound = bounds.bound_for(route.id, "space")
    accented = "é" * ((bound.max_bytes - 2) // 6)

    assert len(accented.encode("utf-8")) * 3 == len(json.dumps(accented).encode("utf-8")) - 2, (
        "a two-byte character no longer costs six serialized bytes, so this fixture is not "
        "measuring the divergence it exists for"
    )

    body = {**_smallest_valid_body(route), "space": accented + "éé"}

    assert bounds.over_bound(route, body) is not None, (
        "an accented value over the bound once escaped is not refused, so this bound is being "
        "measured on the literal form and not on what the API sends"
    )


def test_a_bound_applies_to_EVERY_element_of_a_list_not_the_first():
    """Four bounds sit under a list, and reading only the first element would miss all of them.

    Measured: reducing ``_values`` to ``value[:1]`` left 570 tests green.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    bound = bounds.bound_for(route.id, "source.items[].key")
    body = _smallest_valid_body(route)
    body["source"]["items"] = [
        {"kind": "file", "key": "a"},
        {"kind": "file", "key": "b"},
        {"kind": "file", "key": "k" * (bound.max_bytes + 1)},
    ]

    breached = bounds.over_bound(route, body)

    assert breached is not None and breached.path == "source.items[].key", (
        "an over-long key on the THIRD item is not refused, so only the first element of each "
        "list is being measured"
    )


def test_the_LARGEST_legal_body_of_every_route_is_accepted():
    """The positive control the smallest-body one cannot be.

    ``_smallest_valid_body`` omits every optional field and every container, so a bound pinned
    absurdly tight on one of those is invisible to it. Measured: pinning
    ``tableBuild.refresh/partitionKeys[].range`` to a single byte refused every refresh request
    that declares any partition key — an empty list serializes to two bytes, so nothing legal got
    through — and the whole suite stayed green.

    The body comes from the fleet factory, which builds each field AT its bound, so this asserts
    the round trip the product depends on: what the bounds admit, the bounds do not then refuse.
    """
    sys.path.insert(0, str(REPO / "lambdas"))
    from test_request_size_chain import FILLS, worst_case_body

    for route in contract.ENQUEUE_ROUTES:
        for fill in FILLS:
            body = worst_case_body(route, fill)
            breached = bounds.over_bound(route, body)

            assert breached is None, (
                f"{route.id}'s largest legal body at {fill!r} is refused by its own "
                f"{breached.path} bound — the bounds and the worst case they define disagree, so "
                f"one of them refuses a request the other calls legal"
            )


def test_every_AXIS_of_a_bound_is_covered_by_some_guard():
    """The structural close on a class of defect three review rounds kept finding.

    ``Bound`` has several independent axes, and each round found a guard checking some of them:
    the path resolved but the number was unchecked; the number was checked but the unit was not;
    the unit was checked but only where a leaf matched. Closing instances one at a time is what
    made it recur, because the shape of the table invites it — nothing said which axes were
    covered, so a new one arrived uncovered by default.

    This asserts the axes themselves. Adding a field to ``Bound`` fails here until it is either
    checked by a named guard or recorded as deliberately unchecked with a reason, which turns the
    next instance of this class into a red test rather than a fourth review finding.
    """
    covered = {
        "route_id": "the population guard walks the contract and requires each path to be declared",
        "path": "same guard; and the per-kind guard reads the leaf to decide what it should be",
        "max_bytes": "the per-kind guard, against the constant that kind of field calls for",
        "measured": "the per-kind guard, in the same loop — the axis the whole spec turns on",
        "enforced_at": "the api/verb invariant, which also pins what each side may carry",
        "owner": "the same invariant, plus a guard that every named constant resolves",
        "budget": "unchecked BY DESIGN: it is the sentence a human re-derives the number from, "
        "and a test that asserted its wording would pin prose rather than meaning",
    }
    declared = {field.name for field in dataclasses.fields(bounds.Bound)}

    assert declared == set(covered), (
        f"Bound's axes and the ones some guard covers have diverged — uncovered: "
        f"{sorted(declared - set(covered))}; covered but gone: {sorted(set(covered) - declared)}. "
        f"An axis nothing checks is how the last three review rounds each found a different half "
        f"of one table going unguarded."
    )
