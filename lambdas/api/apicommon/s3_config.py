"""The caps this surface enforces, and where each number comes from.

Four of these are **carried across** and must not be re-derived: three are shipped behaviour the
spec names in as many words, and one is a published service limit. **Exactly one is derived** —
``MAX_DOCUMENT_BYTES`` — and its test names the budget it was derived against, because a
hard-coded cap hides a wrong model.

Attributes:
  MAX_DOCUMENT_BYTES: The largest body the document routes will carry. Sized against Lambda's 6 MB
    synchronous response payload — which binds before API Gateway's 10 MB request side — divided by
    the worst-case JSON escape expansion. **The divisor is not a comfort margin.**
    ``envelope.success`` calls ``json.dumps`` at its default ``ensure_ascii=True``, which renders a
    non-ASCII BMP character as a six-byte ``\\uXXXX`` escape where UTF-8 stored three: a document
    that fits the cap by its stored size can double on the way out. A 4.5 MB CJK document under a
    three-quarters margin produces a response over the ceiling and fails as a fault rather than as
    a refusal. **Without any cap the document route is a second upload path that bypasses
    presigning entirely and works perfectly up to 6 MB**, which is the whole reason small text goes
    through the API and bytes do not.
  S3_SINGLE_PUT_MAX_BYTES: The S3 ``PutObject`` ceiling, which clamps the configured upload cap. A
    published service limit carried across rather than derived — what makes it worth naming is that
    it is exactly the ceiling multipart already had, so the single-``PUT`` design moves it nowhere.
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

_LAMBDA_SYNC_RESPONSE_BYTES: Final[int] = 6 * _MIB
_JSON_ESCAPE_WORST_CASE: Final[int] = 2

MAX_DOCUMENT_BYTES: Final[int] = _LAMBDA_SYNC_RESPONSE_BYTES // _JSON_ESCAPE_WORST_CASE

S3_SINGLE_PUT_MAX_BYTES: Final[int] = 5 * _GIB

DOWNLOAD_URL_EXPIRY_SECONDS: Final[int] = 900
UPLOAD_URL_EXPIRY_SECONDS: Final[int] = 900

FREE_NAME_MAX_ATTEMPTS: Final[int] = 999
