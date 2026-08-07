"""Parallel, layout-preserving, server-side S3 copy for a share recipient.

No object data passes through the Lambda: small objects use a single server-side copy, and
objects over S3's single-copy limit use a multipart part-copy. A retried copy re-copies the
same keys harmlessly, so the Step Function can re-run the whole verb on a transient failure.

Attributes:
  MULTIPART_COPY_THRESHOLD: S3's single-request copy ceiling; larger objects must
    multipart-copy.
  MULTIPART_PART_SIZE: Byte range per part copy.
  COPY_CONCURRENCY: Bounded worker pool for the per-recipient fan-out. The share caps bound
    the total work; this bounds the parallelism.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients, errors
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger(__name__)

MULTIPART_COPY_THRESHOLD = 5 * 1024**3
MULTIPART_PART_SIZE = 1024**3

COPY_CONCURRENCY = 8


def _raise_mapped(exc: Exception, detail: str):
    """Routes a copy fault to the Step Function's retry or fail path.

    Delegates the transient classification to the canonical classifier; if that returns, the
    fault is deterministic. A transient throttle or 5xx retries the whole idempotent verb,
    while anything else is a per-recipient failure.

    Args:
      exc: The fault to classify.
      detail: Context for the raised error's detail.

    Returns:
      Never returns.

    Raises:
      TransientError: On a retryable fault.
      TerminalError: ``copy_failed`` on a deterministic one.
    """
    errors.raise_if_transient(exc, detail)
    raise TerminalError("copy_failed", f"{detail}: {exc}") from exc


def _copy_one(s3, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str, size: int) -> None:
    """Copies one object server-side, choosing single or multipart by its size.

    A failed multipart upload is aborted so it never leaves a half-open upload accruing
    storage. The abort itself is best-effort, since an expired upload lifecycles away.

    Args:
      s3: The S3 client.
      src_bucket: Source bucket.
      src_key: Source key.
      dest_bucket: Destination bucket.
      dest_key: Destination key.
      size: The object's byte size, deciding the copy strategy.

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault.
      TerminalError: ``copy_failed`` on a deterministic one.
    """
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
            try:
                s3.abort_multipart_upload(Bucket=dest_bucket, Key=dest_key, UploadId=upload_id)
            except Exception:  # noqa: BLE001
                logger.warning("abort_multipart_upload failed for %s/%s", dest_bucket, dest_key)
            raise
    except (TerminalError, TransientError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_mapped(exc, f"copy {src_bucket}/{src_key} -> {dest_bucket}/{dest_key}")


def copy_prefix(
    src_bucket: str,
    src_prefix: str,
    objects: list,
    dest_bucket: str,
    dest_prefix: str,
    concurrency: int = COPY_CONCURRENCY,
) -> int:
    """Copies every planned object to the destination prefix, preserving the layout.

    Args:
      src_bucket: Source bucket.
      src_prefix: Source prefix the relative keys hang off.
      objects: The planned objects, each carrying a relative key and size.
      dest_bucket: Destination bucket.
      dest_prefix: Destination prefix the relative keys are re-rooted under.
      concurrency: Worker pool size.

    Returns:
      The number of objects copied.

    Raises:
      TransientError: On a retryable fault, after in-flight copies settle.
      TerminalError: ``copy_failed`` on a deterministic one, after in-flight copies settle.
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
