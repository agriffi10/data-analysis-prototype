"""The caps this surface enforces, and where each number comes from.

Seven of these are **carried across** and must not be re-derived: three are shipped behaviour the
spec names in as many words, and four are published service limits. **Two are derived** —
``MAX_DOCUMENT_BYTES`` and ``MULTIPART_PART_BYTES`` — and each one's test names the budget it was
derived against, because a hard-coded cap hides a wrong model.

**The multipart block below is one quantity wearing two names, deliberately.** The largest object
that can be trusted to finish inside one presigned window on the slowest supported uplink is
*also* the largest part that can be, so ``MULTIPART_THRESHOLD_BYTES`` is ``MULTIPART_PART_BYTES``
rather than a second tunable that could drift away from it.

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
  MULTIPART_MIN_PART_BYTES: 5 MiB, S3's published minimum for every part but the last. Carried.
  MULTIPART_MAX_PART_BYTES: 5 GiB, S3's published maximum per part. Carried.
  MULTIPART_MAX_PARTS: 10,000, S3's published maximum part count. Carried.
  PART_URL_EXPIRY_SECONDS: 900, matching the two windows already shipped rather than differing
    for no reason. It must stay **strictly less than** ``ASSUME_ROLE_DURATION_SECONDS``: a window
    no session can span forces an ``AssumeRole`` per part, permanently and with no signal. That
    relation is checked over a **hand-written** population, so this constant is only guarded
    because it was added to it.
  MIN_SUPPORTED_UPLINK_BYTES_PER_SEC: 250,000 (2 Mbps) — a **product decision**, stated as one.
    It is the slowest connection this product undertakes to upload large files over, and it is
    the number to change if that undertaking changes; below it uploads still work, they simply
    lose the guarantee. Chosen conservatively, because being wrong in the generous direction
    costs a tail-403 after the bytes were sent, and being wrong in the cautious direction costs
    round trips.
  PART_WINDOW_SAFETY_FACTOR: 2 — a part must complete in **half** its window, so a transient
    stall does not become an expiry.
  MULTIPART_PART_BYTES: Derived, not chosen: what the slowest supported uplink can move inside
    half a part's window, clamped to S3's own part limits. A **constant**, not a function of file
    size — the per-upload plan takes the file size into account separately, and only above a
    terabyte.
  MULTIPART_THRESHOLD_BYTES: The size above which an upload goes multipart. **The same quantity**
    as ``MULTIPART_PART_BYTES``, bound to it rather than restated. Above it a single ``PUT``
    cannot be trusted to finish inside its window; below it multipart buys retry granularity that
    costs more round trips than the restart it saves.
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

MULTIPART_MIN_PART_BYTES: Final[int] = 5 * _MIB
MULTIPART_MAX_PART_BYTES: Final[int] = 5 * _GIB
MULTIPART_MAX_PARTS: Final[int] = 10_000

PART_URL_EXPIRY_SECONDS: Final[int] = 900
MIN_SUPPORTED_UPLINK_BYTES_PER_SEC: Final[int] = 250_000
PART_WINDOW_SAFETY_FACTOR: Final[int] = 2

MULTIPART_PART_BYTES: Final[int] = min(
    max(
        MIN_SUPPORTED_UPLINK_BYTES_PER_SEC * PART_URL_EXPIRY_SECONDS // PART_WINDOW_SAFETY_FACTOR,
        MULTIPART_MIN_PART_BYTES,
    ),
    MULTIPART_MAX_PART_BYTES,
)

MULTIPART_THRESHOLD_BYTES: Final[int] = MULTIPART_PART_BYTES
