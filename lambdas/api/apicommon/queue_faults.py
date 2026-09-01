"""What a failed ``SendMessage`` means to the caller who asked for it.

A fact about SQS rather than about any one route, which is why it lives here rather than inside
the enqueue family: two call sites now put a message on a queue — the ten enqueue routes, through
one sender, and the feedback route, which builds its own message — and a second copy of this
mapping would be a second opinion on whether a throttled queue is the user's problem.

**An ``AccessDenied`` here is NOT a denial.** On this plane the credential is the function's own
execution role, so a 403 would tell a user they may not do something when the deployment is
misconfigured — and it would read as isolation working, which is the opposite of the truth.

The error code is read by duck-typing rather than by catching a botocore class, matching how the
identity layer already reads one: this package's sweep keeps every module but that layer away from
the AWS SDK, and reading a field off an exception is not a reason to import it.

Attributes:
  THROTTLE_CODES: The service codes meaning "come back in a moment". The only ones a user can act
    on, which is why they are the only ones that map to a user-fixable refusal.
  UNAVAILABLE_CODES: The service codes meaning the queue itself could not answer.
"""

from . import identity
from .envelope import ApiError

THROTTLE_CODES = frozenset(
    {
        "ThrottlingException",
        "Throttling",
        "RequestThrottled",
        "TooManyRequestsException",
    }
)

UNAVAILABLE_CODES = frozenset({"ServiceUnavailable", "InternalError", "InternalFailure"})


def refuse_for(error: BaseException) -> ApiError:
    """Maps a failed send onto the answer the caller should get.

    Only reached for a failure that carries an AWS error code. A caller checks that first and
    re-raises anything else, so a bug in this service is recorded as a fault with its stack rather
    than reported to the caller as an unreachable queue.

    Args:
      error: The failure the send raised, which carries an AWS error code.

    Returns:
      The refusal to raise.

    Raises:
      None.
    """
    code = identity.aws_error_code(error)
    if code in THROTTLE_CODES:
        return ApiError("RateLimited", "the queue is throttling")
    if code in UNAVAILABLE_CODES:
        return ApiError("ApiUnavailable", "the queue is unavailable")
    return ApiError("InternalError", "the request could not be enqueued")
