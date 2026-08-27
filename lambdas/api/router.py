"""Route table for the portal API, and the gate every route but one passes through.

API Gateway sends every request to one integration through a ``$default`` route, which means the
route table lives here rather than in the API's configuration. That is the arc's decision and not
an accident of the placeholder: a per-route integration would put the route list in two places, and
the authorization below resolves a principal once, before dispatch.

**Deny by default.** A principal is resolved before any handler is invoked, and a route that has
not declared itself public does not run — including a route that does not exist, which is refused
as unauthenticated rather than reported as absent. The distinction matters both ways: a router
that defaults to public passes every other test in this module, because every other test declares
its route; and a 404 to an unauthenticated caller tells them which paths exist.

**The gate is a module this calls, not logic written here.** The target environment splits the two
— a Lambda authorizer decides, a worker serves — and what makes that a wiring change rather than a
rewrite is that the verifier has no dependency on this file.

**This module emits no CORS header of any kind, and that is a rule rather than an omission.** CORS
is configured on the API. AWS documents that an HTTP API with a CORS configuration *ignores* CORS
headers returned by the backend integration, so a header emitted here would not reach the browser —
but the rule stands on its own ground: two places able to answer the same question is how they come
to disagree, and the one that would win is not the one a reader is looking at.

Attributes:
  HEALTH_PATH: The one path with a handler of its own and no credential.
  PUBLIC_ROUTES: Every route reachable without a token. Exactly one, and it returns nothing
    user-identifying — a health check that needed a token could not be used by a load balancer.
  ROUTES: Method and path to the handler serving it. A route absent from here does not run, and
    a route present here runs only for a caller who has been identified.
  JSON_CONTENT_TYPE: The content type every response carries, success or not.
  MAX_ECHOED_CHARS: How much of a caller-supplied method or path travels anywhere — into a
    refusal body, and into the log record's ``route`` field. The second is easy to forget and is
    the one that keeps costing: the response is obviously caller-facing, while a log field reads
    as internal, so an unbounded path lands whole in the operator store and is billed, retained
    and searched forever.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from apicommon import errors, identity, planes, principal
from apicommon.config import ConfigError
from apicommon.context import RequestContext
from cpcommon import observability
from cpcommon.auth import AuthError, VerifierUnavailable
from cpcommon.observability import build_version
from routes.identity_self import identity_self
from routes.whoami import whoami

HEALTH_PATH = "/healthz"
JSON_CONTENT_TYPE = "application/json"
MAX_ECHOED_CHARS = 128

PUBLIC_ROUTES = frozenset({("GET", HEALTH_PATH)})

ROUTES: dict[tuple[str, str], Callable[[RequestContext], dict[str, Any]]] = {
    ("GET", "/_auth/whoami"): whoami,
    ("GET", "/_identity/self"): identity_self,
}


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    """Builds an API Gateway payload-format-2.0 response.

    The body is SERIALIZED here rather than handed over as an object. API Gateway infers a
    response only when the function returns JSON and returns no ``statusCode``; the moment a
    status is set, the envelope is read literally and ``body`` must be a string. An object there
    is a malformed proxy response — a 500 the caller sees and no offline assertion does, because
    a dict body is still perfectly serializable.

    Args:
      status: The HTTP status code.
      body: The object to serialize into the response body.

    Returns:
      The payload-format-2.0 response dict, body already serialized.

    Raises:
      None.
    """
    return {
        "statusCode": status,
        "headers": {"content-type": JSON_CONTENT_TYPE},
        "body": json.dumps(body),
    }


def _health() -> dict[str, Any]:
    """Reports that the function is running, and which build it is.

    The version comes from ``cpcommon.observability.build_version``, which reads the stamp that
    travels in the deployment package. It is deliberately not an environment variable: Terraform
    owns the environment map and would either race the code deploy or revert it, so an env-borne
    version would name the last infrastructure commit rather than the running code.

    Args:
      None.

    Returns:
      A 200 response carrying the status and the build stamp.

    Raises:
      None.
    """
    return _response(200, {"status": "ok", "version": build_version()})


def _not_found(method: str, path: str) -> dict[str, Any]:
    """Refuses a path this router does not serve, for a caller who has been identified.

    Only reachable after authentication, deliberately: an unidentified caller gets the same 401
    whatever path they ask for, so this cannot be used to learn which routes exist.

    Both values are caller-controlled and are echoed back, so both are truncated. The body is
    served as JSON and never as HTML, so this is a size bound rather than an escaping one — a
    request line is not a place to let an arbitrary payload round-trip.

    Args:
      method: The request's HTTP method.
      path: The request's path.

    Returns:
      A 404 response naming what was not found, with both values bounded.

    Raises:
      None.
    """
    return _response(
        404,
        {
            "error": "not_found",
            "method": method[:MAX_ECHOED_CHARS],
            "path": path[:MAX_ECHOED_CHARS],
        },
    )


def _refuse(reason: str, route: str, request_id: str) -> dict[str, Any]:
    """Emits the refusal record and returns the one 401.

    The record carries a fixed reason code, the route and the request id — and no token, no
    Authorization header, no raw event and no email. The caller learns none of it.

    Args:
      reason: The fixed literal naming which check refused.
      route: The method and path asked for.
      request_id: The gateway's id for this request.

    Returns:
      The 401 response.

    Raises:
      None.
    """
    observability.warning(
        "request refused", reason=reason, route=route, request_id=request_id
    )
    return errors.unauthenticated()


def route(
    method: str,
    path: str,
    headers: Mapping[str, str] | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Identifies the caller, then dispatches.

    A misconfiguration and an unreachable provider are answered with a server fault and NEVER
    with a 401. Neither says anything about the caller's token: one is this API misconfigured,
    the other is the provider not answering. Refusing them as unauthenticated would send every
    user through a token refresh that cannot help, and would present an outage as a login problem.

    **The credential plane is reset on the way IN, before anything else happens here.** A warm
    container does not give each invocation a fresh context, so a route key left behind by the
    last request would still be readable by this one — and if that route declared the API plane
    and this one did not, this one reaches the execution role and succeeds. Resetting on the way
    out alone is not enough, because every path that skips the cleanup leaves the previous value
    in place. The reset below runs before the public-route check, so even a request that never
    reaches dispatch starts from a sentinel that authorizes nothing.

    **A failure a route raises is classified, never flattened.** A denial from AWS is the
    isolation model working and is answered 403; an identity this API cannot assume is a fault on
    this side and is answered 5xx. Anything else keeps rising, so an unexpected failure is
    recorded by the span rather than dressed up as a refusal that says something untrue about it.

    Args:
      method: The request's HTTP method, uppercased by the caller.
      path: The request's path, without the stage or query string.
      headers: The request's headers, the only place a credential is read from.
      request_id: The gateway's id for this request, for the log record.

    Returns:
      The response for that method and path.

    Raises:
      AttributeError: If ``headers`` is not a mapping of strings.
      TypeError: If the method or path is not a string.

      Both are fail-closed and neither can reach a handler, so they surface as a gateway error
      that discloses nothing. They are named rather than claimed absent because a shape the
      type contract forbids is still a shape a caller can construct.
    """
    planes.begin_request()

    asked_for = f"{method[:MAX_ECHOED_CHARS]} {path[:MAX_ECHOED_CHARS]}"
    if (method, path) in PUBLIC_ROUTES:
        return _health()

    try:
        caller = principal.resolve(headers or {})
        acting_as = identity.for_request(caller)
    except AuthError as exc:
        return _refuse(str(exc), asked_for, request_id)
    except (ConfigError, VerifierUnavailable) as exc:
        observability.error(
            "request could not be served",
            reason=type(exc).__name__,
            route=asked_for,
            request_id=request_id,
        )
        return errors.server_fault()

    handler = ROUTES.get((method, path))
    if handler is None:
        return _not_found(method, path)

    planes.begin_dispatch((method, path))
    try:
        return _response(
            200, handler(RequestContext(caller, acting_as, asked_for, request_id))
        )
    except Exception as exc:
        refusal = errors.for_exception(exc)
        if refusal is None:
            raise
        observability.warning(
            "request refused", reason=type(exc).__name__, route=asked_for, request_id=request_id
        )
        return refusal
    finally:
        planes.end_dispatch()
