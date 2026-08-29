"""Copy, move and delete — single objects only.

**Move is ONE route performing copy-then-delete**, not two calls from the browser. Two calls put a
closed tab between them, and versioning is off: that is a lost file rather than a failed move.

**The copy source is a dict, never a hand-built string.** ``buildCopySource``'s per-segment
``encodeURIComponent`` is deleted rather than ported — a hand-rolled encoder is wrong for `+` or
`%` and copies the wrong object or none, and it is right for every key in every fixture anybody
would think to write.

Folder copy, move and delete are **not here and never will be**. Arc A's control plane owns every
operation whose cost grows with object count.
"""

from typing import TYPE_CHECKING, Any

from apicommon import protected
from apicommon.context import RequestContext
from apicommon.envelope import ApiError

if TYPE_CHECKING:
    from apicommon.spaces import ResolvedSpace

from . import _objects


def copy_object(context: RequestContext) -> dict[str, Any]:
    """Copies one object.

    Args:
      context: The authenticated request.

    Returns:
      The destination key and its new ETag.

    Raises:
      ApiError: ``AccessDenied``, ``Conflict`` or ``NotFound`` as the shared guard decides.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    plan = _plan(context)
    return _perform_copy(plan, _objects.client(context))


def move_object(context: RequestContext) -> dict[str, Any]:
    """Copies one object and then deletes its source.

    Args:
      context: The authenticated request.

    Returns:
      The destination key and its new ETag.

    Raises:
      ApiError: As ``copy_object``, plus ``AccessDenied`` when the SOURCE is not writable — a move
        deletes it, so a source the caller may not delete is not a source they may move. Checked
        BEFORE the copy: a move that copies and only then discovers it may not delete has already
        duplicated the object, and the user asked for one of it.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    plan = _plan(context)
    protected.assert_writable(plan["source_space"], plan["source_key"])

    client = _objects.client(context)
    written = _perform_copy(plan, client)
    client.delete_object(Bucket=plan["source_space"].bucket, Key=plan["source_key"])
    return written


def delete_object(context: RequestContext) -> dict[str, Any]:
    """Deletes one object.

    Args:
      context: The authenticated request.

    Returns:
      The key deleted.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space, an escaping key, a marker key or a
        write-locked location.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    protected.assert_writable(space, key)

    _objects.client(context).delete_object(Bucket=space.bucket, Key=key)
    return {"key": key}


def _plan(context: RequestContext) -> dict[str, Any]:
    """Resolves both ends of a copy, refusing before any AWS call.

    Args:
      context: The authenticated request.

    Returns:
      The resolved spaces, keys and the overwrite flag.

    Raises:
      ApiError: ``AccessDenied`` when either end is unauthorized, the key escapes its root, or
        the destination is protected.
    """
    body = context.body if isinstance(context.body, dict) else {}
    source_space = _objects.space_from_body(context, "source")
    destination_space = _objects.space_from_body(context, "destination")
    source_key = _objects.contained(source_space, str(body.get("sourceKey", "")))
    destination_key = _objects.contained(destination_space, str(body.get("destinationKey", "")))
    protected.assert_writable(destination_space, destination_key)
    return {
        "source_space": source_space,
        "source_key": source_key,
        "destination_space": destination_space,
        "destination_key": destination_key,
        "overwrite": bool(body.get("overwrite", False)),
    }


def _perform_copy(plan: dict[str, Any], client: Any) -> dict[str, Any]:
    """Runs the copy half, refusing an occupied destination first.

    Args:
      plan: The resolved plan.
      client: The S3 client, passed in so a move's copy and delete share one assumed session
        rather than opening two.

    Returns:
      The destination key and its new ETag.

    Raises:
      ApiError: ``Conflict`` when occupied and ``overwrite`` is false; ``NotFound`` when the
        source is absent.
    """
    destination: ResolvedSpace = plan["destination_space"]

    if not plan["overwrite"]:
        try:
            client.head_object(Bucket=destination.bucket, Key=plan["destination_key"])
        except Exception as exc:
            if not _objects.is_missing(exc):
                raise
        else:
            raise ApiError(
                "Conflict",
                "destination is occupied",
                {"name": plan["destination_key"].rsplit("/", 1)[-1]},
            )

    try:
        written = client.copy_object(
            Bucket=destination.bucket,
            Key=plan["destination_key"],
            CopySource={"Bucket": plan["source_space"].bucket, "Key": plan["source_key"]},
        )
    except Exception as exc:
        if _objects.is_missing(exc):
            raise ApiError("NotFound", "no object at the source key") from exc
        raise

    result = written.get("CopyObjectResult") or {}
    return {"key": plan["destination_key"], "etag": str(result.get("ETag", "")).strip('"')}
