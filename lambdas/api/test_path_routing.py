"""Path templates: what they match, what they refuse, and what they hand a handler.

Every route until now was addressed by a fixed path, and the object surface deliberately
flattened its identifiers into the query string. The catalog routes name an execution and a
database IN the path, so resolution stops being a string comparison — and the two failures a
templated matcher can have are both silent. A template nobody can match answers 404 to every
caller while the table stays green; two templates that overlap resolve by whichever row was
declared first. Both are refused where a declaration is judged rather than repaired where a
request is matched.

The third silent failure is upstream of all of it: **the gateway hands this function a
percent-DECODED path.** Measured against the deployed API rather than assumed — ``GET /health%7A``
answered 200, having matched ``/healthz``, and ``GET /healthz%20`` answered 401. So the browser
encodes each segment and nothing here decodes.

The consequence is asserted below rather than described, because the obvious guess about it is
wrong: a value carrying a slash does not simply 404. Decoded, it addresses whichever template has
one more segment — and this table holds two such pairs — so it lands on a SIBLING route with the
value truncated, answered 200 with a body of the wrong shape. Nothing on this side can tell that
from a path the caller meant, which is why the value is refused in the browser.
"""

import pytest
import router
from apicommon import contract, planes
from conftest import bearer

CATALOG_PATH_PREFIXES = ("/v1/queries", "/v1/catalog/")


def _catalog_routes() -> list[contract.Route]:
    """Every catalog route, DERIVED from the table rather than listed here.

    A hand-kept list is the thing this is avoiding: a seventh catalog route added later would
    simply not appear in it, and the plane assertion below would pass while saying nothing about
    the new route. Selecting by path prefix means a route lands in the population by being
    declared, which is the only way that assertion can stay true without maintenance.

    Args:
      None.

    Returns:
      The routes serving the query and catalog surfaces.

    Raises:
      None.
    """
    return [
        route
        for route in contract.ROUTES
        if route.path.startswith(CATALOG_PATH_PREFIXES)
    ]


def _route(path: str, method: str = "GET", route_id: str = "test.templated") -> contract.Route:
    """One declared route, for a test that needs a template of its own.

    Args:
      path: The path template.
      method: The HTTP method.
      route_id: The route's id.

    Returns:
      The route.

    Raises:
      None.
    """
    return contract.Route(
        id=route_id,
        method=method,
        path=path,
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=contract.UserDirectoryResponse,
    )


def test_a_templated_route_resolves_and_hands_over_its_segments() -> None:
    """The matcher returns the route AND what the placeholders caught.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the route does not resolve, or the segments are not extracted.
    """
    resolved = contract.route_for("GET", "/v1/queries/abc-123/results")

    assert resolved is not None
    route, found = resolved
    assert route.id == "athena.results"
    assert dict(found) == {"queryExecutionId": "abc-123"}


def test_a_placeholder_never_matches_an_empty_segment() -> None:
    """A doubled slash resolves to no route, rather than to a route holding an empty id.

    An empty identifier reaches botocore as a parameter the caller never typed, and the failure
    that comes back names something nobody asked about.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the empty segment is accepted.
    """
    assert contract.route_for("GET", "/v1/queries//results") is None


def test_a_fixed_path_still_matches_exactly_and_a_trailing_slash_does_not() -> None:
    """The templated matcher is equivalent to the string comparison it replaced.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a fixed route stops resolving, or starts accepting a near miss.
    """
    resolved = contract.route_for("GET", "/v1/user-directory")

    assert resolved is not None
    assert resolved[0].id == "userDirectory.get"
    assert dict(resolved[1]) == {}
    assert contract.route_for("GET", "/v1/user-directory/") is None
    assert contract.route_for("POST", "/v1/user-directory") is None


def test_a_value_carrying_a_slash_reaches_a_SIBLING_route_not_the_one_it_named() -> None:
    """Why the browser refuses such a value instead of letting the server sort it out.

    The gateway decodes before this side sees anything, so a slash the caller encoded and a
    slash the caller typed are the same bytes here. Where a sibling template has one more
    segment — and this table has two such pairs — the request lands on THAT route, with the
    value silently truncated, and is answered 200 with a body of the wrong shape.

    404 would have been survivable. This is not, and it cannot be fixed on this side, which is
    the whole reason the refusal lives in the client.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the resolution stops behaving the way the client's refusal assumes.
    """
    truncated = contract.route_for("GET", "/v1/catalog/databases/alice/tables")
    assert truncated is not None
    assert truncated[0].id == "catalog.tables.list"
    assert dict(truncated[1]) == {"database": "alice"}

    assert contract.route_for("GET", "/v1/catalog/databases/alice/secret") is None


def test_the_generator_and_the_matcher_read_one_template_the_same_way() -> None:
    """The names the emitter publishes are the names the matcher fills.

    The browser is typed against ``path_parameters``' output and the server extracts through
    ``route_for``. If the two read a template differently the mismatch is a runtime 400 nobody
    can see in either language.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any route's declared names differ from what the matcher extracts.
    """
    for route in contract.ROUTES:
        names = contract.path_parameters(route.path)
        filled = route.path
        for name in names:
            filled = filled.replace("{" + name + "}", f"value-for-{name}")

        resolved = contract.route_for(route.method, filled)

        assert resolved is not None, f"{route.id} does not match its own filled template"
        assert set(resolved[1]) == set(names), route.id


@pytest.mark.parametrize(
    "path",
    [
        "/v1/queries/{query-execution-id}",
        "/v1/queries/{}",
        "/v1/queries/{Query}",
        "/v1/queries/{queryExecutionId",
        "/v1/queries/queryExecutionId}",
        "/v1/queries/id-{queryExecutionId}",
    ],
    ids=["dashes", "empty", "capitalised", "unclosed", "unopened", "embedded"],
)
def test_a_malformed_placeholder_is_REFUSED_rather_than_read_as_a_literal(
    monkeypatch, path
) -> None:
    """The refusal exists because the alternative has no symptom.

    A braced segment whose name is malformed can only be read as a literal, and a literal wearing
    braces matches no request anybody sends — so the route 404s forever while the table, the
    generated TypeScript and every type-level check stay green.

    Args:
      monkeypatch: Pytest's patcher.
      path: The malformed template.

    Returns:
      None.

    Raises:
      AssertionError: If the declaration is accepted.
    """
    monkeypatch.setattr(contract, "ROUTES", (*contract.ROUTES, _route(path)))

    with pytest.raises(contract.UnsupportedTypeError, match="malformed path placeholder"):
        contract.check_routes()


def test_a_path_naming_one_parameter_twice_is_refused(monkeypatch) -> None:
    """The second segment would overwrite the first, and the route would never know.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the declaration is accepted.
    """
    monkeypatch.setattr(
        contract, "ROUTES", (*contract.ROUTES, _route("/v1/pairs/{name}/{name}"))
    )

    with pytest.raises(contract.UnsupportedTypeError, match="path parameter twice"):
        contract.check_routes()


def test_two_routes_that_could_match_one_path_are_refused(monkeypatch) -> None:
    """Resolution takes the first row that matches, so an overlap resolves by declaration order.

    Refused outright rather than arbitrated by a precedence rule: a rule saying literals win is a
    second thing to reason about at every future declaration, and it only ever fires in the case
    this makes unreachable.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the overlapping pair is accepted.
    """
    monkeypatch.setattr(
        contract,
        "ROUTES",
        (*contract.ROUTES, _route("/v1/queries/{somethingElse}", route_id="test.overlap")),
    )

    with pytest.raises(contract.UnsupportedTypeError, match="both match"):
        contract.check_routes()


def test_the_overlap_check_does_not_fire_on_a_table_that_is_fine() -> None:
    """Guard-the-guard: an overlap rule that refused everything would also pass every test above.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the shipped table is refused.
    """
    contract.check_routes()


def test_a_templated_route_is_a_404_until_a_handler_serves_it() -> None:
    """The six routes are declared here and served in the next change, and that gap is inert.

    A route the contract declares and the router cannot serve answers exactly what an unknown
    path answers — same status, same body — so this change is invisible to every caller.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a declared-but-unserved route answers anything else.
    """
    unserved = router.route("GET", "/v1/queries/abc-123", bearer(), "rq")
    unknown = router.route("GET", "/v1/nothing-here", bearer(), "rq")

    assert unknown["statusCode"] == 404
    assert unserved["statusCode"] == unknown["statusCode"]
    assert unserved["body"] == unknown["body"]
    assert unserved["headers"] == unknown["headers"]


def test_every_catalog_route_is_declared_on_the_USER_plane() -> None:
    """There is no catalog call this API makes on its own behalf.

    A route reaching the API plane would issue Athena or Glue calls as the execution role — which
    SUCCEEDS, against every user's data, and is the one failure the plane rule exists to stop.

    The population is derived and its size is asserted first: a prefix that stopped matching
    would leave this iterating over nothing and passing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any catalog route declares anything but the user plane.
    """
    found = _catalog_routes()

    assert len(found) == 6, [route.id for route in found]
    for route in found:
        assert route.plane == "user", route.id
        assert planes.planes_for(route.id) == frozenset(), route.id


def test_start_is_the_only_catalog_route_that_may_not_be_retried() -> None:
    """Idempotence is declared per route and never derived from the method.

    Both flags here would be wrong under a method rule: ``athena.stop`` is a POST that may safely
    be repeated — the execution id is in the path, so a repeat cannot stop a different query and
    a second stop on a terminal execution changes nothing — while ``athena.start`` is the billed,
    stateful call that a ``retry: 1`` once turned into two executions 1.1 seconds apart.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the flags do not match.
    """
    flags = {route.id: route.idempotent for route in _catalog_routes()}

    assert flags["athena.start"] is False
    assert flags["athena.stop"] is True
    assert [route_id for route_id, retryable in flags.items() if not retryable] == ["athena.start"]
