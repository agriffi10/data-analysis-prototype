"""Route table for the portal API — one function serves every path, so routing is internal.

API Gateway sends every request to one integration through a ``$default`` route, which means the
route table lives here rather than in the API's configuration. That is the arc's decision and not
an accident of the placeholder: a per-route integration would put the route list in two places, and
the authorization this arc adds later resolves a principal once, before dispatch.

**This module emits no CORS header of any kind, and that is a rule rather than an omission.** CORS
is configured on the API. AWS documents that an HTTP API with a CORS configuration *ignores* CORS
headers returned by the backend integration, so a header emitted here would not reach the browser —
but the rule stands on its own ground: two places able to answer the same question is how they come
to disagree, and the one that would win is not the one a reader is looking at.

What routes exist today is deliberately almost nothing. The placeholder proves the pipeline — the
deploy matrix, the layer attachment, the environment contract and the log record — and a later spec
replaces the table wholesale.

Attributes:
  HEALTH_PATH: The one path with a handler of its own.
  JSON_CONTENT_TYPE: The content type every response carries, success or not.
  MAX_ECHOED_CHARS: How much of a caller-supplied method or path a refusal echoes back.
"""

import json
from typing import Any

from cpcommon.observability import build_version

HEALTH_PATH = "/healthz"
JSON_CONTENT_TYPE = "application/json"
MAX_ECHOED_CHARS = 128


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
    """Refuses a path this router does not serve.

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


def route(method: str, path: str) -> dict[str, Any]:
    """Dispatches one request to its handler.

    Args:
      method: The request's HTTP method, uppercased by the caller.
      path: The request's path, without the stage or query string.

    Returns:
      The response for that method and path, or a 404 when no route matches.

    Raises:
      None.
    """
    if method == "GET" and path == HEALTH_PATH:
        return _health()
    return _not_found(method, path)
