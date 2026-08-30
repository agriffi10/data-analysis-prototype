"""Serves the published username directory, which the browser used to read from S3 itself.

**An unavailable directory is an empty directory, never an error.** A missing object, a body that
is not JSON, a document version this build does not understand and a ``usernames`` field that is
not an array all answer 200 with an empty list. That inverts the usual mapping of an S3 404 onto a
404, deliberately: the only honest thing to do with an unavailable suggestion list is offer no
suggestions, and an error banner would announce the failure of a feature whose whole promise is
that it stays out of the way. Every consumer accepts a name that is not in the list anyway.

**Every entry is re-checked here even though the builder already guarantees it.** A producer
guarantee is not a runtime guarantee: the object is one ``aws s3 cp`` away from holding anything at
all, and the browser renders these into the DOM and builds keys from them. The browser re-checks
too, and that is not redundancy — this route is now a second producer, and a second producer is a
second thing that can be wrong.

**Nothing is truncated.** The index cap is the browser's, and its warning is the only signal that
the directory has outgrown it; truncating server-side would silence that while looking like a
kindness. The size is bounded rather than hoped at: the cap's worth of maximum-length catalog names,
JSON-encoded, is around 1.3 MB — comfortably inside the synchronous response payload limit, with
more than four times the headroom.

Attributes:
  DIRECTORY_KEY: Where the daily builder publishes. The portal role holds ``GetObject`` here,
    which is what authorizes the read, and ``ListBucket`` on this prefix, which is what makes
    ``MISSING_CODES`` reachable — S3 reports a missing object as absent only to a caller that can
    list, so without the second grant an unpublished directory answers ``AccessDenied`` and this
    route raises instead of degrading to empty.
  SUPPORTED_VERSION: The only document shape this reader understands. A different one is refused,
    not guessed at.
  MISSING_CODES: The S3 responses meaning THE OBJECT is not there — the same set the browser's
    reader used. Three spellings, because a ``GetObject`` for an absent key answers ``NoSuchKey``
    while a head-shaped path answers ``NotFound`` or a bare ``404``. **``NoSuchBucket`` is
    deliberately absent**: a wrong or unset bucket name is a configuration fault, and folding it in
    here would answer 200 with an empty list — a misconfiguration wearing the costume of the
    ordinary pre-builder state, which is the one thing the live check cannot tell apart.
"""

import json
from typing import Any

from apicommon import identity
from apicommon.config import user_space_bucket
from apicommon.context import RequestContext
from cpcommon import observability
from cpcommon.config import CATALOG_IDENTIFIER_RE

DIRECTORY_KEY = "_directory/usernames.json"
SUPPORTED_VERSION = 1
MISSING_CODES = frozenset({"NoSuchKey", "NotFound", "404"})

_EMPTY: dict[str, Any] = {"usernames": [], "generatedAt": None}


def user_directory(context: RequestContext) -> dict[str, Any]:
    """Returns the usernames the directory publishes.

    Reads through the caller's own assumed session rather than the execution role, so the read is
    authorized by the same grants the browser used to rely on, plus the prefix listing that lets
    an unpublished document be reported absent rather than denied.

    Args:
      context: The authenticated request.

    Returns:
      The usernames and when they were published, or the empty state when the document is
      unavailable or unusable.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Any S3 failure that is not the object being absent — a denial, a throttle, an
        outage. Those are real faults and are classified above; swallowing them here would report
        an empty directory for a bucket nobody could read.
    """
    client = identity.user_client("s3", context.acting_as)
    try:
        body = client.get_object(Bucket=user_space_bucket(), Key=DIRECTORY_KEY)["Body"].read()
    except Exception as exc:
        if identity.aws_error_code(exc) in MISSING_CODES:
            return dict(_EMPTY)
        raise

    directory = _parse(body)
    observability.stamp(username_count=len(directory["usernames"]))
    return directory


def _parse(body: bytes | str | None) -> dict[str, Any]:
    """Turns the stored document into the wire shape, degrading to empty rather than raising.

    Total by construction: a body that is not JSON is as empty as one that is JSON of the wrong
    shape, so there is no arm where a malformed document reaches a caller as a fault.

    Args:
      body: The object's bytes, or None.

    Returns:
      The wire shape.

    Raises:
      None.
    """
    if not body:
        return dict(_EMPTY)
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return dict(_EMPTY)
    return _from_document(parsed)


def _from_document(parsed: object) -> dict[str, Any]:
    """Validates a parsed document into the wire shape.

    Args:
      parsed: Whatever the object deserialized to.

    Returns:
      The wire shape, empty when the document is not one this reader understands.

    Raises:
      None.
    """
    if not isinstance(parsed, dict):
        return dict(_EMPTY)

    version = parsed.get("version")
    if version != SUPPORTED_VERSION:
        observability.warning(
            "ignoring a directory document of an unsupported version",
            found_version=str(version),
            supported_version=SUPPORTED_VERSION,
        )
        return dict(_EMPTY)

    usernames = parsed.get("usernames")
    if not isinstance(usernames, list):
        return dict(_EMPTY)

    valid = [
        name
        for name in usernames
        if isinstance(name, str) and CATALOG_IDENTIFIER_RE.match(name)
    ]
    if not valid:
        return dict(_EMPTY)

    generated_at = parsed.get("generatedAt")
    return {
        "usernames": valid,
        "generatedAt": generated_at if isinstance(generated_at, str) else None,
    }
