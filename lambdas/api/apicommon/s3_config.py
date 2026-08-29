"""The caps this surface enforces, and where each number comes from.

Three of these are **shipped behaviour carried across** and must not be re-derived — the spec says
so for two of them in as many words. Two are **computed**, and their tests name the budget they
were computed against, because a hard-coded cap hides a wrong model.

Attributes:
  MAX_DOCUMENT_BYTES: The largest body the document routes will carry. Computed against Lambda's
    6 MB synchronous response payload and API Gateway's 10 MB request payload, whichever binds
    first — the response side does, so it is the one sized against. **Without this cap the
    document route is a second upload path that bypasses presigning entirely and works perfectly
    up to 6 MB**, which is the whole reason small text goes through the API and bytes do not.
  S3_SINGLE_PUT_MAX_BYTES: The S3 ``PutObject`` ceiling, which clamps the configured upload cap.
    Computed rather than written because it is what makes the single-``PUT`` design's ceiling
    equal to the one multipart already had.
  DOWNLOAD_URL_EXPIRY_SECONDS: 900, unchanged from what the browser mints today. **Not
    re-derived** — carried across.
  UPLOAD_URL_EXPIRY_SECONDS: 900, the same window, chosen to match the download side rather than
    left to differ for no reason. The spec names no value; this is the decision, stated.
  FREE_NAME_MAX_ATTEMPTS: 999, the bound ``firstFreeName``'s ``n < 1000`` loop already had.
    **Not re-derived** — carried across, and named so the literal stops being inline.
"""

from typing import Final

_MIB: Final[int] = 1024 * 1024
_GIB: Final[int] = 1024 * _MIB

# Lambda's synchronous response payload ceiling. The document route reads a body INTO a JSON
# envelope, so the response side binds before API Gateway's 10 MB request side; the margin covers
# the envelope's own fields and the base64 growth a non-ASCII body incurs on the way out.
_LAMBDA_SYNC_RESPONSE_BYTES: Final[int] = 6 * _MIB
_ENVELOPE_MARGIN: Final[float] = 0.75

MAX_DOCUMENT_BYTES: Final[int] = int(_LAMBDA_SYNC_RESPONSE_BYTES * _ENVELOPE_MARGIN)

# S3 accepts at most 5 GiB in a single PutObject; above it a caller must use multipart, which this
# surface deliberately does not offer.
S3_SINGLE_PUT_MAX_BYTES: Final[int] = 5 * _GIB

DOWNLOAD_URL_EXPIRY_SECONDS: Final[int] = 900
UPLOAD_URL_EXPIRY_SECONDS: Final[int] = 900

FREE_NAME_MAX_ATTEMPTS: Final[int] = 999
