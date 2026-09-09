"""The one path the ELEVEN ENQUEUE ROUTES take to ``SendMessage``. No credential passes through it.

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

A handler still builds no message body, which is what keeps the router's premise true at eleven
routes rather than one.

Attributes:
  SQS_MAX_MESSAGE_BYTES: What these queues accept for one message body. It is the service default
    rather than the documented maximum, because no queue module sets ``max_message_size``. It is
    no longer what binds — the state arm below is roughly a third of it — and it stays because the
    queue's own ceiling is still real. **Nobody should read its passing as evidence it fires.**
  MAX_IDENTITY_BLOCK_BYTES: The allowance for the identity block at its largest.
  MAX_PIPE_RECORD_OVERHEAD_BYTES: The allowance for everything in the Pipes SQS record that is not
    the body — the receipt handle, the FIFO attributes block, the source ARN. MODELLED rather than
    measured: no captured record exists to measure, so a guard holds this against the documented
    shape at each field's maximum.
  MAX_RECORD_FAILURE_LITERAL_BYTES: The allowance for every key the largest plane's
    ``RecordFailure`` names beside the envelope and the error. Not a rounding error and easy to
    drop: without it the fleet cap and the per-plane failure state disagree by kilobytes. A guard
    sums the real key sets from the eight templates against it — this module cannot, because the
    image carries ``lambdas/`` and not ``infra/``.
  BODY_ESCAPE_FACTOR: What the body costs again when the Pipe embeds it in the record as a JSON
    string. Exactly 2 in the worst case — a run of quotes or backslashes — and nothing beats it,
    because ``json.dumps`` emits no raw control character or non-ASCII byte.
  MESSAGE_HEADROOM_BYTES: What the cap deliberately leaves unspent. A budget pinned at today's
    measurement leaves the next legitimate addition nothing, which makes the gate cause the damage
    it exists to prevent. It is bounded ABOVE as well: file-send's counterfactual tripwire — that
    carrying the selection beside the envelope would breach the limit — stops being evidence once
    the send cap falls to **62 KiB**, which `test_the_tripwire_above_holds_far_below_the_shipped_cap`
    measures with that tripwire's own arithmetic rather than restating. An earlier version of this
    sentence said 82 KiB, measured against the 4 KB error model this spec replaced.
  MAX_MESSAGE_BYTES: What a caller's payload may serialize to once everything above is stamped
    onto it. Derived from the limit that actually binds, which is not the queue's: SQS accepting a
    message says nothing about Step Functions starting an execution with it, and every per-plane
    cap that looks like it bounds the chain runs INSIDE ``validate-authorize``, so the request that
    overflows arrives before the cap that would refuse it. Measured against the ALREADY-STAMPED
    body, because that is what is sent.
  MAX_LOGGED_REQUEST_ID: How much of the caller's own request id reaches a log field. It is
    caller-controlled text on baggage, so it rides every event of the invocation into a store that
    is retained forever — the reason the router bounds the id IT echoes.
"""

import json
from collections.abc import Mapping
from typing import Any

from cpcommon import config, observability

from . import fifo, identity, identity_block, queue_faults
from .config import queue_url
from .context import RequestContext
from .contract import EnqueueRoute
from .envelope import ApiError

SQS_MAX_MESSAGE_BYTES = 262_144
MAX_IDENTITY_BLOCK_BYTES = 512

MAX_PIPE_RECORD_OVERHEAD_BYTES = 2 * 1024
MAX_RECORD_FAILURE_LITERAL_BYTES = 4 * 1024
BODY_ESCAPE_FACTOR = 2
MESSAGE_HEADROOM_BYTES = 8 * 1024

_STATE_ARM = (
    config.STATE_PAYLOAD_LIMIT_BYTES
    - config.CAUSE_RESERVATION_BYTES
    - MAX_PIPE_RECORD_OVERHEAD_BYTES
    - MAX_RECORD_FAILURE_LITERAL_BYTES
    - MESSAGE_HEADROOM_BYTES
) // BODY_ESCAPE_FACTOR
_QUEUE_ARM = SQS_MAX_MESSAGE_BYTES - MAX_IDENTITY_BLOCK_BYTES
MAX_MESSAGE_BYTES = min(_STATE_ARM, _QUEUE_ARM)

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

    ``mode`` and ``schemaVersion`` choose behaviour rather than describe a request, which is why
    neither is a caller input: ``mode`` is the difference between archiving and restoring, and
    handing it to a body would hand the caller that branch.

    ``traceparent`` is the other kind and is on every route. A run begins here — the API span is
    the root of a trace the run's nine or twenty-five invocations all join — so the value has to
    leave with the message, threaded through the state payload exactly as ``requestId`` is.

    **It is written unconditionally, ``None`` included.** A conditional write would hand a
    caller's value straight through on any request where no span is open, which is the whole
    failure the extractor's narrowing exists to close: the caller's key would then be the one
    every verb in the run adopted. ``build_message`` spreads the payload FIRST, so whatever this
    returns overwrites a caller's key of the same name; that ordering is the outbound half of the
    same boundary. The route contract also refuses an undeclared body key today, so a caller
    cannot get one this far — but a route that later declares a free-form block would end that,
    and this would still hold.

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
    return {"traceparent": observability.run_traceparent(), **values.get(route.id, {})}


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
    """Refuses a message the CHAIN cannot carry, before it is billed for or partly done.

    Measured on the SERIALIZED body after stamping, because that is what is sent: a cap applied to
    the caller's payload permits a request the send cannot make, and the failure then arrives as a
    dead-letter minutes later rather than as an answer now.

    The queue is no longer what it is measured against, and the summary said so for as long as it
    was true. What binds is the state limit an execution has to fit — see ``MAX_MESSAGE_BYTES`` —
    and a message SQS would happily take can still be one no execution can start from.

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
