"""The document routes — raw bytes, never parsed.

Nine JSON reads across seven modules, one write, one quarantine copy, two marker writes and a
folder placeholder all ride these two routes.

**Parsing server-side is the wrong implementation that looks identical.** It works for every
healthy document and turns an unparseable one into a 500 — which puts the browser's whole
quarantine path out of reach, because the classifier never sees the body it must classify as
unreadable. The bytes go out as they came in and the browser decides what they are.

**Re-serialising on write is the same defect from the other side.** ``json.dumps`` of a parsed body
changes key order and whitespace: nothing visible breaks, and byte-identity does.

**The byte cap is what holds the line between this route and presigning.** Without it the document
route is a second upload path that bypasses the presigned ``PUT`` entirely and works perfectly up
to Lambda's 6 MB response ceiling.
"""

from typing import Any

from apicommon import protected, s3_config
from apicommon.context import RequestContext
from apicommon.envelope import ApiError

from . import _objects


def read_content(context: RequestContext) -> dict[str, Any]:
    """Returns an object's bytes, decoded as UTF-8 and not parsed.

    Args:
      context: The authenticated request.

    Returns:
      The decoded body and the object's ETag.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key; ``NotFound`` when
        absent; ``PayloadTooLarge`` above the cap; ``InvalidRequest`` when the stored bytes are
        not valid UTF-8 — refused rather than substituted, because a silent ``errors='replace'``
        writes corruption back on the next read-modify-write.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    space = _objects.space_from_query(context)
    key = _objects.contained(space, context.query.get("key", ""))
    client = _objects.client(context)

    try:
        stored = client.get_object(Bucket=space.bucket, Key=key)
    except Exception as exc:
        if _objects.is_missing(exc):
            raise ApiError("NotFound", "no object at that key") from exc
        raise

    if int(stored.get("ContentLength", 0)) > s3_config.MAX_DOCUMENT_BYTES:
        raise ApiError(
            "PayloadTooLarge",
            "document exceeds the readable cap",
            {"limit": s3_config.MAX_DOCUMENT_BYTES},
        )

    raw = stored["Body"].read()
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError("InvalidRequest", "stored bytes are not valid UTF-8") from exc

    return {"body": body, "etag": str(stored.get("ETag", "")).strip('"')}


def write_content(context: RequestContext) -> dict[str, Any]:
    """Writes a body byte for byte.

    Args:
      context: The authenticated request.

    Returns:
      The key written and its new ETag.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space, an escaping key, a marker key or a
        write-locked location; ``PayloadTooLarge`` above the cap, refused BEFORE any S3 call;
        ``Conflict`` when the key is occupied and ``overwrite`` is false.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    protected.assert_writable(space, key)

    payload = str(body.get("body", "")).encode("utf-8")
    if len(payload) > s3_config.MAX_DOCUMENT_BYTES:
        raise ApiError(
            "PayloadTooLarge",
            "document exceeds the writable cap",
            {"limit": s3_config.MAX_DOCUMENT_BYTES},
        )

    client = _objects.client(context)
    if not body.get("overwrite", False):
        _refuse_if_occupied(client, space.bucket, key)

    written = client.put_object(
        Bucket=space.bucket,
        Key=key,
        Body=payload,
        ContentType=str(body.get("contentType", "application/octet-stream")),
    )
    return {"key": key, "etag": str(written.get("ETag", "")).strip('"')}


def _refuse_if_occupied(client: Any, bucket: str, key: str) -> None:
    """Refuses a write onto an existing object.

    The collision head moves inside the route, so a caller pays one call rather than two — and
    the two cannot disagree, which they can when the check is a separate request.

    Args:
      client: The S3 client.
      bucket: The bucket.
      key: The key being written.

    Returns:
      None.

    Raises:
      ApiError: ``Conflict`` naming the leaf, when the key is occupied.
    """
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _objects.is_missing(exc):
            return
        raise
    raise ApiError("Conflict", "destination is occupied", {"name": key.rsplit("/", 1)[-1]})
