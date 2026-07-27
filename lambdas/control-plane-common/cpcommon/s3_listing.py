"""Paginated S3 listing plus the shared "what counts as a data object" rules (SPEC-107).

The single source of the ignore rules for every control plane's source listing: the
prefix marker (DO_NOT_DELETE.txt), the ``athenaresults/`` and ``user_settings/``
sub-trees, zero-byte placeholders, and hidden/partial paths are never source data.

SPEC-107 FR-003 fixes two things the twins disagreed on:

- **Segment-level hidden rule.** Any ``_``/``.``-prefixed path SEGMENT under the request
  prefix excludes the object — not just the basename. tbcommon's basename-only rule
  meant ``alice/_data-quality-reports/x/report.json`` was NOT ignored (the ``_`` is in a
  directory segment), so Table Builder would ingest this arc's own hidden reports as
  source data. Athena ignores ``_``/``.``-prefixed files AND directories (e.g. Spark
  ``_temporary/``), so they must not enter any plan either.
- **Yield semantics.** ``list_data_objects`` yields ABSOLUTE keys by default (table
  builder / data quality need them for ``sampleObjectKey`` and manifests) and takes
  ``relative: bool = False``; table-share's call sites pass ``relative=True`` to get the
  prefix-relative keys the copy step re-roots.
"""

from collections.abc import Iterator

from . import clients

# The user-space / shared-space prefix marker written at folder creation.
MARKER_BASENAME = "DO_NOT_DELETE.txt"

# First-segment sub-trees that are never source data, regardless of a leading underscore.
# athenaresults/ holds query output; user_settings/ holds the notification inbox + saved
# queries (no leading underscore, so the segment rule below wouldn't catch it — but a
# folder-level scan reaching a space root must never treat those as source data).
_IGNORED_SUBTREES = ("athenaresults/", "user_settings/")


def _basename(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def is_ignored(key: str, size: int, prefix: str) -> bool:
    """True if ``key`` is not a data object (marker / results / settings / placeholder / hidden).

    ``prefix`` is the request prefix; ``rel`` is ``key`` relative to it. ``size`` is the
    object's byte size (zero-byte = folder placeholder).
    """
    rel = key.removeprefix(prefix)
    if rel.startswith(_IGNORED_SUBTREES):
        return True
    base = _basename(key)
    if base == "":  # a "folder" key ending in "/"
        return True
    if base == MARKER_BASENAME:
        return True
    # Segment-level hidden rule: any hidden/temporary path segment under the prefix
    # excludes the object (FR-003 — extends tbcommon's basename-only check).
    if any(segment.startswith(("_", ".")) for segment in rel.split("/") if segment):
        return True
    return size == 0


def list_data_objects(bucket: str, prefix: str, relative: bool = False) -> Iterator[tuple[str, int]]:
    """Yield ``(key, size)`` for every non-ignored data object under ``prefix``.

    Keys are ABSOLUTE by default; pass ``relative=True`` to get keys relative to
    ``prefix`` (table-share re-roots them under each recipient's ``shared_tables/`` path).
    Paginated (handles > 1000 objects).

    Errors are NEVER swallowed — a paginator fault propagates raw. But "raw" means a
    botocore ``ClientError``, which a Step Function sees by its PYTHON CLASS NAME
    (``errorType: "ClientError"``); a verb's Retry list names ``TransientError``, not
    ``ClientError``, so a raw fault is NOT retried by default. Mapping a throttle/5xx to
    ``TransientError`` is the CALLER's job (see ``cpcommon.errors`` +
    ``table-share-common/tscommon/copy.py`` / ``data-quality-inspect-source`` for the
    pattern), and only helps under a state whose Retry actually names ``TransientError``.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            if is_ignored(key, size, prefix):
                continue
            yield (key[len(prefix):] if relative else key), size
