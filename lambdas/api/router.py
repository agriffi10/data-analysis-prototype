"""Dispatch for the portal API, and the gate every route but one passes through.

API Gateway sends every request to one integration through a ``$default`` route, which means the
route table lives in code rather than in the API's configuration. That is the arc's decision and
not an accident: a per-route integration would put the route list in two places, and the
authorization below resolves a principal once, before dispatch.

**The table is the contract's, not this module's.** ``apicommon.contract`` declares each route
whole — id, method, path, credential plane, whether it may be retried — and this module holds only
the map from a route id to the function serving it. A route that exists in one and not the other
is what the registry guard refuses, in both directions: a route with no handler is a 404 the
contract promises works, and a handler with no route is code the router can never reach.

**Resolution reads the contract on every call**, rather than an index built at import. The cost is
a walk of a table with one row per route; what it buys is that "adding a route makes it reachable
with no other edit" is a claim a test can drive, and that a test route cannot be shadowed by a
stale index.

**Deny by default.** A principal is resolved before any handler is invoked, and a route that has
not declared itself public does not run — including a route that does not exist, which is refused
as unauthenticated rather than reported as absent. The distinction matters both ways: a router
that defaults to public passes every other test in this module, because every other test declares
its route; and a 404 to an unauthenticated caller tells them which paths exist.

**A preflight is answered before authentication, and that is not a hole.** ``$default`` matches
every method including OPTIONS, so API Gateway's own CORS responder — which runs only when no
route matches — never sees one. A preflight refused as unauthenticated fails the browser's CORS
check, and every bearer-carrying request then fails as an opaque network error with nothing on the
wire to explain it. The answer carries no credential, discloses nothing, and is the same for a
path that exists and one that does not.

**This module emits no CORS header of any kind, and that is a rule rather than an omission.** CORS
is configured on the API. AWS documents that an HTTP API with a CORS configuration *ignores* CORS
headers returned by the backend integration, so a header emitted here would not reach the browser
— but the rule stands on its own ground: two places able to answer the same question is how they
come to disagree, and the one that would win is not the one a reader is looking at.

Attributes:
  HEALTH_PATH: The one path with a handler of its own and no credential.
  PUBLIC_ROUTES: Every route reachable without a token. Exactly one, and it returns nothing
    user-identifying — a health check that needed a token could not be used by a load balancer.
  PREFLIGHT_METHOD: The method answered before authentication, for the reason above.
  HANDLERS: Route id to the function serving it. The only hand-written half of the dispatch;
    everything else about a route is declared in the contract.
  UUID_RE: What a client-supplied request id must look like to be recorded at all. It is a log
    field the caller controls, so it is bounded in shape as well as in length, and it is never
    used to build a key, a path or a dedup token.
  MAX_ECHOED_CHARS: How much of a caller-supplied method or path travels into the log record. The
    response echoes neither, so this bounds the operator store alone — which is the one that keeps
    costing, because a log field reads as internal and an unbounded path lands there whole, billed
    and retained forever.
"""

import json
import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from apicommon import contract, envelope, errors, identity, planes, principal
from apicommon.config import ConfigError
from apicommon.context import RequestContext
from cpcommon import observability
from cpcommon.auth import AuthError, VerifierUnavailable
from cpcommon.observability import build_version
from routes import (
    athena,
    catalog,
    feature_flags,
    objects_content,
    objects_free_name,
    objects_head,
    objects_list,
    objects_mutate,
    objects_presign,
)
from routes import (
    enqueue as enqueue_routes,
)
from routes.user_directory import user_directory

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

HEALTH_PATH = "/healthz"
PREFLIGHT_METHOD = "OPTIONS"
MAX_ECHOED_CHARS = 128

PUBLIC_ROUTES = frozenset({("GET", HEALTH_PATH)})

HANDLERS: dict[str, Callable[[RequestContext], dict[str, Any]]] = {
    "sharedSpace.enqueue": enqueue_routes.shared_space,
    "notifications.enqueue": enqueue_routes.notifications,
    "tableBuild.create": enqueue_routes.table_build,
    "tableBuild.refresh": enqueue_routes.table_refresh,
    "tableShare.enqueue": enqueue_routes.table_share,
    "dataQuality.enqueue": enqueue_routes.data_quality,
    "fileSend.enqueue": enqueue_routes.file_send,
    "archive.archive": enqueue_routes.archive,
    "archive.restore": enqueue_routes.restore,
    "fileOps.enqueue": enqueue_routes.file_ops,
    "userDirectory.get": user_directory,
    "featureFlags.get": feature_flags.feature_flags,
    "objects.list": objects_list.list_objects,
    "objects.metadata": objects_head.metadata,
    "objects.exists": objects_head.exists,
    "objects.readContent": objects_content.read_content,
    "objects.writeContent": objects_content.write_content,
    "objects.copy": objects_mutate.copy_object,
    "objects.move": objects_mutate.move_object,
    "objects.delete": objects_mutate.delete_object,
    "objects.uploadUrl": objects_presign.upload_url,
    "objects.downloadUrl": objects_presign.download_url,
    "objects.freeName": objects_free_name.free_name,
    "athena.start": athena.start,
    "athena.status": athena.status,
    "athena.results": athena.results,
    "athena.stop": athena.stop,
    "catalog.database.get": catalog.get_database,
    "catalog.tables.list": catalog.list_tables,
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
    return envelope.success({"status": "ok", "version": build_version()})


def _preflight() -> dict[str, Any]:
    """Answers a CORS preflight, before any credential is looked at.

    Empty and identical for every path, so it is not an inventory of which routes exist. The
    allow-origin, allow-headers and allow-methods headers are the API's to add and are deliberately
    absent here.

    Args:
      None.

    Returns:
      An empty 200. Not a 204: one status, one parse path, no body-less response anywhere.

    Raises:
      None.
    """
    return envelope.success({})


def _stamp_correlation(headers: Mapping[str, str], request_id: str) -> None:
    """Fixes this request's correlation key, and records the caller's own id separately.

    **The explicit stamp is the whole point.** The structured-logging layer reads a top-level
    ``requestId`` and then falls back to parsing ``body`` as JSON — and an API Gateway v2 event's
    body IS a JSON string, which for a submit shape carries a browser-supplied ``requestId``. Left
    implicit, this service's correlation key would be a value chosen by the caller. Stamped
    unconditionally, including when the gateway gave none, so the caller's value can never stand.

    Args:
      headers: The request's headers, where the client's own id may be.
      request_id: The gateway's id for this request.

    Returns:
      None.

    Raises:
      None.
    """
    observability.stamp(request_id=request_id)

    supplied = None
    for name, value in (headers or {}).items():
        if name.lower() == "x-request-id":
            supplied = value
            break
    observability.stamp(
        client_request_id=supplied if supplied and UUID_RE.match(supplied) else None
    )


def _answered(response: dict[str, Any], code: str | None = None) -> dict[str, Any]:
    """Records what this request actually answered, then returns it.

    **The span's own status is not the HTTP status**, and conflating them is how this record comes
    to say nothing. Every enveloped failure is RETURNED rather than raised, so the span closes
    successfully for a 401, a 403, a 404 and a 409 alike — a query filtering on the span status
    would find one value for every outcome the API has.

    Args:
      response: The response about to be returned.
      code: The wire code, on a failure. Absent on a success.

    Returns:
      The response, unchanged.

    Raises:
      None.
    """
    observability.stamp(status=response["statusCode"])
    if code is not None:
        observability.stamp(code=code)
    return response


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
    return _answered(errors.unauthenticated(request_id), errors.UNAUTHENTICATED_CODE)


def route(
    method: str,
    path: str,
    headers: Mapping[str, str] | None = None,
    request_id: str = "",
    body: object = None,
    query: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Identifies the caller, then dispatches.

    A misconfiguration and an unreachable provider are answered with a server fault and NEVER with
    a 401. Neither says anything about the caller's token: one is this API misconfigured, the
    other is the provider not answering. Refusing them as unauthenticated would send every user
    through a token refresh that cannot help, and would present an outage as a login problem.

    **The credential plane is reset on the way IN, before anything else happens here.** A warm
    container does not give each invocation a fresh context, so a route id left behind by the last
    request is still readable by this one. A handler is not the exposure — the dispatch below sets
    the id unconditionally before one runs — but every path that returns BEFORE dispatch is: the
    health route, the preflight, an unknown route, and every refusal. Resetting on the way out
    alone does not cover them, because those are the paths most likely to skip the cleanup. The
    reset runs before the public-route check, so a request that never dispatches still starts from
    a sentinel that authorizes nothing.

    **An identity this API cannot RESOLVE is answered here, and that is not a duplicate of the
    classification below.** ``for_request`` runs before dispatch, so a failure it raises never
    reaches the dispatch guard where ``errors.for_exception`` maps it — it would leave ``route()``
    entirely and arrive as a bare ``InternalError`` carrying nothing an operator or the browser can
    act on. Reachable only when memberships are sourced from something that can be unavailable,
    which is why it appears with the source that can be.

    **A failure a route raises is classified, never flattened.** A denial from AWS is the isolation
    model working and is answered 403; an identity this API cannot assume is a fault on this side
    and is answered 5xx. Anything else keeps rising, so an unexpected failure is recorded by the
    span — with its stack — rather than dressed up as a refusal that says something untrue about
    it. The entry point converts it into the envelope's InternalError afterwards, which is the
    only ordering that gets both: a catch here would end the span successfully and the fault
    would be recorded nowhere.

    Args:
      method: The request's HTTP method, uppercased by the caller.
      path: The request's path, without the stage or query string.
      headers: The request's headers, the only place a credential is read from.
      request_id: The gateway's id for this request, for the log record and the envelope.
      body: The parsed request body, checked against the route's DECLARED request type before
        dispatch and then discarded. It reaches the validator and nothing else — a handler holding
        it could read a username the caller asserted, and would pass every test that sends a
        matching token.

    Returns:
      The response for that method and path.

    Raises:
      AttributeError: If ``headers`` is not a mapping of strings.
      TypeError: If the method or path is not a string.
      Exception: Whatever a route raised that the failure mapping does not recognise, re-raised
        rather than flattened.

      The first two are fail-closed and neither can reach a handler, so they surface as a gateway error
      that discloses nothing. They are named rather than claimed absent because a shape the type
      contract forbids is still a shape a caller can construct.
    """
    planes.begin_request()
    _stamp_correlation(headers or {}, request_id)

    asked_for = f"{method[:MAX_ECHOED_CHARS]} {path[:MAX_ECHOED_CHARS]}"
    if method == PREFLIGHT_METHOD:
        return _answered(_preflight())
    if (method, path) in PUBLIC_ROUTES:
        return _answered(_health())

    try:
        caller = principal.resolve(headers or {})
        acting_as = identity.for_request(caller)
    except AuthError as exc:
        return _refuse(str(exc), asked_for, request_id)
    except identity.IdentityUnavailableError as exc:
        observability.error(
            "request could not be served",
            reason=str(exc),
            route=asked_for,
            request_id=request_id,
        )
        return _answered(
            errors.identity_unavailable(request_id), errors.IDENTITY_UNAVAILABLE_CODE
        )
    except (ConfigError, VerifierUnavailable) as exc:
        observability.error(
            "request could not be served",
            reason=type(exc).__name__,
            route=asked_for,
            request_id=request_id,
        )
        return _answered(errors.server_fault(request_id), errors.SERVER_FAULT_CODE)

    resolved = contract.route_for(method, path)
    declared, path_params = resolved if resolved is not None else (None, {})
    handler = HANDLERS.get(declared.id) if declared is not None else None
    if declared is None or handler is None:
        observability.warning(
            "route not served", route=asked_for, request_id=request_id
        )
        return _answered(errors.not_found(request_id), errors.NOT_FOUND_CODE)

    observability.stamp(route_id=declared.id, method=method, actor=caller.username)

    refusal = contract.validate_request(declared, body)
    if refusal is not None:
        observability.warning(
            "request body refused", reason=refusal, route=asked_for, request_id=request_id
        )
        return _answered(envelope.failure(refusal, request_id), refusal)

    refusal = contract.validate_query(declared, query)
    if refusal is not None:
        observability.warning(
            "request query refused", reason=refusal, route=asked_for, request_id=request_id
        )
        return _answered(envelope.failure(refusal, request_id), refusal)

    planes.begin_dispatch(declared.id)
    try:
        return _answered(
            envelope.success(
                handler(
                    RequestContext(
                        caller,
                        acting_as,
                        asked_for,
                        request_id,
                        body,
                        MappingProxyType(dict(query or {})),
                        MappingProxyType(dict(path_params)),
                    )
                )
            )
        )
    except envelope.ApiError as exc:
        observability.warning(
            "request refused", reason=exc.code, route=asked_for, request_id=request_id
        )
        return _answered(
            envelope.failure(exc.code, request_id, exc.detail, exc.params), exc.code
        )
    except Exception as exc:
        classified = errors.for_exception(exc, request_id)
        if classified is None:
            raise
        code = json.loads(classified["body"])["error"]["code"]
        observability.warning(
            "request refused", reason=code, route=asked_for, request_id=request_id
        )
        return _answered(classified, code)
    finally:
        planes.end_dispatch()

