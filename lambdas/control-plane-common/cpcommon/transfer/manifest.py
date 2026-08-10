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

from .. import clients, errors

CONTENT_TYPE = "application/jsonl"


def write_manifest(bucket: str, key: str, items: list) -> int:
    """Writes the transfer items as JSON Lines and returns how many were written.

    Args:
      bucket: The bucket to write to.
      key: The manifest key.
      items: The transfer items, each a JSON-serialisable mapping.

    Returns:
      The number of lines written, which is the Map's item count.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the whole verb.
        Safe because the key is execution-unique and the write is a whole-object PUT.
      ClientError: Any deterministic fault propagates.
    """
    body = "\n".join(json.dumps(item, separators=(",", ":")) for item in items).encode()
    try:
        clients.s3().put_object(Bucket=bucket, Key=key, Body=body, ContentType=CONTENT_TYPE)
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise
    return len(items)
