"""Paginated S3 listing, the size of one named object, and the shared rules for what counts
as a data object.

The reads sit together because every plane that expands a selection into a copy plan needs them:
a listing for a folder item and a head for a file item, which costs its own serial ``HeadObject``.

``list_data_records`` is the paginator; ``list_data_objects`` is that function projected onto the
``(key, size)`` pairs most callers read. There is one place that pages, and the projection exists
so that a plane needing the ETag — to make a later write or delete conditional on the object not
having changed — does not have to fork the pagination to get a field the response already carried.

The single source of the ignore rules for every control plane's source listing: the prefix
marker, the results and settings sub-trees, zero-byte placeholders, and hidden or partial
paths are never source data.

The hidden rule is segment-level, not basename-only: any underscore- or dot-prefixed path
segment under the request prefix excludes the object. A basename-only rule meant a hidden
reports folder was not ignored, so Table Builder would ingest another arc's own reports as
source data. Athena ignores such files and directories too, so they must not enter any plan.

Attributes:
  MARKER_BASENAME: The prefix marker written at folder creation.
  _IGNORED_SUBTREES: Sub-trees that are never source data regardless of a
    leading underscore. Query output and the notification inbox plus saved queries have no
    leading underscore, so the segment rule would not catch them — but a folder-level scan
    reaching a space root must never treat them as source data. Matched against the remainder
    after the listing prefix, so the results entry is built with an EMPTY root: the remainder is
    relative. It comes from the PLURAL builder, which now answers one home per folder, so this
    tuple shrank with the narrowing rather than being edited here.
"""

from collections.abc import Callable, Iterator

from . import clients, errors
from .app_managed import ATHENA_RESULTS_FOLDER, app_managed_prefixes
from .errors import TerminalError

MARKER_BASENAME = "DO_NOT_DELETE.txt"

_IGNORED_SUBTREES = (*app_managed_prefixes("", ATHENA_RESULTS_FOLDER), "user_settings/")


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

    Public for its own test's benefit, and NOT dead — ``list_data_objects`` calls it below.
    the rule looked at making it private and kept public: the ignore rule is the one
    part of listing worth asserting case by case, and a test reaching through a leading
    underscore to do that is worse than a name that says it may be read.

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


def list_data_records(
    bucket: str,
    prefix: str,
    ignore: Callable[[str, int, str], bool] = is_ignored,
) -> Iterator[dict]:
    """Yields every non-ignored data object under a prefix, with the fields the listing already
    returned, paginating past 1000 objects.

    The paginator itself, and the reason it is the one function rather than two: ``ListObjectsV2``
    returns ``ETag`` and ``Size`` in ``Contents`` at zero marginal cost, and a plane that needs the
    ETag to make its later write conditional has no other cheap producer of it — the alternative is
    a ``HeadObject`` per object, which is a round trip per object where a listing is one per
    thousand. ``list_data_objects`` below is this function narrowed to the two fields its five
    callers read, so there is still exactly one place that pages.

    Args:
      bucket: The bucket to list.
      prefix: The request prefix.
      ignore: Predicate receiving ``(key, size, prefix)`` and reporting whether the object is
        something other than source data. Defaults to the analytics rule above; the planes whose
        exclusions are anchored somewhere else pass their own.

    Yields:
      ``{"key", "size", "etag"}`` per data object, the key absolute.

    Raises:
      ClientError: Propagated raw from the paginator.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            if ignore(key, size, prefix):
                continue
            yield {"key": key, "size": size, "etag": obj.get("ETag")}


def list_data_objects(
    bucket: str,
    prefix: str,
    relative: bool = False,
    ignore: Callable[[str, int, str], bool] = is_ignored,
) -> Iterator[tuple[str, int]]:
    """Yields every non-ignored data object under a prefix, paginating past 1000 objects.

    ``list_data_records`` narrowed to the ``(key, size)`` pairs these callers read. It is a
    projection rather than a second paginator, so a plane that needs the ETag and one that does not
    still page in exactly one place.

    Errors are never swallowed — but "raw" means a botocore ``ClientError``, which a Step
    Function sees by its Python class name, and a verb's Retry list names ``TransientError``
    rather than ``ClientError``. Mapping a throttle or 5xx is therefore the caller's job, and
    only helps under a state whose Retry actually names ``TransientError``.

    **The pagination is the shared part; the ignore rule is not necessarily**. Every
    rule in ``is_ignored`` is anchored at the LISTING PREFIX, which is right for the three
    analytics planes — they list a table's or a check's own folder — and wrong for file-send,
    whose listing prefix is whichever item the user picked. There the same rule would drop a
    user's own ``reports/athenaresults/`` and any underscore-prefixed folder from a copy,
    silently. So the predicate is a parameter rather than a fork of the paginator: one place
    still pages past 1000 keys, and a plane whose exclusions are anchored somewhere else says
    so at the call site.

    Args:
      bucket: The bucket to list.
      prefix: The request prefix.
      relative: Yield keys relative to the prefix instead of absolute ones. Table-share
        passes True and re-roots them under each recipient's path; table-builder and
        data-quality need absolute keys for manifests and sample keys.
      ignore: Predicate receiving ``(key, size, prefix)`` and reporting whether the object is
        something other than source data. Defaults to the analytics rule above; file-send
        passes its own, anchored at the space root.

    Yields:
      ``(key, size)`` for each data object.

    Raises:
      ClientError: Propagated raw from the paginator.
    """
    for record in list_data_records(bucket, prefix, ignore=ignore):
        key = record["key"]
        yield (key[len(prefix):] if relative else key), record["size"]


def object_size(bucket: str, key: str, *, missing_reason: str) -> int:
    """Reads one selected file's size, or fails the request naming it.

    A file item costs its own serial ``HeadObject`` where a folder item costs one listing page
    per thousand objects, which is why a plane's per-item timeout is sized against the number of
    ITEMS rather than the number of objects.

    Args:
      bucket: The source bucket.
      key: The selected file's key.
      missing_reason: The caller's registered terminal reason for a source object that cannot be
        read. Required rather than defaulted so the wording stays the domain layer's, as it is
        for every other reason code this layer takes.

    Returns:
      The object's size in bytes.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb.
      TerminalError: ``missing_reason``, naming the key, when the object is absent or unreadable.
    """
    try:
        return int(clients.s3().head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception as err:
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise TerminalError(missing_reason, f"{key!r}: {err}") from err
