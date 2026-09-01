"""Presigned upload and download URLs.

**A presigned URL is a bearer token.** AWS's own words: they "are bearer tokens that grant access
to those who possess them". So everything true of a credential is true of one — it is minted only
after exactly the authorization the direct call would have had, it is signed with the *caller's*
session and never the API's execution role, and it appears in no emitted record. A debug field
stamping the response body would look like good telemetry.

**The lifetime is clamped to the signing session's, from ONE read of it.** A URL outliving its own
signature returns 403 at redemption, which reads as a permissions bug rather than an expiry — and
on an upload it does so *after* the bytes were sent, at the tail of the longest transfers. The
clamp reads the credentials that actually signed, handed back by the same call that built the
client; asking the identity layer a second time can return a fresher session than the one that
signed, and the URL then advertises an expiry a quarter of an hour past its real one.

The clamp and the mint-shaping themselves live in ``_presign``, shared with the multipart routes:
two copies of the rule deciding how long a capability lives is the pair that agrees on the day it
is written and diverges in the environment nobody tests in.
"""

from typing import Any
from urllib.parse import quote

from apicommon import identity, protected, s3_config
from apicommon.context import RequestContext
from apicommon.envelope import ApiError

from . import _objects, _presign


def upload_url(context: RequestContext) -> dict[str, Any]:
    """Mints a presigned PUT for one object.

    Args:
      context: The authenticated request.

    Returns:
      The URL and when it expires.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space, an escaping key, a marker key or a
        write-locked location; ``Conflict`` when the key is occupied and ``overwrite`` is false — and NO url is
        minted in that case, because a route that mints first has already handed out the
        capability.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))
    overwrite = bool(body.get("overwrite", False))
    # The stricter rule at BOTH settings, where the document route has to admit a create. A user
    # genuinely can pick a file called DO_NOT_DELETE.txt in the dropzone, and before this arc that
    # upload succeeded — the bucket policies deny only the delete. It is refused now, deliberately:
    # the object would sit at a key the listing hides by basename and nobody can ever remove, and
    # the folder it lands in stays open around it. The only marker this app writes is the one the
    # document route creates, with a body it chose.
    protected.assert_replaceable(space, key)

    client, credentials = identity.signing_client(
        "s3", context.acting_as, covering=s3_config.UPLOAD_URL_EXPIRY_SECONDS
    )

    if not overwrite:
        try:
            client.head_object(Bucket=space.bucket, Key=key)
        except Exception as exc:
            if not _objects.is_missing(exc):
                raise
        else:
            raise ApiError(
                "Conflict", "destination is occupied", {"name": key.rsplit("/", 1)[-1]}
            )

    seconds = _presign.clamped(s3_config.UPLOAD_URL_EXPIRY_SECONDS, credentials)
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": space.bucket,
            "Key": key,
            "ContentType": str(body.get("contentType", "application/octet-stream")),
        },
        ExpiresIn=seconds,
    )
    return _presign.minted(url, seconds, key, space_kind=space.kind)


def download_url(context: RequestContext) -> dict[str, Any]:
    """Mints a presigned GET for one object.

    Args:
      context: The authenticated request.

    Returns:
      The URL and when it expires.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping key.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    key = _objects.contained(space, str(body.get("key", "")))

    client, credentials = identity.signing_client(
        "s3", context.acting_as, covering=s3_config.DOWNLOAD_URL_EXPIRY_SECONDS
    )
    seconds = _presign.clamped(s3_config.DOWNLOAD_URL_EXPIRY_SECONDS, credentials)

    params: dict[str, Any] = {"Bucket": space.bucket, "Key": key}
    file_name = body.get("fileName")
    if isinstance(file_name, str) and file_name:
        params["ResponseContentDisposition"] = content_disposition(file_name)

    url = client.generate_presigned_url("get_object", Params=params, ExpiresIn=seconds)
    return _presign.minted(url, seconds, key, space_kind=space.kind)


def content_disposition(file_name: str) -> str:
    """Builds an RFC 6266 attachment header for a filename.

    **Backslashes first, then quotes.** S3 permits `"` in a key, and an unescaped one closes the
    quoted string early and lets the rest of the filename be read as header parameters. Escaping
    quotes before backslashes double-escapes the backslash it just introduced.

    Args:
      file_name: The name to offer the browser.

    Returns:
      The header value.

    Raises:
      None.
    """
    escaped = file_name.replace("\\", "\\\\").replace('"', '\\"')
    return f"attachment; filename=\"{escaped}\"; filename*=UTF-8''{quote(file_name, safe='')}"
