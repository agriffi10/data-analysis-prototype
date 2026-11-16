"""One page of a folder listing.

**One page. Never two.** ``Delimiter='/'`` and a bounded ``MaxKeys``, and no paginator anywhere in
this package — Arc A moved every operation whose cost grows with object count onto a control plane,
and a route that walks a subtree recreates that loop under a 29-second integration ceiling. It
would work, for small folders, in every test anyone writes.

Folders and files travel in one array with a ``kind`` on each row, which is what lets the browser's
existing ``FileListPage`` mapping stay exactly as it is.

``nextToken`` leaves UNMODIFIED. The browser round-trips it through a query string, and a token
carrying ``+``, ``/`` or ``=`` that anything re-encodes stops resolving to the page it named — the
next page then silently repeats the first.
"""

from typing import Any

from apicommon import protected
from apicommon.context import RequestContext
from cpcommon import observability

from . import _objects

LISTING_PAGE_SIZE = 25


def list_objects(context: RequestContext) -> dict[str, Any]:
    """Lists one page of a folder.

    Args:
      context: The authenticated request.

    Returns:
      The page's rows and a continuation token, or None on the last page.

    Raises:
      ApiError: ``AccessDenied`` when the claims do not authorize the space, or the prefix is
        not inside its root, a relative prefix included.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    space = _objects.space_from_query(context)
    prefix = protected.contained_prefix(space, context.query.get("prefix", ""))

    request: dict[str, Any] = {
        "Bucket": space.bucket,
        "Prefix": prefix,
        "Delimiter": "/",
        "MaxKeys": LISTING_PAGE_SIZE,
    }
    token = context.query.get("nextToken")
    if token:
        request["ContinuationToken"] = token

    page = _objects.client(context).list_objects_v2(**request)
    items = _rows(page, prefix)
    observability.stamp(item_count=len(items))
    return {
        "items": items,
        "nextToken": page.get("NextContinuationToken") or None,
    }


def _rows(page: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    """Turns one S3 page into the wire's rows.

    The folder marker is filtered out by basename, which is the same rule the browser applies and
    the same one the portal role's marker Denies encode — it is an implementation detail of a folder, not a
    file anybody put there.

    Args:
      page: The ``list_objects_v2`` response.
      prefix: The prefix that was listed, so the self-entry can be dropped.

    Returns:
      The rows, folders first, in S3's own order within each group.

    Raises:
      None.
    """
    rows: list[dict[str, Any]] = [
        {"kind": "folder", "key": entry["Prefix"], "size": None, "lastModified": None}
        for entry in page.get("CommonPrefixes", [])
    ]
    for entry in page.get("Contents", []):
        key = entry["Key"]
        if key == prefix or protected.is_marker(key):
            continue
        modified = entry.get("LastModified")
        rows.append(
            {
                "kind": "file",
                "key": key,
                "size": int(entry.get("Size", 0)),
                "lastModified": modified.isoformat() if modified is not None else None,
            }
        )
    return rows
