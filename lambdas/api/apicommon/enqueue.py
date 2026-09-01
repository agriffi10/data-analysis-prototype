"""The one path the TEN ENQUEUE ROUTES take to ``SendMessage``. No credential passes through it.

Every enqueue route hands its validated payload here. This module stamps what the caller may not —
the identity block and the route's own literals — derives the FIFO keys, checks the result against
what the queue will accept, and sends.

It is not the API's only ``SendMessage`` any more, and the distinction is worth keeping straight:
the feedback route builds its own message because its wire shape is not this family's — a
top-level username rather than a nested identity block, a stamped event id rather than an echoed
request id. What the two do share is what a failed send MEANS, and that lives in
``queue_faults`` so there is one answer to it.

**The caller's raw bearer used to be stamped in beside the block**, because the control planes
verified a token out of the message body. They read the identity block now, so the token has no
reader, and forwarding a bearer credential through eight queues and into eight state-machine
execution inputs for nobody is the exposure this whole change exists to close. The wrapper that
kept it un-renderable, the field on the request context and the sweep counting its one reader all
went with it: there is nothing left to contain.

A handler still builds no message body, which is what keeps the router's premise true at ten
routes rather than one.

Attributes:
  SQS_MAX_MESSAGE_BYTES: What these queues accept for one message body. It is the service default
    rather than the documented maximum, because no queue module sets ``max_message_size``.
  MAX_IDENTITY_BLOCK_BYTES: The allowance for the identity block at its largest.
  MAX_MESSAGE_BYTES: What a caller's payload may serialize to once everything above is stamped
    onto it. Derived, never written down: a cap applied to the caller's payload alone would admit
    a request the send cannot make. It is measured against the ALREADY-STAMPED body, so the
    allowance above is reserved twice — the safe direction. It grew by 8 KB when the token stopped
    being sent, which is headroom returned to callers rather than a limit relaxed.
  MAX_LOGGED_REQUEST_ID: How much of the caller's own request id reaches a log field. It is
    caller-controlled text on baggage, so it rides every event of the invocation into a store that
    is retained forever — the reason the router bounds the id IT echoes.
"""

import json
from collections.abc import Mapping
from typing import Any

from cpcommon import observability

from . import fifo, identity, identity_block, queue_faults
from .config import queue_url
from .context import RequestContext
from .contract import EnqueueRoute
from .envelope import ApiError

SQS_MAX_MESSAGE_BYTES = 262_144
MAX_IDENTITY_BLOCK_BYTES = 512
MAX_MESSAGE_BYTES = SQS_MAX_MESSAGE_BYTES - MAX_IDENTITY_BLOCK_BYTES

MAX_LOGGED_REQUEST_ID = 128


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


def _stamped_values(route: EnqueueRoute) -> dict[str, Any]:
    """The top-level fields the sender writes and the caller may not.

    Each is a value that chooses behaviour rather than describing a request, which is why none of
    them is a caller input: ``mode`` is the difference between archiving and restoring, and
    handing it to a body would hand the caller that branch.

    It takes no request. It used to, for shared-space's advisory top-level ``actor`` — which
    duplicated ``identity.actor``, which nothing read, and which is gone: a second place a
    username appears on the wire is a second one that can disagree with the first.

    Args:
      route: The route being served.

    Returns:
      The fields to stamp, whose key set is the route's own declaration.

    Raises:
      None.
    """
    values: dict[str, dict[str, Any]] = {
        "sharedSpace.enqueue": {"schemaVersion": 1},
        "tableBuild.refresh": {"mode": "refresh"},
        "archive.archive": {"mode": "archive"},
        "archive.restore": {"mode": "restore"},
    }
    return values.get(route.id, {})


def build_message(
    route: EnqueueRoute, ctx: RequestContext, payload: Mapping[str, Any]
) -> dict:
    """Assembles the message one route sends.

    The identity block stays NESTED now that the token it rode beside is gone. Moving it into the
    flat ``actor`` field four planes used to keep a token in would be a second wire migration for
    no gain, and would create a window in which one plane's ``actor`` is a username while another's
    is still a token.

    Args:
      route: The route being served.
      ctx: The request, carrying the verified caller.
      payload: The validated request body.

    Returns:
      The message body, ready to serialize.

    Raises:
      None.
    """
    return {
        **dict(payload),
        **_stamped_values(route),
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


def enqueue(
    ctx: RequestContext, route: EnqueueRoute, payload: Mapping[str, Any]
) -> dict:
    """Sends one request onto its queue and answers the caller.

    Args:
      ctx: The request, carrying the verified caller.
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
        raise queue_faults.refuse_for(error) from error

    return {"requestId": payload.get("requestId")}
