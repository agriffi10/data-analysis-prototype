"""Paginated S3 listing plus the shared ignore rules for table-builder sources.

The single source of "what counts as a data object": the prefix marker
(DO_NOT_DELETE.txt), the athenaresults/ sub-tree, zero-byte objects (folder
placeholders), and hidden/partial files (basename starting "_" or ".") are not data.
"""

from . import clients

# The user-space / shared-space prefix marker written at folder creation.
MARKER_BASENAME = "DO_NOT_DELETE.txt"


def _basename(key):
    return key.rsplit("/", 1)[-1]


def is_ignored(key, size, prefix):
    """True if ``key`` is not a data object (marker / results / placeholder / hidden).

    ``prefix`` is the request prefix, used to spot the ``athenaresults/`` sub-tree
    relative to it. ``size`` is the object's byte size (zero-byte = folder marker).
    """
    rel = key[len(prefix):] if key.startswith(prefix) else key
    # Athena query results live under {space}/athenaresults/ — never source data.
    if rel.startswith("athenaresults/"):
        return True
    base = _basename(key)
    if base == "":  # a "folder" key ending in "/"
        return True
    if base == MARKER_BASENAME:
        return True
    if base.startswith("_") or base.startswith("."):
        return True
    if size == 0:
        return True
    return False


def list_data_objects(bucket, prefix):
    """Yield ``(key, size)`` for every non-ignored data object under ``prefix``.

    Paginated (handles > 1000 objects). Transient S3 errors propagate so the Step
    Function's Retry can handle them — they are never swallowed.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            if is_ignored(key, size, prefix):
                continue
            yield key, size
