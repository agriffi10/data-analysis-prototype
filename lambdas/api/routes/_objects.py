"""What every object route does before it touches S3.

One place resolves a space and contains a key, so a route cannot forget to. The order is the point
and it is the same on every route: **resolve the space from claims, then contain the key, then
build the client.** A client built first would mean a refusal costs an ``AssumeRole``, and the
zero-call property is asserted by counting exactly that.
"""

from typing import Any

from apicommon import identity, protected, spaces
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from apicommon.spaces import ResolvedSpace


def space_from_query(context: RequestContext) -> ResolvedSpace:
    """Resolves the space a GET route's query names.

    Args:
      context: The authenticated request.

    Returns:
      The resolved space.

    Raises:
      ApiError: ``AccessDenied`` when the claims do not authorize it.
    """
    return spaces.resolve(
        context.acting_as, context.query.get("spaceKind", ""), context.query.get("spaceName", "")
    )


def space_from_body(context: RequestContext, field: str = "space") -> ResolvedSpace:
    """Resolves the space a body names.

    Args:
      context: The authenticated request.
      field: Which body field holds the ``SpaceRef``.

    Returns:
      The resolved space.

    Raises:
      ApiError: ``AccessDenied`` when the claims do not authorize it, or the field is missing.
    """
    body = context.body if isinstance(context.body, dict) else {}
    ref = body.get(field)
    if not isinstance(ref, dict):
        raise ApiError("AccessDenied", "request names no space")
    return spaces.resolve(context.acting_as, str(ref.get("kind", "")), str(ref.get("name", "")))


def contained(space: ResolvedSpace, key: str) -> str:
    """Contains a caller-supplied key inside a resolved space.

    Args:
      space: The resolved space.
      key: The caller's key.

    Returns:
      The key, when it is inside the root.

    Raises:
      ApiError: ``AccessDenied`` otherwise.
    """
    return protected.contained_key(space, key)


def client(context: RequestContext) -> Any:
    """Builds the S3 client on the caller's own assumed session.

    Built LAST, after every refusal has had its chance: a client is an ``AssumeRole``, and a
    refusal issued after one is indistinguishable from an IAM denial to anything outside the
    process.

    Args:
      context: The authenticated request.

    Returns:
      The S3 client.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    return identity.user_client("s3", context.acting_as)


def is_missing(exc: BaseException) -> bool:
    """Whether an S3 failure means the object is simply not there.

    Args:
      exc: The raised failure.

    Returns:
      True when the code is one of the three spellings S3 uses for an absent object.

    Raises:
      None.
    """
    return identity.aws_error_code(exc) in {"NoSuchKey", "NotFound", "404"}
