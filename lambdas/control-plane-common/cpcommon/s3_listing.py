"""Paginated S3 listing plus the shared rules for what counts as a data object.

The single source of the ignore rules for every control plane's source listing: the prefix
marker, the results and settings sub-trees, zero-byte placeholders, and hidden or partial
paths are never source data.

The hidden rule is segment-level, not basename-only: any underscore- or dot-prefixed path
segment under the request prefix excludes the object. A basename-only rule meant a hidden
reports folder was not ignored, so Table Builder would ingest another arc's own reports as
source data. Athena ignores such files and directories too, so they must not enter any plan.

Attributes:
  MARKER_BASENAME: The prefix marker written at folder creation.
  _IGNORED_SUBTREES: First-segment sub-trees that are never source data regardless of a
    leading underscore. Query output and the notification inbox plus saved queries have no
    leading underscore, so the segment rule would not catch them — but a folder-level scan
    reaching a space root must never treat them as source data.
"""

from collections.abc import Iterator

from . import clients

MARKER_BASENAME = "DO_NOT_DELETE.txt"

_IGNORED_SUBTREES = ("athenaresults/", "user_settings/")


def _basename(key: str) -> str:
    """Returns the last slash-separated segment of an S3 key.

    Args:
      key: The object key.

    Returns:
      The basename, which is "" for a key ending in a slash.

    Raises:
      None.
    """
    return key.rsplit("/", 1)[-1]


def is_ignored(key: str, size: int, prefix: str) -> bool:
    """Reports whether an object is something other than source data.

    Args:
      key: The absolute object key.
      size: The object's byte size; zero means a folder placeholder.
      prefix: The request prefix the key is being listed under.

    Returns:
      True for the prefix marker, the ignored sub-trees, a folder key, a zero-byte
      placeholder, or any path with a hidden segment below the prefix.

    Raises:
      None.
    """
    rel = key.removeprefix(prefix)
    if rel.startswith(_IGNORED_SUBTREES):
        return True
    base = _basename(key)
    if base == "":
        return True
    if base == MARKER_BASENAME:
        return True
    if any(segment.startswith(("_", ".")) for segment in rel.split("/") if segment):
        return True
    return size == 0


def list_data_objects(bucket: str, prefix: str, relative: bool = False) -> Iterator[tuple[str, int]]:
    """Yields every non-ignored data object under a prefix, paginating past 1000 objects.

    Errors are never swallowed — but "raw" means a botocore ``ClientError``, which a Step
    Function sees by its Python class name, and a verb's Retry list names ``TransientError``
    rather than ``ClientError``. Mapping a throttle or 5xx is therefore the caller's job, and
    only helps under a state whose Retry actually names ``TransientError``.

    Args:
      bucket: The bucket to list.
      prefix: The request prefix.
      relative: Yield keys relative to the prefix instead of absolute ones. Table-share
        passes True and re-roots them under each recipient's path; table-builder and
        data-quality need absolute keys for manifests and sample keys.

    Yields:
      ``(key, size)`` for each data object.

    Raises:
      ClientError: Propagated raw from the paginator.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            if is_ignored(key, size, prefix):
                continue
            yield (key[len(prefix):] if relative else key), size
