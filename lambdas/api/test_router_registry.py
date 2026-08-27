"""Three declarations that must agree, and the guard that fails closed on a fourth answer.

A route is declared in the contract, served from the router's handler map, and reaches its
credentials through the plane derived from that same declaration. What is asserted here is that
none of those can exist without the others — and, where a set equality would now be tautological,
what is asserted instead is the property the equality used to stand for.
"""

import pytest
import router
from apicommon import contract, planes
from conftest import bearer, declare_route

_EXTRA = contract.Route(
    id="registry.extra",
    method="GET",
    path="/v1/registry-extra",
    idempotent=True,
    plane="user",
    request=None,
    response=contract.UserDirectoryResponse,
)


def test_every_declared_route_has_a_handler_and_every_handler_has_a_route() -> None:
    """Set equality, both directions, over two hand-written halves.

    Both failures are real and neither is visible from one side. A route with no handler is a 404
    the contract promises works — the browser is typed against it and the compiler is happy. A
    handler with no route is code the router can never dispatch, which is exactly what deleting a
    route row would otherwise leave behind.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either direction differs.
    """
    declared = {route.id for route in contract.ROUTES}

    assert declared == set(router.HANDLERS), (
        f"declared {sorted(declared)} but the router serves {sorted(router.HANDLERS)}"
    )


def test_a_route_added_to_the_contract_is_reachable_with_no_other_edit() -> None:
    """Dispatch reads the declaration rather than an index built at import.

    The claim is not decorative: an import-time index makes a test route unreachable no matter
    what a test registers, and the failure looks like the route being refused rather than like a
    stale cache.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the added route is not served.
    """
    assert router.route("GET", "/v1/registry-extra", bearer())["statusCode"] == 404

    with declare_route(_EXTRA, lambda context: {"served": True}):
        assert router.route("GET", "/v1/registry-extra", bearer())["statusCode"] == 200

    assert router.route("GET", "/v1/registry-extra", bearer())["statusCode"] == 404


def test_every_declared_route_resolves_to_a_plane() -> None:
    """The plane map covers the route table, in both directions.

    Retained as a REGRESSION TRIPWIRE rather than as the guard, and the difference is worth
    stating plainly. The map is derived from the same declaration it is compared against, so this
    equality cannot fail while the derivation is a straight comprehension — what would break it is
    a derivation that filters. The guarantee the old hand-written table needed a guard for is now
    structural: ``Route.plane`` is a required field, so a route cannot be declared without
    choosing. The half neither of those covers has its own test below.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a declared route resolves to no plane entry.
    """
    assert set(planes.route_planes()) == {route.id for route in contract.ROUTES}


def test_a_plane_value_that_is_neither_of_the_two_is_refused() -> None:
    """The half a set equality can never carry: choosing, but choosing wrongly.

    A typo resolving quietly to user-only is indistinguishable from a correct user-only route,
    and the fail-closed guarantee would be gone with nothing to show for it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an unrecognised plane resolves instead of raising.
    """
    typo = contract.Route(
        id="registry.typo",
        method="GET",
        path="/v1/registry-typo",
        idempotent=True,
        plane="superuser",
        request=None,
        response=contract.UserDirectoryResponse,
    )

    with declare_route(typo, lambda context: {}), pytest.raises(ValueError):
        planes.planes_for("registry.typo")


def test_the_user_plane_route_declares_no_extra_plane() -> None:
    """The ported route reaches S3 as the caller, which is what needs no new IAM at all.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the route acquired the API plane.
    """
    assert planes.planes_for("userDirectory.get") == frozenset()

    route = contract.route_by_id("userDirectory.get")
    assert route is not None
    assert route.plane == "user"
