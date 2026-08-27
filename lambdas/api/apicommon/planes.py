"""Which credential plane a route may reach for, and the guard that fails closed.

Two planes serve this API. The **user plane** is the caller's own assumed session, and every call
that must be isolation-enforced goes through it. The **API plane** is the function's execution
role, and it carries only what the user is not directly authorized for — the assume-role call
itself today.

**The default is the user plane, because the dangerous direction is one-way.** A user-scoped call
escaping onto the execution role reads every user's data and succeeds; an execution-role call
mistakenly scoped to a user is refused. So a route reaches the API plane only by being named here,
and a route that names nothing gets the less privileged of the two.

**The current route is set at the START of every request, not cleared at the end of one.** That
ordering is the whole safety property and it is easy to get backwards. The Python runtime does not
hand each Lambda invocation a fresh context, so a value left behind by one request is visible to
the next — which is exactly why the structured-logging layer resets its baggage on entry rather
than on exit. Cleanup-on-exit is skipped by any path that does not reach the cleanup: an exception
in the wrong place, a return from an inner frame, a reset token that itself raises. Any one of
those leaves a previous request's route key in place, and the next request on a user-only route
then reaches the API plane and **succeeds** against the execution role. Setting a sentinel first
thing in the router makes every path start from "authorizes nothing", whether or not the last one
finished tidily.

**The plane is DERIVED from the route's own declaration, per call.** It used to be a second
hand-written table equated to the router's by a guard. It is now read from the one place a route
is declared whole, which is stronger than the guard was: a route cannot be added without choosing,
because the field is required to construct one. What the guard could never do — and what is
asserted instead — is refuse a plane value that is neither of the two, which would otherwise
resolve to the less privileged one and quietly delete the fail-closed half.

Per call rather than cached at import, so the table cannot go stale against a route table a test
replaced — and so "adding a route makes it reachable with no other edit" is a claim something can
actually check.

Attributes:
  NO_ROUTE: The sentinel a request starts from. It names no route, so it authorizes nothing — a
    request that has not reached dispatch cannot reach the API plane.
"""

import enum
from contextvars import ContextVar

from . import contract


class Plane(enum.Enum):
    """The two sets of credentials a call in this API can be made with.

    Attributes:
      USER: The caller's own assumed session, carrying their session tags.
      API: The function's execution role.
    """

    USER = "user"
    API = "api"


NO_ROUTE = ""

_CURRENT_ROUTE: ContextVar[str] = ContextVar("current_route", default=NO_ROUTE)


def planes_for(route_id: str) -> frozenset[Plane]:
    """The planes one route may reach BEYOND the user plane.

    The user plane is implicit and never listed, so an empty set means user-only — which is also
    what an unknown route id resolves to, because the dangerous direction is one-way.

    Args:
      route_id: The route's id.

    Returns:
      The extra planes that route declared, empty when it declared none or does not exist.

    Raises:
      ValueError: If the route declares a plane that is neither of the two. Refused rather than
        defaulted: a typo resolving silently to user-only would look identical to a correct
        user-only route, and the fail-closed guarantee would be gone with nothing to show it.
    """
    route = contract.route_by_id(route_id)
    if route is None:
        return frozenset()
    if route.plane == "user":
        return frozenset()
    if route.plane == "api":
        return frozenset({Plane.API})
    raise ValueError(f"{route_id} declares an unknown credential plane: {route.plane!r}")


def route_planes() -> dict[str, frozenset[Plane]]:
    """Every declared route's extra planes.

    Args:
      None.

    Returns:
      Route id to the planes beyond the user plane.

    Raises:
      ValueError: If any route declares an unknown plane.
    """
    return {route.id: planes_for(route.id) for route in contract.ROUTES}


def begin_request() -> None:
    """Resets the current route at the start of an invocation.

    Called before anything else the router does, including before the public-route check, so a
    request that never reaches dispatch still starts from a sentinel rather than from whatever
    the last request in this container left behind.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _CURRENT_ROUTE.set(NO_ROUTE)


def begin_dispatch(route_id: str) -> None:
    """Names the route about to run, so its declaration can be looked up.

    Args:
      route_id: The id of the route this request matched.

    Returns:
      None.

    Raises:
      None.
    """
    _CURRENT_ROUTE.set(route_id)


def end_dispatch() -> None:
    """Returns to the sentinel once a route has finished, however it finished.

    Belt to ``begin_request``'s braces. The entry reset is the load-bearing one; this narrows the
    window within a single request, and it must not be relied on as the only reset.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _CURRENT_ROUTE.set(NO_ROUTE)


def current_route() -> str:
    """Returns the route currently dispatching, or the sentinel.

    Args:
      None.

    Returns:
      The route id, or ``NO_ROUTE`` if no dispatch is in progress.

    Raises:
      None.
    """
    return _CURRENT_ROUTE.get()


def require(plane: Plane) -> None:
    """Refuses a plane the running route did not declare, before any AWS call is made.

    The check is on the way in rather than on the way out, so a violation costs no request and
    reaches no service. A route with no entry, and a request with no dispatch in progress, both
    fall through to the empty set and are refused.

    Args:
      plane: The plane the caller is asking for.

    Returns:
      None.

    Raises:
      PlaneViolationError: If the running route did not declare that plane. Imported HERE rather
        than at module scope, and the reason is structural: the two doors live in the identity
        layer, which imports this module to ask the question, so a module-scope import back would
        be a cycle. The refusal type belongs beside the doors it guards, not beside the table.
    """
    from .identity import PlaneViolationError

    if plane is Plane.USER:
        return
    if plane not in planes_for(_CURRENT_ROUTE.get()):
        raise PlaneViolationError(
            f"the running route did not declare the {plane.value} plane"
        )
