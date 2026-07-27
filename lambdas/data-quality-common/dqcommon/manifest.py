"""Reading the source manifest inspect-source wrote (SPEC-110 -> SPEC-111/112).

The manifest — ``{space}/_data-quality-reports/{requestId}/manifest.json`` — carries the
per-file key/size/columns and the detected partition keys. It is passed between states by
POINTER, never inline, and this module is the one place that turns the pointer back into
data.

WHY IT IS NOT IN THE STATE: at the caps (1000 files x 1024-char keys x 50 columns) the
manifest measures ~2.6 MB, and a Step Functions state payload over 256 KB raises
States.DataLimitExceeded — which is thrown OUTSIDE every Catch. The execution would die
without reaching NotifyFailure, so the user would be told NOTHING, on exactly the biggest
folders. That is the worst failure mode in the pipeline and this indirection is what
avoids it.

``inspect-source`` still owns the WRITE side (its error handling is bespoke — a lost
manifest must be a retryable fault, because the verb is replay-safe and a Retry simply
rewrites it).
"""

import json

from cpcommon import clients, errors
from cpcommon.errors import TerminalError

from . import messages


def load(bucket: str, key: str) -> dict:
    """Return the parsed manifest at ``s3://{bucket}/{key}``.

    Raises:
        TransientError: on a retryable S3 fault, so the caller's Step Function ``Retry``
            re-runs the verb rather than failing a request over a one-off SlowDown.
        TerminalError: ``invalid_request`` when the manifest cannot be read or parsed —
            by this point inspect-source has already written it, so a failure here means
            the object is missing or corrupt, which no retry will fix.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise TerminalError(
            messages.INVALID_REQUEST, f"could not read manifest {key}: {err}"
        ) from err

    try:
        return json.loads(body)
    except ValueError as err:
        raise TerminalError(
            messages.INVALID_REQUEST, f"manifest {key} is not valid JSON: {err}"
        ) from err
