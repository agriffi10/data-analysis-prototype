"""Paginated S3 listing plus the shared ignore rules for table-share sources.

The single source of "what counts as a data object" (mirrors the table-builder
rules): the prefix marker (DO_NOT_DELETE.txt), the athenaresults/ sub-tree,
zero-byte objects (folder placeholders), and hidden/partial files (basename
starting "_" or ".") are not data — they are excluded from the copy plan.
"""

from collections.abc import Iterator

from . import clients

# The user-space / shared-space prefix marker written at folder creation.
MARKER_BASENAME = "DO_NOT_DELETE.txt"


def _basename(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def is_ignored(key: str, size: int, prefix: str) -> bool:
    """True if ``key`` is not a data object (marker / results / placeholder / hidden)."""
    rel = key[len(prefix):] if key.startswith(prefix) else key
    # Athena query results live under {space}/athenaresults/ — never source data.
    if rel.startswith("athenaresults/"):
        return True
    base = _basename(key)
    if base == "":  # a "folder" key ending in "/"
        return True
    if base == MARKER_BASENAME:
        return True
    # Any hidden/temporary path SEGMENT under the prefix excludes the object —
    # Athena ignores `_`/`.`-prefixed files AND directories (e.g. Spark
    # `_temporary/`), so they must not enter the copy plan either. (Deliberately
    # extends the table-builder's basename-only rule.)
    if any(segment.startswith(("_", ".")) for segment in rel.split("/") if segment):
        return True
    if size == 0:
        return True
    return False


def list_data_objects(bucket: str, prefix: str) -> Iterator[tuple[str, int]]:
    """Yield ``(relative_key, size)`` for every non-ignored data object under ``prefix``.

    Keys are RELATIVE to ``prefix`` (the copy step re-roots them under each
    recipient's shared_tables/{tableName}/ prefix, layout preserved). Paginated
    (handles > 1000 objects). Transient S3 errors propagate so the Step Function's
    Retry can handle them — they are never swallowed.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            if is_ignored(key, size, prefix):
                continue
            yield key[len(prefix):], size
