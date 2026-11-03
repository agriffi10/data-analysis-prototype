"""Entry point for the portal API: one span per request, and a name on the wire for every fault.

The function itself decides nothing. It reads the method, the path and the headers out of the
event, hands them to the router, and hands whatever comes back to the gateway. What it adds is
the two things that must wrap EVERY request rather than every route: the span, and the conversion
of an unpredicted fault into a code the contract declares.

**The decorators are ordered, and the order is load-bearing.** Tracing goes on the inside so the
span sees a raise and records it with its stack; the conversion goes on the outside so the caller
still receives an envelope rather than a bare gateway 500. Swap them and every failed request ends
its span successfully, and the fault is recorded nowhere.

The pipeline this rides on has a silent failure mode — a matrix row that is not added, an
environment that is missing a key. Both pass every offline gate: ``conftest.py`` puts the shared
roots on ``sys.path`` so imports resolve in tests, and pointing a function at an image succeeds
against one that cannot import what it needs. Only a real invocation sees it, which is why the first
invocation after a deploy is a live check rather than a formality.

The event is API Gateway's payload format 2.0, and the method and path come from
``requestContext.http`` rather than the top-level ``rawPath``. At the empty API mapping this API
uses, the two agree — so this is a choice about which field stays correct if the mapping ever
gains a key, not a live bug being avoided. AWS documents ``rawPath`` as the field that does NOT
carry the mapping value, so reading it would be the one that changes meaning under a non-empty
key. Stated because a reason that reads false to whoever checks it is worse than none.

Attributes:
  SERVICE: The service name every log record from this function carries.
  UNPARSEABLE_BODY: What a body that is not JSON becomes. A distinct value rather than None, so a
    route declaring no request body refuses arbitrary bytes instead of ignoring them.
  Entry: What an entry point looks like, so the fault-converting decorator below is typed rather
    than passing an untyped callable through and answering ``Any`` to its caller.
  MAX_STACK_BYTES: Imported for the one call below. It is a plain constant with no environment
    read behind it, deliberately — this ``init`` runs at module scope, so a required value read
    here would be a cold-start failure that no test and no deploy can see.
"""

import functools
from collections.abc import Callable
from typing import Any

Entry = Callable[[dict[str, Any], object], dict[str, Any]]

import json

from apicommon import errors
from apicommon.config import MAX_STACK_BYTES
from cpcommon import observability
from router import route

SERVICE = "api"

UNPARSEABLE_BODY = object()

observability.init(service=SERVICE, max_stack_bytes=MAX_STACK_BYTES)


def envelope_faults(fn: Entry) -> Entry:
    """Gives an unpredicted fault a name on the wire, from OUTSIDE the span.

    **The ordering is the whole point, and it is why this is a decorator rather than a try block
    in the function below.** A span records a failure only if the function it wraps actually
    raises, so a catch one frame in would end every failed request successfully and the fault
    would be recorded nowhere — with no stack, which is the only thing an unpredicted fault leaves
    behind. Applied outside the tracing decorator, the span sees the raise and records it, and the
    caller still receives a code the contract declares rather than a bare gateway 500 carrying
    nothing.

    Args:
      fn: The traced entry point.

    Returns:
      The wrapped entry point.

    Raises:
      None.
    """

    @functools.wraps(fn)
    def wrapper(event: dict[str, Any], context: object) -> dict[str, Any]:
        """Runs the request, converting an unmapped fault into the envelope.

        The detail names the exception's TYPE and never its message, because a message is where a
        bucket name, a key, a role ARN or a caller's own value ends up.

        Args:
          event: The API Gateway payload-format-2.0 request.
          context: The Lambda context object.

        Returns:
          The response, always envelope-shaped.

        Raises:
          None. Every failure leaves as a declared code.
        """
        try:
            return fn(event, context)
        except Exception as exc:  # noqa: BLE001
            request_id = str(event.get("requestContext", {}).get("requestId", ""))
            return errors.internal_error(exc, request_id)

    return wrapper


@envelope_faults
@observability.traced("request")
def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Answers one HTTP request, inside the span.

    A malformed event — one carrying no ``requestContext.http`` — is routed rather than raised on,
    because the router's own answer, a 401 since it carries no credential, is better than a
    traceback for something that cannot reach this function through the API anyway. Two callers
    are not the API: the deploy's cold-start probe, whose ``{}`` is refused 401, and the daily
    keep-warm rule, which sends a health-route event.

    The headers are handed to the router whole and the raw event is not. The query string and the
    body DO leave this function now — the object routes take ``{space, key}`` and cannot work
    otherwise — but they leave it as data the router **validates against the route's declaration**
    before any handler sees them, and they never carry an identity anywhere.

    **This used to say the query and the body never leave, and that sentence was the guarantee.**
    It is not any more, and the replacement is named rather than implied: a handler is given
    ``acting_as``, built from verified claims, and can assemble no other; ``routes/`` is swept for
    any read of ``event`` or ``headers``; and a test asserts the resolved identity is unchanged
    against a body and a query each naming a different user. Shape no longer forbids a handler
    reading a caller-stated username — those three do.

    Args:
      event: The API Gateway payload-format-2.0 request.
      context: The Lambda context object, unused.

    Returns:
      The payload-format-2.0 response for that request.

    Raises:
      Exception: Whatever a route raised that the failure mapping does not recognise. Deliberately
        not caught INSIDE the span: a fault with no defined answer must reach it, because the span
        is what records the failure and captures its stack. Caught immediately outside instead,
        where it becomes the envelope's InternalError.
    """
    context_block = event.get("requestContext", {})
    http = context_block.get("http", {})
    method = str(http.get("method", "")).upper()
    path = str(http.get("path", ""))
    headers = event.get("headers") or {}
    return route(
        method,
        path,
        headers,
        str(context_block.get("requestId", "")),
        _parsed_body(event),
        event.get("queryStringParameters") or {},
    )


def _parsed_body(event: dict[str, Any]) -> object:
    """Parses the request body, for the router to check against the route's declared type.

    Returns the SENTINEL for a body that is not JSON at all, rather than None: an absent body and
    an unparseable one are different facts, and answering the same for both would let a route
    declaring no body accept any bytes a caller sent.

    Args:
      event: The API Gateway payload-format-2.0 request.

    Returns:
      The parsed body, None when there is none, or ``UNPARSEABLE_BODY``.

    Raises:
      None.
    """
    raw = event.get("body")
    if not isinstance(raw, str) or raw.strip() == "":
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return UNPARSEABLE_BODY

