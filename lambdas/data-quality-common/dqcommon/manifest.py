"""Reading the source manifest inspect-source wrote.

The manifest carries the per-file key, size and columns plus the detected partition keys. It is
passed between states by pointer, never inline, and this module is the one place that turns the
pointer back into data.

It is not on the state because at the caps the manifest measures megabytes, and a state payload
over the limit raises ``States.DataLimitExceeded``, which escapes every Catch here
(``States.ALL`` does not match it and none names it). The execution would die without
reaching the notify state, so the user would be told nothing, on exactly the biggest folders —
the worst failure mode in the pipeline, and what this indirection avoids.

inspect-source still owns the write side: its error handling is bespoke, because a lost manifest
must be a retryable fault — the verb is replay-safe and a retry simply rewrites it.

**What is read back is not trusted to stay inside the check.** The key is a pure function of a
caller-supplied request id, so it is predictable, and more than one writer can reach it. Every
reader here would otherwise dereference whatever keys it names under a role that can read every
object in both buckets — byte-scan GETs each one — so a manifest naming another tenant's file would
put that file's byte-level findings in this check's report. The loader refuses any file outside the
checked location, which is exactly the set inspect-source lists, so the containment holds whoever
wrote the object.
"""

import json
from typing import cast

from cpcommon import clients, errors
from cpcommon.errors import TerminalError

from . import messages


def load(bucket: str, key: str, location: str) -> dict:
    """Reads and parses the manifest at one object key, refusing one that names a foreign file.

    Args:
      bucket: The manifest's bucket.
      key: The manifest key.
      location: The checked location from the state, which every listed file must be or sit under.

    Returns:
      The parsed manifest.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb rather
        than failing a request over a one-off throttle.
      TerminalError: ``invalid_request`` when the manifest cannot be read or parsed, or names a
        file outside the location. By this point inspect-source has already written it, so a
        failure here means the object is missing, corrupt or not the one it wrote, which no retry
        will fix.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise TerminalError(
            messages.INVALID_REQUEST, f"could not read manifest {key}: {err}"
        ) from err

    try:
        manifest = cast("dict", json.loads(body))
    except ValueError as err:
        raise TerminalError(
            messages.INVALID_REQUEST, f"manifest {key} is not valid JSON: {err}"
        ) from err
    _refuse_foreign_files(manifest, key, location)
    return manifest


def _refuse_foreign_files(manifest: object, key: str, location: str) -> None:
    """Refuses a manifest listing any file that is not the location or beneath it.

    The comparison appends the slash rather than matching the bare location as a prefix, because a
    listing is a prefix match and ``alice/sales`` would otherwise admit ``alice/sales-2024/a.csv``,
    a sibling the user never selected — the same hazard inspect-source's own listing guards against.
    The key equal to the location is a single-file check's one file.

    Args:
      manifest: The parsed manifest.
      key: The manifest key, for the detail.
      location: The checked location.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_request`` when the manifest is not an object, its file list is not
        a list, or any entry is not an object naming a key inside the location. The detail names
        the manifest and never the foreign key.
    """
    target = location.rstrip("/")
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise TerminalError(messages.INVALID_REQUEST, f"manifest {key} carries no file list")
    for entry in files:
        name = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not (name == target or name.startswith(f"{target}/")):
            raise TerminalError(
                messages.INVALID_REQUEST, f"manifest {key} names a file outside the checked location"
            )
