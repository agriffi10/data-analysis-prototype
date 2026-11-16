"""The multipart upload lifecycle, and the one decision the browser is not allowed to make.

**The SERVER decides which path an upload takes.** ``create`` answers ``single`` with a presigned
``PUT`` or ``multipart`` with a plan, and the threshold is never sent to the browser: a second copy
of a policy number in the SPA would drift, and a drifted copy sends files down the wrong path with
nothing failing.

**The upload id is a capability, not evidence.** Every route here re-authorizes from the caller's
verified claims — space resolution and key containment run on part, complete and abort exactly as
they run on create. The id looks like authorization, which is what makes that easy to get wrong,
and it buys nothing: the ``(key, uploadId)`` pair is checked by S3 itself, so the API keeps no
record of an upload and there is no second copy of that state to go stale.

**Each part URL is a bearer token** and inherits every rule the single ``PUT`` already follows —
minted through ``identity.signing_client``, clamped to the credential that actually signed, and in
no emitted record. The span carries the part number and the key's length; it carries neither the
URL nor the upload id.

**S3's multipart faults are mapped here, per route, and not by the classifier.** ``errors``
maps its denial set to 403 unconditionally, so teaching it ``NoSuchUpload`` would answer "you lack
a permission" for an upload that simply expired. Without a mapping a fault becomes the deliberately
generic ``InternalError``, so the per-route raise is what makes an authored sentence possible.

Attributes:
  _ABSENT_UPLOAD_CODES: What S3 calls an upload that is finished, abandoned or expired. Answered
    **404**, never 403 — the denial classifier maps its whole set to "you lack a permission"
    unconditionally, which is the wrong sentence for an upload that simply ran out.
  _MALFORMED_PART_CODES: The three ways a part list fails to assemble. They share one answer, so
    the tests discriminate them by FIXTURE: asserting the shared code against one of them would
    pass with the other two unmapped.
"""

from typing import Any

from apicommon import identity, protected, s3_config
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from apicommon.spaces import ResolvedSpace
from cpcommon import observability

from . import _objects, _presign

_ABSENT_UPLOAD_CODES = {"NoSuchUpload"}
_MALFORMED_PART_CODES = {"InvalidPart", "InvalidPartOrder", "EntityTooSmall"}


def create(context: RequestContext) -> dict[str, Any]:
    """Begins an upload, choosing its shape from the declared size.

    The plan is computed before any client is built, so a size no plan can serve is refused
    without costing an ``AssumeRole`` — a refusal issued after one is indistinguishable from an
    IAM denial to anything outside the process.

    The comparison is strictly greater-than, so an object of exactly the threshold takes the
    single ``PUT``: below it multipart buys retry granularity costing more round trips than the
    restart it saves.

    Args:
      context: The authenticated request.

    Returns:
      Either ``{mode: "single", url, expiresAt}`` or
      ``{mode: "multipart", uploadId, partSize, partCount}``.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space, an escaping key, a marker key, a
        write-locked location, the query results folder or the data-quality reports folder;
        ``PayloadTooLarge`` when no plan can serve the declared size;
        ``Conflict`` when the key is occupied and ``overwrite`` is false — and NOTHING is created
        in that case, neither a url nor an upload.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    overwrite = bool(body.get("overwrite", False))
    content_type = str(body.get("contentType", "application/octet-stream"))
    protected.assert_replaceable(space, key)

    size = _declared_size(body)

    if size > s3_config.MULTIPART_THRESHOLD_BYTES:
        part_size, part_count = part_plan(size)
        client = _objects.client(context)
        _refuse_if_occupied(client, space, key, overwrite)
        upload_id = _created(client, space, key, content_type)
        observability.stamp(
            space_kind=space.kind,
            key_length=len(key),
            upload_mode="multipart",
            part_count=part_count,
        )
        return {
            "mode": "multipart",
            "uploadId": upload_id,
            "partSize": part_size,
            "partCount": part_count,
        }

    client, credentials = identity.signing_client(
        "s3", context.acting_as, covering=s3_config.UPLOAD_URL_EXPIRY_SECONDS
    )
    _refuse_if_occupied(client, space, key, overwrite)
    seconds = _presign.clamped(s3_config.UPLOAD_URL_EXPIRY_SECONDS, credentials)
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": space.bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=seconds,
    )
    minted = _presign.minted(
        url, seconds, key, space_kind=space.kind, upload_mode="single"
    )
    return {"mode": "single", **minted}


def sign_part(context: RequestContext) -> dict[str, Any]:
    """Mints the presigned PUT for one part.

    One part per call. A batch would age while the parts ahead of it upload, so its last URL
    would be signed long before it was redeemed — which is the failure the whole design removes.

    **It runs the same protected-location check ``create`` runs**, and not because a caller could
    get anywhere without it: minting needs an ``uploadId`` that ``create`` refuses to issue for
    these keys, and for the receipt folder the portal role Denies the write underneath. It runs
    because the rule is that a presigned URL is minted only after *exactly* the authorization the
    direct call would have had, and a route that mints where its sibling refuses has already broken
    that rule whether or not the URL is redeemable.

    Args:
      context: The authenticated request.

    Returns:
      The URL and when it expires.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space, an escaping key, a marker key, a
        write-locked location, the query results folder or the data-quality reports folder;
        ``InvalidRequest`` on a part number outside S3's range.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    protected.assert_replaceable(space, key)
    upload_id = _upload_id(body)
    part_number = _part_number(body)

    client, credentials = identity.signing_client(
        "s3", context.acting_as, covering=s3_config.PART_URL_EXPIRY_SECONDS
    )
    seconds = _presign.clamped(s3_config.PART_URL_EXPIRY_SECONDS, credentials)
    url = client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": space.bucket,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=seconds,
    )
    return _presign.minted(
        url, seconds, key, space_kind=space.kind, part_number=part_number
    )


def complete(context: RequestContext) -> dict[str, Any]:
    """Assembles the uploaded parts into the object.

    **The collision check runs AGAIN here when ``overwrite`` is false.** The create-time check
    answered about a moment that can be hours earlier, and a long upload is exactly when the user
    re-creates the file they are replacing — so completing over what arrived in between would
    report success while destroying it. ``If-None-Match: *`` makes S3 decide it at the instant
    the object is written, which no read-then-write could.

    Args:
      context: The authenticated request.

    Returns:
      The key written and its ETag.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key; ``NotFound`` when
        the upload id is unknown or expired; ``InvalidRequest`` when the part list does not
        assemble; ``Conflict`` when the key was taken while the upload ran and ``overwrite`` is
        false — and that refusal leaves the upload IN PROGRESS, since only the caller knows
        whether it wants to retry or abandon. Nothing here aborts it; the bucket's seven-day
        lifecycle rule is the only sweep.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    upload_id = _upload_id(body)
    overwrite = bool(body.get("overwrite", False))
    parts = _parts(body)

    client = _objects.client(context)
    request: dict[str, Any] = {
        "Bucket": space.bucket,
        "Key": key,
        "UploadId": upload_id,
        "MultipartUpload": {"Parts": parts},
    }
    if not overwrite:
        request["IfNoneMatch"] = "*"

    observability.stamp(space_kind=space.kind, key_length=len(key), part_count=len(parts))
    try:
        answer = client.complete_multipart_upload(**request)
    except Exception as exc:
        code = identity.aws_error_code(exc)
        if code in _ABSENT_UPLOAD_CODES:
            raise ApiError("NotFound", "that upload is no longer in progress") from exc
        if code in _MALFORMED_PART_CODES:
            raise ApiError("InvalidRequest", "the uploaded parts did not assemble") from exc
        if code == "PreconditionFailed":
            raise ApiError(
                "Conflict", "destination is occupied", {"name": key.rsplit("/", 1)[-1]}
            ) from exc
        raise
    return {"key": key, "etag": str(answer.get("ETag", "")).strip('"')}


def abort(context: RequestContext) -> dict[str, Any]:
    """Abandons an upload so S3 discards its parts.

    Args:
      context: The authenticated request.

    Returns:
      The key that will not be written.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key; ``NotFound`` when
        the upload id is unknown or already finished.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    upload_id = _upload_id(body)

    client = _objects.client(context)
    observability.stamp(space_kind=space.kind, key_length=len(key))
    try:
        client.abort_multipart_upload(Bucket=space.bucket, Key=key, UploadId=upload_id)
    except Exception as exc:
        if identity.aws_error_code(exc) in _ABSENT_UPLOAD_CODES:
            raise ApiError("NotFound", "that upload is no longer in progress") from exc
        raise
    return {"key": key}


def part_plan(size: int) -> tuple[int, int]:
    """Computes the part size and count for an object of the given length.

    **Determinate — there is no range and no choice.** An earlier design left the plan free
    between two bounds, which made every boundary assertion unwritable and let two
    implementations produce two part counts for one file.

    **The part size is always the constant, and there is deliberately no size term.** An object
    needing more than ``MULTIPART_MAX_PARTS`` parts at that size would need larger parts — and
    larger parts cannot finish inside their window, which is the one thing the constant exists to
    guarantee. So that region is REFUSED below rather than served with a bigger part, and once it
    is refused a ``max(constant, ceil(size / MULTIPART_MAX_PARTS))`` can only ever return the
    constant. Writing the term anyway would be a branch no input reaches and no test can cover.

    **The arithmetic is integer throughout, and that is not style.** A declared size is a caller's
    number parsed by ``json.loads``, which builds arbitrary-precision integers — so ``size / n``
    on a 400-digit value raises ``OverflowError`` converting to float, and an expected refusal
    becomes a 500 carrying an error stack into a store retained forever. ``-(-a // b)`` is the
    same ceiling with no float in it.

    **The ceiling refusal is a COURTESY on a declared number, not enforcement.** Nothing verifies
    the size — the API keeps no record of an upload, so ``sign_part`` cannot bound a part number
    by the plan's count and ``complete`` cannot check what was actually sent. A client that
    under-declares gets a plan too small for its file and is refused by S3; a client that
    deliberately under-declares can assemble an object above the ceiling. What this refusal buys
    is that an honest over-size upload fails at create rather than after its bytes, and that the
    ceiling is not silently 209 times what the product states.

    Args:
      size: The object's declared byte length.

    Returns:
      ``(part_size, part_count)``.

    Raises:
      ApiError: ``PayloadTooLarge`` when the declared size exceeds the upload ceiling, or when no
        plan can both stay inside S3's part ceiling and finish each part inside its window.
    """
    if size > s3_config.S3_SINGLE_PUT_MAX_BYTES:
        raise ApiError(
            "PayloadTooLarge",
            "file is too large to upload",
            {"limit": s3_config.S3_SINGLE_PUT_MAX_BYTES},
        )

    needed = -(-size // s3_config.MULTIPART_MAX_PARTS)
    if needed > s3_config.MULTIPART_PART_BYTES:
        limit = s3_config.MULTIPART_PART_BYTES * s3_config.MULTIPART_MAX_PARTS
        raise ApiError("PayloadTooLarge", "file is too large to upload", {"limit": limit})

    part_size = s3_config.MULTIPART_PART_BYTES
    return part_size, -(-size // part_size)


def _declared_size(body: dict[str, Any]) -> int:
    """Reads the caller's declared object size.

    Args:
      body: The request body.

    Returns:
      The size in bytes.

    Raises:
      ApiError: ``InvalidRequest`` when it is absent or not a non-negative whole number.
    """
    size = body.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ApiError("InvalidRequest", "size must be a non-negative whole number")
    return size


def _upload_id(body: dict[str, Any]) -> str:
    """Reads the upload id, which is a capability and never an authorization.

    Args:
      body: The request body.

    Returns:
      The upload id.

    Raises:
      ApiError: ``InvalidRequest`` when it is absent or empty.
    """
    upload_id = body.get("uploadId")
    if not isinstance(upload_id, str) or not upload_id:
        raise ApiError("InvalidRequest", "request names no upload")
    return upload_id


def _part_number(body: dict[str, Any]) -> int:
    """Reads and bounds a 1-based part number.

    Args:
      body: The request body.

    Returns:
      The part number.

    Raises:
      ApiError: ``InvalidRequest`` when it is outside S3's range.
    """
    number = body.get("partNumber")
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or not 1 <= number <= s3_config.MULTIPART_MAX_PARTS
    ):
        raise ApiError("InvalidRequest", "part number is outside the permitted range")
    return number


def _parts(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Shapes the caller's part list for S3.

    Args:
      body: The request body.

    Returns:
      The parts, in the shape ``complete_multipart_upload`` takes.

    Raises:
      ApiError: ``InvalidRequest`` when the list is absent, empty or malformed.
    """
    parts = body.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ApiError("InvalidRequest", "request names no parts")
    shaped = []
    for part in parts:
        if not isinstance(part, dict):
            raise ApiError("InvalidRequest", "request names no parts")
        number = part.get("partNumber")
        etag = part.get("etag")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or not isinstance(etag, str)
            or not etag
        ):
            raise ApiError("InvalidRequest", "request names no parts")
        shaped.append({"PartNumber": number, "ETag": etag})
    return shaped


def _refuse_if_occupied(
    client: Any, space: ResolvedSpace, key: str, overwrite: bool
) -> None:
    """Refuses an occupied destination before anything is created.

    Checked BEFORE the upload is created, because a route that creates first has already made
    something that needs aborting.

    Args:
      client: The caller's S3 client.
      space: The resolved space.
      key: The contained key.
      overwrite: Whether an occupied key may be replaced.

    Returns:
      None.

    Raises:
      ApiError: ``Conflict`` when the key is occupied and ``overwrite`` is false.
    """
    if overwrite:
        return
    try:
        client.head_object(Bucket=space.bucket, Key=key)
    except Exception as exc:
        if not _objects.is_missing(exc):
            raise
    else:
        raise ApiError("Conflict", "destination is occupied", {"name": key.rsplit("/", 1)[-1]})


def _created(client: Any, space: ResolvedSpace, key: str, content_type: str) -> str:
    """Creates the multipart upload and returns its id.

    Args:
      client: The caller's S3 client.
      space: The resolved space.
      key: The contained key.
      content_type: The type the assembled object will carry.

    Returns:
      The upload id.

    Raises:
      ApiError: ``InternalError`` when S3 answers without one.
    """
    answer = client.create_multipart_upload(
        Bucket=space.bucket, Key=key, ContentType=content_type
    )
    upload_id = answer.get("UploadId")
    if not isinstance(upload_id, str) or not upload_id:
        raise ApiError("InternalError", "the upload was not created")
    return upload_id
