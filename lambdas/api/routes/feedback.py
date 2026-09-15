"""The one route that takes something a user wrote and puts it somewhere we will read it.

**It is not one of the ten enqueue routes, and the difference is the wire rather than the
plumbing.** Those carry a nested identity block, echo a request id the caller minted, and answer
``EnqueueAccepted``; this carries a top-level username, mints its own event id, and answers with
the stamp. Serving it through the shared sender would mean three exemptions inside a family whose
guards exist precisely to stop exemptions, so it builds its own message here. What it does share
is what a failed send means, which lives in ``apicommon.queue_faults``.

**The plane is ``api``, so the portal role holds no grant on this queue.** The user plane would
need the portal role to hold ``sqs:SendMessage`` here — a grant carried by every session the API
mints for every user, for a write this one handler makes. On this plane no user-scoped identity can
write the queue, so the only way a record gets there is through this handler, which takes the
username from the verified claim and never from the body. The request type declares no username
field for the same reason: there is nothing to ignore.

**Validation here is the control; the browser's is a courtesy.** The contract's validator has
already refused an unknown key, a category outside the closed set and a non-string message before
this runs — what is left are the value checks a type cannot express, and each is refused with the
operator text at the raise site and a machine code the browser turns into its own sentence.

**Nothing here logs the message.** It is a user's own prose, and a log store has a far wider read
audience than the file it is going into. The span carries its LENGTH.

**The 200 is the whole guarantee, and it is deliberately narrow.** It means the submission is on
the queue. Nothing after that point is something the user could act on, which is why nothing after
that point tells them anything — and why the queue's dead-letter queue is not drained into a
notification (``dlq_drain.UNDRAINED_QUEUES``).

Attributes:
  MAX_MESSAGE_CHARS: The longest message accepted, counted after trimming. Long enough for a
    considered bug report and far below the queue's own limit, so a refusal here is never a
    stand-in for one the send would have made.
  MAX_ROUTE_CHARS: The longest captured path accepted. The browser sends one of its own routes, so
    this bounds a caller that sends something else rather than a path anybody types.
  SCHEMA_VERSION: The message shape this route writes, recorded on the wire so the writer can tell
    which producer wrote an entry.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from apicommon import config, identity, queue_faults
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from cpcommon import observability

MAX_MESSAGE_CHARS = 4000
MAX_ROUTE_CHARS = 200

SCHEMA_VERSION = 1


def _checked_message(body: dict[str, Any]) -> str:
    """Returns the submission's message, or refuses it.

    Trimmed before both checks, which is the point of doing it here rather than in the type: a
    message of four thousand spaces is empty to a reader and full to a length check, and the
    contract can say neither.

    Args:
      body: The validated request body.

    Returns:
      The trimmed message.

    Raises:
      ApiError: ``InvalidRequest`` if the message is empty once trimmed, or longer than
        ``MAX_MESSAGE_CHARS``.
    """
    message = cast("str", body["message"]).strip()
    if not message:
        raise ApiError("InvalidRequest", "the feedback message is empty")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ApiError(
            "InvalidRequest",
            f"the feedback message is {len(message)} characters, over the "
            f"{MAX_MESSAGE_CHARS}-character limit",
        )
    return message


def _checked_route(body: dict[str, Any]) -> str | None:
    """Returns the captured path, or refuses it.

    Stored verbatim and interpreted by nothing — it is not resolved, not matched against the route
    table, and not turned into a link. The only thing asked of it is that it be bounded, because
    it lands in a file somebody reads.

    Args:
      body: The validated request body.

    Returns:
      The path, or None when the caller sent none.

    Raises:
      ApiError: ``InvalidRequest`` if the path is longer than ``MAX_ROUTE_CHARS``.
    """
    captured = body.get("route")
    if captured is None:
        return None
    if len(cast("str", captured)) > MAX_ROUTE_CHARS:
        raise ApiError(
            "InvalidRequest",
            f"the captured route is {len(cast('str', captured))} characters, over the "
            f"{MAX_ROUTE_CHARS}-character limit",
        )
    return cast("str", captured)


def submit(ctx: RequestContext) -> dict[str, Any]:
    """Validates one submission, stamps it, and puts it on the feedback queue.

    The client and the queue URL are resolved BEFORE the try, and the try re-raises anything that
    does not carry an AWS error code. Both matter: inside it, an unset queue variable and a
    tripped credential-plane guard would be reshaped into "the queue is unavailable" — a 503
    blaming the network for a misconfiguration, ending the span successfully with no stack.

    ``MessageGroupId`` is the submission's UTC date, so every message destined for one day's file
    serializes behind the previous one — which is the contention the writer's compare-and-swap
    would otherwise have to retry through. ``MessageDeduplicationId`` is the event id, so a
    transport-level duplicate lands once.

    Args:
      ctx: The request, carrying the verified caller and its validated body.

    Returns:
      The stamp, once the send has succeeded and not before.

    Raises:
      ApiError: ``InvalidRequest`` when a value check refuses the submission; ``RateLimited``,
        ``ApiUnavailable`` or ``InternalError`` when the send itself fails.
      ConfigError: If the queue's URL is unset. Reaches the router's own handler, which answers a
        server fault and records the stack.
    """
    body = cast("dict[str, Any]", ctx.body or {})
    message = _checked_message(body)
    captured = _checked_route(body)

    event_id = str(uuid.uuid4())
    submitted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    submission: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": event_id,
        "username": ctx.principal.username,
        "category": body["category"],
        "message": message,
        "submittedAt": submitted_at,
    }
    if captured is not None:
        submission["route"] = captured

    group_id = submitted_at[:10]

    observability.stamp(
        event_id=event_id,
        category=body["category"],
        message_chars=len(message),
        message_group_id=group_id,
    )

    client = identity.api_client("sqs")
    url = config.feedback_queue_url()

    try:
        client.send_message(
            QueueUrl=url,
            MessageBody=json.dumps(submission, separators=(",", ":")),
            MessageGroupId=group_id,
            MessageDeduplicationId=event_id,
        )
    except Exception as error:
        if not identity.aws_error_code(error):
            raise
        raise queue_faults.refuse_for(error) from error

    return {"submittedAt": submitted_at}
