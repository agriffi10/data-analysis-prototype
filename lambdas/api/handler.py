"""Placeholder entry point for the portal API — proves the pipeline, serves no business logic.

This function performs **no AWS call**, holds **no session**, and resolves **no identity**. It
answers ``GET /healthz`` and 404s everything else. Every one of those absences is asserted by a
test, because each is a later spec's work and an early arrival would be invisible: a data-plane
grant added here applies green and is only wrong later.

It is not inert, and that is why it is built before anything needs it. The arc leans on a Lambda
pipeline whose failure mode is silent — a layer that is not attached, a matrix row that is not
added, an environment that is missing a key. All three pass every offline gate: ``conftest.py`` puts
the layer on ``sys.path`` so imports resolve in tests, and ``update-function-code`` succeeds against
a function that cannot import what it needs. Only a real invocation sees it. Shipping the placeholder
now means the first spec with something to lose is not also the first to exercise the pipeline.

The event is API Gateway's payload format 2.0, and the method and path come from
``requestContext.http`` rather than the top-level ``rawPath``. At the empty API mapping this API
uses, the two agree — so this is a choice about which field stays correct if the mapping ever
gains a key, not a live bug being avoided. AWS documents ``rawPath`` as the field that does NOT
carry the mapping value, so reading it would be the one that changes meaning under a non-empty
key. Stated because a reason that reads false to whoever checks it is worse than none.

Attributes:
  SERVICE: The service name every log record from this function carries.
"""

from typing import Any

from cpcommon import observability
from router import route

SERVICE = "api"

observability.init(service=SERVICE)


@observability.traced("request")
def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Answers one HTTP request.

    A malformed event — one carrying no ``requestContext.http`` — is routed rather than refused,
    because the router's own 404 is a better answer than a traceback for something that cannot
    reach this function through the API anyway.

    Args:
      event: The API Gateway payload-format-2.0 request.
      context: The Lambda context object, unused.

    Returns:
      The payload-format-2.0 response for that request.

    Raises:
      None.
    """
    http = event.get("requestContext", {}).get("http", {})
    method = str(http.get("method", "")).upper()
    path = str(http.get("path", ""))
    return route(method, path)
