"""Metadata and existence — the two heads.

``exists`` answers **200 for both answers**, and that is the whole design decision in it. Mapping
absence onto the error arm would turn every free-name probe and every collision pre-check into a
failure the caller has to re-interpret, and the browser's ``objectExists`` resolves a missing key
to ``data: false`` today.

It answers about a **prefix** as well as an object, and the listing route cannot stand in for that
half: ``objects_list`` hides the prefix's own marker and every ``DO_NOT_DELETE.txt``, so an empty
folder and a ``saved_queries/`` holding only its marker both list as nothing while being perfectly
present. A panel that read "nothing listed" as "deleted" would tell a user their folder was gone.
"""

from typing import Any

from apicommon import protected
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from apicommon.spaces import ResolvedSpace

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
        "storageClass": str(head.get("StorageClass") or "STANDARD"),
        "userMetadata": [
            {"name": str(name), "value": str(value)}
            for name, value in sorted((head.get("Metadata") or {}).items())
        ],
    }


def exists(context: RequestContext) -> dict[str, Any]:
    """Reports whether an object — or anything at all under a prefix — is there, as a 200 either way.

    Args:
      context: The authenticated request. ``target=prefix`` asks about a whole folder; anything
        else, absence included, asks about the one key.

    Returns:
      ``{"exists": bool}``.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Any S3 failure other than absence. A denial or a throttle reported as
        ``exists: false`` would let a free-name search march past a name that is taken.
    """
    space = _objects.space_from_query(context)
    if context.query.get("target") == "prefix":
        return _prefix_exists(context, space)

    key = _objects.contained(space, context.query.get("key", ""))
    try:
        _objects.client(context).head_object(Bucket=space.bucket, Key=key)
    except Exception as exc:
        if _objects.is_missing(exc):
            return {"exists": False}
        raise
    return {"exists": True}


def _prefix_exists(context: RequestContext, space: ResolvedSpace) -> dict[str, Any]:
    """Whether any key at all lives under a prefix.

    Raw and unfiltered, which is the whole point — the marker object a "New folder" leaves behind
    IS the folder, and the listing route drops it.

    One page of one row, delimited like every other listing in this package: with ``Delimiter``
    set, a folder holding only a nested subfolder still answers through ``CommonPrefixes``, so the
    delimiter costs the answer nothing and keeps the thinness rule whole. The verdict reads the
    two arrays rather than ``KeyCount``, because reading the count means trusting a documented
    relationship this package has no way to fail loudly on.

    **``IsTruncated`` is in the verdict as a belt.** A bounded, delimited page can in principle come
    back with neither array populated and more to follow, which the browser's old undelimited
    ``MaxKeys=1`` call could not — and a false answer here tells a user their folder is gone, which
    is the one thing this question exists to avoid. Whether S3 actually produces that page is
    unverified; the residual costs one boolean to close and is not worth leaving open.

    Args:
      context: The authenticated request.
      space: The already-resolved space.

    Returns:
      ``{"exists": bool}``.

    Raises:
      ApiError: ``AccessDenied`` when the prefix escapes the space root.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    prefix = protected.contained_prefix(space, context.query.get("key", ""))
    page = _objects.client(context).list_objects_v2(
        Bucket=space.bucket, Prefix=prefix, Delimiter="/", MaxKeys=1
    )
    return {
        "exists": bool(
            page.get("Contents") or page.get("CommonPrefixes") or page.get("IsTruncated")
        )
    }
