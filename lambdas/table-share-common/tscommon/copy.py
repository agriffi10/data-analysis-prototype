"""Parallel, layout-preserving, server-side S3 copy (SPEC-091).

copy_prefix copies every planned object from the source prefix to the recipient
destination with a bounded thread pool. No object data passes through the Lambda:
small objects use a single server-side CopyObject; objects over S3's 5 GiB
single-copy limit use multipart UploadPartCopy. A retried copy re-copies the same
keys harmlessly (idempotent), so the Step Function can re-run the whole verb on a
transient failure.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger(__name__)

# S3's single-request CopyObject ceiling; larger objects must multipart-copy.
MULTIPART_COPY_THRESHOLD = 5 * 1024**3  # 5 GiB
MULTIPART_PART_SIZE = 1024**3  # 1 GiB per UploadPartCopy range

# Bounded worker pool for the per-recipient copy fan-out (lambdas.md: bound
# parallelism; the SPEC-090 caps bound the total work).
COPY_CONCURRENCY = 8

# Error codes that are worth a Step Function retry of the whole (idempotent) verb;
# anything else is a deterministic per-recipient copy failure.
_TRANSIENT_CODES = frozenset(
    {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "Throttling", "503", "500"}
)


def _raise_mapped(exc: Exception, detail: str):
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    if code in _TRANSIENT_CODES:
        raise TransientError(f"{detail}: {exc}") from exc
    raise TerminalError("copy_failed", f"{detail}: {exc}") from exc


def _copy_one(s3, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str, size: int) -> None:
    source = {"Bucket": src_bucket, "Key": src_key}
    try:
        if size <= MULTIPART_COPY_THRESHOLD:
            s3.copy_object(Bucket=dest_bucket, Key=dest_key, CopySource=source)
            return
        upload = s3.create_multipart_upload(Bucket=dest_bucket, Key=dest_key)
        upload_id = upload["UploadId"]
        try:
            parts = []
            offset = 0
            part_number = 1
            while offset < size:
                end = min(offset + MULTIPART_PART_SIZE, size) - 1
                resp = s3.upload_part_copy(
                    Bucket=dest_bucket,
                    Key=dest_key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    CopySource=source,
                    CopySourceRange=f"bytes={offset}-{end}",
                )
                parts.append({"ETag": resp["CopyPartResult"]["ETag"], "PartNumber": part_number})
                offset = end + 1
                part_number += 1
            s3.complete_multipart_upload(
                Bucket=dest_bucket,
                Key=dest_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            # Never leave a half-open upload accruing storage; the abort itself is
            # best-effort (an expired upload lifecycles away).
            try:
                s3.abort_multipart_upload(Bucket=dest_bucket, Key=dest_key, UploadId=upload_id)
            except Exception:  # noqa: BLE001
                logger.warning("abort_multipart_upload failed for %s/%s", dest_bucket, dest_key)
            raise
    except (TerminalError, TransientError):
        raise
    except Exception as exc:  # noqa: BLE001 - mapped to the SFN's retry/fail routing
        _raise_mapped(exc, f"copy {src_bucket}/{src_key} -> {dest_bucket}/{dest_key}")


def copy_prefix(
    src_bucket: str,
    src_prefix: str,
    objects: list,
    dest_bucket: str,
    dest_prefix: str,
    concurrency: int = COPY_CONCURRENCY,
) -> int:
    """Copy every ``{relKey, size}`` object to ``dest_prefix``, layout preserved.

    Returns the number of objects copied. The first failure propagates (mapped to
    TransientError/TerminalError) after in-flight copies settle.
    """
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _copy_one,
                clients.s3(),
                src_bucket,
                f"{src_prefix}{obj['relKey']}",
                dest_bucket,
                f"{dest_prefix}{obj['relKey']}",
                obj.get("size", 0),
            )
            for obj in objects
        ]
        for future in futures:
            future.result()
    return len(objects)
