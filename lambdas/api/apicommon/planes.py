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

Attributes:
  NO_ROUTE: The sentinel a request starts from. It is not a key in the table, so it authorizes
    nothing — a request that has not reached dispatch cannot reach the API plane.
  ROUTE_PLANES: Route key to the planes that route may use BEYOND the user plane. The user plane
    is implicit and never listed; an empty set means user-only. Keyed identically to the router's
    dispatch table so the two can be compared as sets rather than through a transformation, which
    would be one more place to get it wrong. A hand-maintained list rots, so a guard equates the
    two.
"""

import enum
from collections.abc import Mapping
from contextvars import ContextVar


class Plane(enum.Enum):
    """The two sets of credentials a call in this API can be made with.

    Attributes:
      USER: The caller's own assumed session, carrying their session tags.
      API: The function's execution role.
    """

    USER = "user"
    API = "api"


NO_ROUTE = ("", "")

ROUTE_PLANES: Mapping[tuple[str, str], frozenset[Plane]] = {
    ("GET", "/_auth/whoami"): frozenset(),
    ("GET", "/_identity/self"): frozenset(),
}

_CURRENT_ROUTE: ContextVar[tuple[str, str]] = ContextVar("current_route", default=NO_ROUTE)


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


def begin_dispatch(route_key: tuple[str, str]) -> None:
    """Names the route about to run, so its declaration can be looked up.

    Args:
      route_key: The method and path this request matched.

    Returns:
      None.

    Raises:
      None.
    """
    _CURRENT_ROUTE.set(route_key)


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


def current_route() -> tuple[str, str]:
    """Returns the route currently dispatching, or the sentinel.

    Args:
      None.

    Returns:
      The route key, or ``NO_ROUTE`` if no dispatch is in progress.

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
    route_key = _CURRENT_ROUTE.get()
    if plane not in ROUTE_PLANES.get(route_key, frozenset()):
        raise PlaneViolationError(
            f"the running route did not declare the {plane.value} plane"
        )
