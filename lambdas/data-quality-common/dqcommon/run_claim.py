"""Claims a data-quality request id for the one execution allowed to use it.

Every per-run resource this plane creates is named from the request id: the temp tables, the report
folder and everything written under it, and the Athena idempotency tokens. The caller chooses that
id and the queue forgets it after five minutes, so a second execution sending the same id later
used to inherit the first one's table through the ``IF NOT EXISTS`` create, overwrite its manifest
and report, and drop its tables on cleanup. Claiming the id before anything is named from it makes
every one of those names this execution's alone, which is why this is one claim rather than a guard
at each resource.

A claim only makes the derived names unique if distinct ids derive distinct names. A table's name is
the id with its hyphens stripped, and Glue folds table names to lower case, so ``ab-cd`` and
``abcd``, or an id and its upper-case twin, would hold two claims and share one table. Only the
canonical lower-case UUID form is accepted, here and at the validator, which makes that derivation
one-to-one.

The claim lives in the admin bucket, which no user can reach by any route. A claim kept beside the
report would sit inside the space, where it is only as safe as every route that can write or delete
there, and a member who removed it could reuse the id. It would also be one claim per space rather
than one per id, and Athena's tokens are not scoped to a space.

The holder is the execution ARN, never the request id, because the id is whatever the caller sent. A
retry of the claiming Task is the same execution, finds its own ARN and carries on. A redelivered
message was measured to re-attach to its first execution rather than start a second, but that the
Pipe names executions per message is inferred rather than proven, so nothing here relies on it.

A claim is never released, taken over or expired. That is the difference from ``cpcommon.lock``,
whose staleness rule would hand the id to a later execution, which is the collision this prevents.

Attributes:
  CLAIM_VERSION: Body schema version, recorded so a later reader can tell which shape wrote a
    claim. Nothing branches on it.
  _CANONICAL_REQUEST_ID: The only request-id shape this plane accepts, the hyphenated lower-case
    UUID that the browser mints.
  _PRECONDITION_FAILED: The codes S3 returns when a conditional create finds the key taken.
  _CONDITIONAL_CONFLICT: The codes S3 returns when a concurrent request interrupted the
    conditional create. S3 says to retry the write, so these are transient rather than evidence
    that the key is held.
"""

import json
import re
from datetime import UTC, datetime
from typing import TypeGuard

from cpcommon import clients, errors, observability
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError, TransientError

from . import messages
from .config import CLAIM_PREFIX

CLAIM_VERSION = 1

_CANONICAL_REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

_PRECONDITION_FAILED = frozenset({"PreconditionFailed", "412"})

_CONDITIONAL_CONFLICT = frozenset({"ConditionalRequestConflict", "409"})


def is_canonical_request_id(value: object) -> TypeGuard[str]:
    """Reports whether a request id is the canonical lower-case UUID this plane accepts.

    The type is checked before the pattern: a request field may hold a number or a list, and a
    pattern match on one raises ``TypeError`` instead of letting the caller refuse it by name.

    Args:
      value: The untrusted request id, of any type.

    Returns:
      True only for a string that is a hyphenated lower-case UUID.

    Raises:
      None.
    """
    return isinstance(value, str) and _CANONICAL_REQUEST_ID.fullmatch(value) is not None


def claim_key(request_id: str) -> str:
    """Derives the claim object's key in the admin bucket.

    Args:
      request_id: A canonical request id.

    Returns:
      The claim key.

    Raises:
      None.
    """
    return f"{CLAIM_PREFIX}/{request_id}.json"


@observability.step("claim-request-id")
def claim(request_id: object, execution_arn: object) -> None:
    """Makes the request id this execution's, or refuses the run.

    The canonical form is checked again here although the validator already refused anything
    else, because this function builds an admin-bucket key from the id and must not rely on a
    different verb having run.

    Args:
      request_id: The run's request id, as read off the state.
      execution_arn: This execution's ARN, stamped on the state by the machine.

    Returns:
      None, once this execution holds the claim, whether it wrote it now or on an earlier attempt.

    Raises:
      TerminalError: ``invalid_request`` for a request id that is not canonical or a missing
        execution ARN, and ``request_id_reused`` when another execution holds the id or the
        claim found at the key cannot be read as one.
      TransientError: When a concurrent request interrupted the write, or on a retryable S3 fault.
    """
    if not is_canonical_request_id(request_id):
        raise TerminalError(messages.INVALID_REQUEST, "requestId is not a lower-case UUID")
    if not isinstance(execution_arn, str) or not execution_arn.strip():
        raise TerminalError(messages.INVALID_REQUEST, "no execution ARN to claim the request id for")

    bucket = cpconfig.ADMIN_BUCKET
    key = claim_key(request_id)
    body = json.dumps(
        {
            "version": CLAIM_VERSION,
            "requestId": request_id,
            "executionArn": execution_arn,
            "claimedAt": datetime.now(UTC).isoformat(),
        },
        sort_keys=True,
    ).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as err:
        code = errors.error_code(err)
        if code in _CONDITIONAL_CONFLICT:
            raise TransientError(f"claim write for {request_id!r} was interrupted ({code})") from err
        if code not in _PRECONDITION_FAILED:
            errors.raise_if_transient(err, f"claim {bucket}/{key}")
            raise
        holder = _holder(bucket, key)
        if holder != execution_arn:
            observability.warning("request id already claimed", held_by_this_run=False)
            raise TerminalError(
                messages.REQUEST_ID_REUSED,
                f"request id {request_id!r} is claimed by {holder!r}, not this execution",
            ) from err
        observability.info("request id claimed", reclaimed=True)
    else:
        observability.info("request id claimed", reclaimed=False)


def _holder(bucket: str, key: str) -> str | None:
    """Reads which execution holds an existing claim.

    Called only after a conditional create found the key taken. Claims are never deleted and the
    bucket keeps no versions, so the object is there to read.

    Args:
      bucket: The admin bucket.
      key: The claim key.

    Returns:
      The holding execution's ARN, or None when the object does not parse as a claim, which the
      caller refuses rather than treating as free.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other S3 fault propagates.
    """
    try:
        response = clients.s3().get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"read claim {bucket}/{key}")
        raise
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    holder = document.get("executionArn") if isinstance(document, dict) else None
    return holder if isinstance(holder, str) else None
