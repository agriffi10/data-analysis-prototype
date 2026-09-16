"""The JSON Lines transfer manifest a Distributed Map reads its items from.

One line per transfer item, written to the admin bucket and handed to the Map's ``ItemReader``
as ``InputType: JSONL``. It replaces putting the item list on the state: the list runs to the
share caps, and Step Functions caps a state payload at 256 KB.

The writer is deliberately the only place the file format is decided. A trailing newline is NOT
written — a blank final line is a line the reader may hand back as an empty item, and an empty
item would reach the copier as a transfer with no source. Where the manifest LIVES is the
calling plane's business: this module writes the bytes, the domain layer owns the key layout.

Attributes:
  CONTENT_TYPE: Written so an operator opening the object in the console gets text rather than
    a download. Step Functions ignores it.
"""

import json

from .. import clients, errors, observability

CONTENT_TYPE = "application/jsonl"


@observability.step("write-transfer-manifest")
def write_manifest(bucket: str, key: str, items: list) -> int:
    """Writes the transfer items as JSON Lines and returns how many were written.

    **Call bound: at most once per invocation**, in each of the five build-manifest verbs that
    reach it. AT MOST rather than exactly: file-ops guards the call with ``if lines:``, and
    file-send and table-share return early when there is nothing to send, so a verb can complete
    without writing one. Never more than once, which is the property that makes a child span
    here two events per invocation rather than two per item.

    Args:
      bucket: The bucket to write to.
      key: The manifest key.
      items: The transfer items, each a JSON-serialisable mapping.

    Returns:
      The number of lines written, which is the Map's item count.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the whole verb.
        Safe because a Retry of one run writes the same key again — the key carries the run's
        execution name or its request id — and the write is a whole-object PUT.
      ClientError: Any deterministic fault propagates.
    """
    body = "\n".join(json.dumps(item, separators=(",", ":")) for item in items).encode()
    try:
        clients.s3().put_object(Bucket=bucket, Key=key, Body=body, ContentType=CONTENT_TYPE)
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise
    return len(items)
