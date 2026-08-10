"""Reading the source manifest inspect-source wrote.

The manifest carries the per-file key, size and columns plus the detected partition keys. It is
passed between states by pointer, never inline, and this module is the one place that turns the
pointer back into data.

It is not on the state because at the caps the manifest measures megabytes, and a state payload
over the limit raises an error thrown outside every Catch. The execution would die without
reaching the notify state, so the user would be told nothing, on exactly the biggest folders —
the worst failure mode in the pipeline, and what this indirection avoids.

inspect-source still owns the write side: its error handling is bespoke, because a lost manifest
must be a retryable fault — the verb is replay-safe and a retry simply rewrites it.
"""

import json
from typing import cast

from cpcommon import clients, errors
from cpcommon.errors import TerminalError

from . import messages


def load(bucket: str, key: str) -> dict:
    """Reads and parses the manifest at one object key.

    Args:
      bucket: The manifest's bucket.
      key: The manifest key.

    Returns:
      The parsed manifest.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb rather
        than failing a request over a one-off throttle.
      TerminalError: ``invalid_request`` when the manifest cannot be read or parsed. By this
        point inspect-source has already written it, so a failure here means the object is
        missing or corrupt, which no retry will fix.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise TerminalError(
            messages.INVALID_REQUEST, f"could not read manifest {key}: {err}"
        ) from err

    try:
        return cast("dict", json.loads(body))
    except ValueError as err:
        raise TerminalError(
            messages.INVALID_REQUEST, f"manifest {key} is not valid JSON: {err}"
        ) from err
