"""Shaping a minted URL, and clamping it to the session that signed it.

Extracted when the second presigning surface arrived rather than copied into it. A presigned URL
is a bearer token, and a duplicated clamp is two implementations of the one rule that decides how
long a capability lives — the kind of pair that agrees on the day it is written and diverges in
the environment nobody is testing in.

**The clamp is written against the credential, never against the configured duration.** They agree
today and will not later: the successor environment signs from vended credentials with a different
maximum, and a clamp computed from a constant passes every test here and mints dead URLs there.

Attributes:
  None.
"""

import datetime
from typing import Any

from cpcommon import observability


def clamped(requested: int, credentials: Any) -> int:
    """Clamps a requested lifetime to what the signing session has left.

    Args:
      requested: The window this route would like.
      credentials: The credentials that will sign — read for their own expiry, never for the
        configured duration, which is a different number in the successor environment.

    Returns:
      The seconds to sign for, at least one.

    Raises:
      None.
    """
    remaining = credentials.expires_at - datetime.datetime.now(datetime.UTC)
    return max(1, min(requested, int(remaining.total_seconds())))


def minted(url: str, seconds: int, key: str, **fields: Any) -> dict[str, Any]:
    """Shapes a minted URL, and records the mint WITHOUT the URL.

    The span carries the key's length rather than the key, and nothing carries the URL or its
    query string. A signed URL in the log store is a credential in the log store — and so is an
    upload id, which is why ``fields`` is for the space kind and the part number and never for
    anything a caller could redeem.

    Args:
      url: The signed URL.
      seconds: The window it was signed for.
      key: The object key, for its length alone.
      **fields: Extra span fields, each one a value no caller can redeem.

    Returns:
      The wire shape.

    Raises:
      None.
    """
    expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    observability.stamp(presign_expires_in=seconds, key_length=len(key), **fields)
    return {"url": url, "expiresAt": expires_at.isoformat()}
