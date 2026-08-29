"""Serves the published feature-flag document, which the browser used to read from S3 itself.

**It needs a route of its own for the same reason the username directory did.** The document lives
at ``_config/feature-flags.json`` in the user-space bucket, which belongs to no user and to no
shared space — so the space resolver, whose whole job is to refuse a prefix the caller's claims do
not authorize, correctly refuses it. Routing it through the object surface would mean teaching that
resolver about a prefix nobody owns, and every other object route would inherit the exemption.

**The bytes leave unparsed.** The browser's reader is three-way — a document of an unsupported
version is refused rather than guessed at, and the distinction between "read and unusable" and
"could not read" is what lets the app report that it is running on compiled-in defaults. Parsing
here would collapse both onto a 500 and the fallback would become unreportable.

**An absent document is a 404, not an empty answer**, which is the opposite of the directory's
choice and deliberately so: no directory means no suggestions, which is honest, while no flag
document means the publish workflow has never run against this bucket. That is a deploy defect, and
the browser's own reader already treats it as one.

Attributes:
  FLAGS_KEY: Where ``.github/workflows/deploy-config.yml`` publishes. The portal role holds
    ``GetObject`` here and nothing else, which is what authorizes this route with no IAM change.
  MISSING_CODES: The S3 responses meaning THE OBJECT is not there. Three spellings, because a
    ``GetObject`` for an absent key answers ``NoSuchKey`` while a head-shaped path answers
    ``NotFound`` or a bare ``404``. ``NoSuchBucket`` is deliberately absent: a wrong bucket name is
    a configuration fault wearing the costume of the ordinary pre-publish state.
"""

from typing import Any

from apicommon import identity, s3_config
from apicommon.config import user_space_bucket
from apicommon.context import RequestContext
from apicommon.envelope import ApiError

FLAGS_KEY = "_config/feature-flags.json"
MISSING_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


def feature_flags(context: RequestContext) -> dict[str, Any]:
    """Returns the flag document's bytes, decoded as UTF-8 and not parsed.

    Read through the caller's own assumed session rather than the execution role, so the read is
    authorized by the same grant the browser relied on and this route needs no new one.

    Args:
      context: The authenticated request.

    Returns:
      The decoded body and the object's ETag.

    Raises:
      ApiError: ``NotFound`` when the document has never been published; ``PayloadTooLarge`` above
        the document cap; ``InvalidRequest`` when the stored bytes are not valid UTF-8.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Any other S3 failure — a denial, a throttle, an outage.
    """
    client = identity.user_client("s3", context.acting_as)
    try:
        stored = client.get_object(Bucket=user_space_bucket(), Key=FLAGS_KEY)
    except Exception as exc:
        if identity.aws_error_code(exc) in MISSING_CODES:
            raise ApiError("NotFound", "no feature-flag document has been published") from exc
        raise

    if int(stored.get("ContentLength", 0)) > s3_config.MAX_DOCUMENT_BYTES:
        raise ApiError(
            "PayloadTooLarge",
            "flag document exceeds the readable cap",
            {"limit": s3_config.MAX_DOCUMENT_BYTES},
        )

    try:
        body = stored["Body"].read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError("InvalidRequest", "stored bytes are not valid UTF-8") from exc

    return {"body": body, "etag": str(stored.get("ETag", "")).strip('"')}
