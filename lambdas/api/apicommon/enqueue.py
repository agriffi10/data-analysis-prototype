"""The one path to ``SendMessage``, and the one place the caller's raw bearer is read.

Every enqueue route hands its validated payload here. This module stamps what the caller may not —
the identity block, the route's own literals, and, transitionally, the token the plane still
verifies — derives the FIFO keys, checks the result against what the queue will accept, and sends.

A handler builds no message body. That is what keeps the router's premise true at ten routes
rather than one: the bearer never reaches a handler, and the sweep that counts its readers counts
exactly one, here.

Attributes:
  SQS_MAX_MESSAGE_BYTES: What these queues accept for one message body. It is the service default
    rather than the documented maximum, because no queue module sets ``max_message_size``.
  MAX_BEARER_BYTES: The allowance for the transitional token, measured from a real ID token with
    the largest claim set this pool issues rather than guessed. It disappears with the token.
  MAX_IDENTITY_BLOCK_BYTES: The allowance for the identity block at its largest.
  MAX_MESSAGE_BYTES: What a caller's payload may serialize to once everything above is stamped
    onto it. Derived, never written down: a cap applied to the caller's payload alone would admit
    a request the send cannot make. It is measured against the ALREADY-STAMPED body, so the two
    allowances above are reserved twice and roughly 8 KB of real headroom goes unused — the safe
    direction, and the margin covers a token larger than the one that was measured.
  MAX_LOGGED_REQUEST_ID: How much of the caller's own request id reaches a log field. It is
    caller-controlled text on baggage, so it rides every event of the invocation into a store that
    is retained forever — the reason the router bounds the id IT echoes.
"""

import json
from collections.abc import Mapping
from typing import Any

from cpcommon import observability

from . import fifo, identity, identity_block
from .config import queue_url
from .context import RequestContext, reveal
from .contract import EnqueueRoute
from .envelope import ApiError

SQS_MAX_MESSAGE_BYTES = 262_144
MAX_BEARER_BYTES = 8_192
MAX_IDENTITY_BLOCK_BYTES = 512
MAX_MESSAGE_BYTES = SQS_MAX_MESSAGE_BYTES - MAX_BEARER_BYTES - MAX_IDENTITY_BLOCK_BYTES

MAX_LOGGED_REQUEST_ID = 128

_THROTTLE_CODES = frozenset(
    {
        "ThrottlingException",
        "Throttling",
        "RequestThrottled",
        "TooManyRequestsException",
    }
)
_UNAVAILABLE_CODES = frozenset(
    {"ServiceUnavailable", "InternalError", "InternalFailure"}
)


def _clipped(request_id) -> str | None:
    """Bounds the caller's own request id before it becomes a log field.

    Args:
      request_id: The body's request id, or None on the two planes that have none.

    Returns:
      The id, truncated, or None.

    Raises:
      None.
    """
    if not isinstance(request_id, str):
        return None
    return request_id[:MAX_LOGGED_REQUEST_ID]


def _stamped_values(route: EnqueueRoute, ctx: RequestContext) -> dict[str, Any]:
    """The top-level fields the sender writes and the caller may not.

    Each is a value that chooses behaviour rather than describing a request, which is why none of
    them is a caller input: ``mode`` is the difference between archiving and restoring, and
    handing it to a body would hand the caller that branch.

    Args:
      route: The route being served.
      ctx: The request, for the verified actor the shared-space envelope carries advisorily.

    Returns:
      The fields to stamp, whose key set is the route's own declaration.

    Raises:
      None.
    """
    values: dict[str, dict[str, Any]] = {
        "sharedSpace.enqueue": {"schemaVersion": 1, "actor": ctx.principal.username},
        "tableBuild.refresh": {"mode": "refresh"},
        "archive.archive": {"mode": "archive"},
        "archive.restore": {"mode": "restore"},
    }
    return values.get(route.id, {})


def build_message(
    route: EnqueueRoute, ctx: RequestContext, payload: Mapping[str, Any]
) -> dict:
    """Assembles the message one route sends.

    The identity block rides alongside the token rather than replacing it. It is nested under one
    key because on four planes the top-level field named ``actor`` IS the raw token today, so a
    flat verified actor would overwrite the field those planes verify.

    Args:
      route: The route being served.
      ctx: The request, carrying the verified caller and the wrapped bearer.
      payload: The validated request body.

    Returns:
      The message body, ready to serialize.

    Raises:
      None.
    """
    return {
        **dict(payload),
        **_stamped_values(route, ctx),
        route.token_field: reveal(ctx.bearer),
        "identity": identity_block.build(ctx.principal),
    }


def _refuse_if_oversized(body: str) -> None:
    """Refuses a message the queue would not accept, before it is billed for or partly done.

    Measured on the SERIALIZED body after stamping, because that is what is sent: a cap applied to
    the caller's payload permits a request the send cannot make, and the failure then arrives as a
    dead-letter minutes later rather than as an answer now.

    Args:
      body: The serialized message body.

    Returns:
      None.

    Raises:
      ApiError: ``PayloadTooLarge`` if the body exceeds what the queue accepts.
    """
    if len(body.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ApiError("PayloadTooLarge", "the request is too large to enqueue")


def _refuse_for(error: BaseException) -> ApiError:
    """Maps a failed send onto the answer the caller should get.

    An ``AccessDenied`` here is NOT a denial. On this plane the credential is this function's own
    execution role, so a 403 would tell a user they may not do something when the deployment is
    misconfigured — and it would read as isolation working, which is the opposite of the truth.

    The error code is read by duck-typing rather than by catching a botocore class, matching how
    the identity layer already reads one: this package's sweep keeps every module but that layer
    away from the AWS SDK, and reading a field off an exception is not a reason to import it.

    Only reached for a failure that carries an AWS error code. Anything else rises untouched, so
    a bug in this service is recorded as a fault with its stack rather than reported to the caller
    as an unreachable queue.

    Args:
      error: The failure the send raised, which carries an AWS error code.

    Returns:
      The refusal to raise.

    Raises:
      None.
    """
    code = identity.aws_error_code(error)
    if code in _THROTTLE_CODES:
        return ApiError("RateLimited", "the queue is throttling")
    if code in _UNAVAILABLE_CODES:
        return ApiError("ApiUnavailable", "the queue is unavailable")
    return ApiError("InternalError", "the request could not be enqueued")


def enqueue(
    ctx: RequestContext, route: EnqueueRoute, payload: Mapping[str, Any]
) -> dict:
    """Sends one request onto its queue and answers the caller.

    Args:
      ctx: The request, carrying the verified caller and the wrapped bearer.
      route: The route being served.
      payload: The validated request body.

    Returns:
      The accepted response, echoing the caller's own request id where the plane has one.

    The body's own request id is stamped as ``body_request_id`` and NEVER as ``request_id``. The
    latter is the gateway's, and it is this request's correlation key: stamping the caller's value
    over it makes every record correlate on something a caller chose, and the two are easy to
    confuse because the body's field is also called ``requestId``.

    The client and the queue URL are resolved BEFORE the try, and the try re-raises anything that
    does not carry an AWS error code. Both matter: inside it, an unset queue variable and a tripped
    credential-plane guard were reshaped into "the queue could not be reached" — a 503 blaming the
    network for a misconfiguration, ending the span successfully with no stack, which is the exact
    shape of failure the credential-plane design says must be the loud half.

    Raises:
      ApiError: ``PayloadTooLarge`` when the message is too large; ``RateLimited``,
        ``ApiUnavailable`` or ``InternalError`` when the send itself fails.
      ConfigError: If the queue's URL or a bucket a derivation needs is unset. Reaches the router's
        own handler, which answers a server fault and records the stack.
    """
    message = build_message(route, ctx, payload)
    body = json.dumps(message, separators=(",", ":"))
    _refuse_if_oversized(body)

    group_id = fifo.group_id_for(route.id, ctx.principal, payload)
    dedup_id = fifo.dedup_id_for(route.id, ctx.principal, payload)

    observability.stamp(
        route_id=route.id,
        queue=route.queue,
        actor=ctx.principal.username,
        message_group_id=group_id,
        dedup_id=dedup_id,
        body_request_id=_clipped(payload.get("requestId")),
        body_bytes=len(body.encode("utf-8")),
    )

    client = identity.api_client("sqs")
    url = queue_url(route.queue)

    try:
        client.send_message(
            QueueUrl=url,
            MessageBody=body,
            MessageGroupId=group_id,
            MessageDeduplicationId=dedup_id,
        )
    except Exception as error:
        if not identity.aws_error_code(error):
            raise
        raise _refuse_for(error) from error

    return {"requestId": payload.get("requestId")}
