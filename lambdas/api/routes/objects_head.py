"""Metadata and existence — the two heads.

``exists`` answers **200 for both answers**, and that is the whole design decision in it. Mapping
absence onto the error arm would turn every free-name probe and every collision pre-check into a
failure the caller has to re-interpret, and the browser's ``objectExists`` resolves a missing key
to ``data: false`` today.
"""

from typing import Any

from apicommon.context import RequestContext
from apicommon.envelope import ApiError

from . import _objects


def metadata(context: RequestContext) -> dict[str, Any]:
    """Returns one object's metadata.

    Args:
      context: The authenticated request.

    Returns:
      The object's size, timestamp, content type and ETag.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key; ``NotFound`` when
        the object is absent — unlike ``exists``, a metadata read of nothing has nothing to say.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    space = _objects.space_from_query(context)
    key = _objects.contained(space, context.query.get("key", ""))
    try:
        head = _objects.client(context).head_object(Bucket=space.bucket, Key=key)
    except Exception as exc:
        if _objects.is_missing(exc):
            raise ApiError("NotFound", "no object at that key") from exc
        raise

    modified = head.get("LastModified")
    return {
        "key": key,
        "size": int(head.get("ContentLength", 0)),
        "lastModified": modified.isoformat() if modified is not None else "",
        "contentType": head.get("ContentType", "application/octet-stream"),
        "etag": str(head.get("ETag", "")).strip('"'),
    }


def exists(context: RequestContext) -> dict[str, Any]:
    """Reports whether an object is there, as a 200 either way.

    Args:
      context: The authenticated request.

    Returns:
      ``{"exists": bool}``.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Any S3 failure other than absence. A denial or a throttle reported as
        ``exists: false`` would let a free-name search march past a name that is taken.
    """
    space = _objects.space_from_query(context)
    key = _objects.contained(space, context.query.get("key", ""))
    try:
        _objects.client(context).head_object(Bucket=space.bucket, Key=key)
    except Exception as exc:
        if _objects.is_missing(exc):
            return {"exists": False}
        raise
    return {"exists": True}
