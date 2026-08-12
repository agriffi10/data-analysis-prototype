"""``_manifest.json`` — the integrity record that sits with the archived data.

Written to the ARCHIVE bucket at ``{archiveRoot}_manifest.json``, where the user cannot reach it,
before the source is deleted. It records what the run believed it had copied: the request, the
actor, the source it came from, the object count and the byte total.

**It is a record, not a lookup table, and nothing may come to depend on it.** SPEC-170 rebuilds
every restore destination by listing the archive prefix and running each key through
``paths.origin_key`` — the archived key encodes its own origin — exactly as SPEC-143 judges a
table by its shape rather than by the marker it also writes. That is what makes a lost, truncated
or hand-edited manifest unable to make a restore wrong, and it is why the only consumers here are
the count/byte cross-check and a human reading a failed run.
``test_no_restore_verb_requires_the_manifest`` holds that open for the specs that add those verbs.

**The write is ordered most durable to least**: this file, then the source deletion, then the
receipt — the same ordering the data-quality plane uses for its report, notification and index.
A manifest with no receipt is a recoverable state an operator can read; a receipt with no archive
is not.

Attributes:
  BASENAME: The object's name at the archive root. The leading underscore keeps it out of the way
    of the archived keys beside it, all of which are the user's own relative paths.
  VERSION: The document's schema version, present from the first write so a later shape can be
    told from this one rather than guessed at.
"""

import json

from cpcommon import clients, errors

from .config import ARCHIVE_STORAGE_CLASS

BASENAME = "_manifest.json"

VERSION = 1


def write(bucket: str, archive_root: str, record: dict) -> str:
    """Writes the integrity record at the archive root and returns its key.

    Args:
      bucket: The archive bucket.
      archive_root: The prefix this archive occupies, ending in a slash.
      record: The run's outcome — request id, actor, the source location, the object count, the
        byte total and the execution's start time.

    Returns:
      The key the record was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb — safe,
        because the key is a pure function of the archive root and the write is a whole-object
        PUT.
      ClientError: Any deterministic fault propagates. It is a whole-request failure BEFORE
        anything has been deleted, which is the cheapest moment on this plane for one to happen.
    """
    source = record.get("source") or {}
    key = f"{archive_root}{BASENAME}"
    body = json.dumps(
        {
            "version": VERSION,
            "requestId": record.get("requestId"),
            "archivedAt": record.get("startedAt"),
            "actor": record.get("actor"),
            "source": {"bucket": source.get("bucket"), "root": source.get("root")},
            "objectCount": record.get("objectCount"),
            "totalBytes": record.get("totalBytes"),
            "storageClass": ARCHIVE_STORAGE_CLASS,
        },
        separators=(",", ":"),
    ).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise
    return key
