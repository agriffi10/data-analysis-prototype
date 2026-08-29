"""Resolving a free `{name} (N)` in one call instead of up to 999.

The browser walked `(1)` … `(999)` with a head per candidate. Behind the API each probe would be a
browser → API → S3 round trip, which is strictly worse than what it replaces — so the walk moves
here and the browser makes exactly one call per gesture.

**Exhaustion and failure become distinguishable, and today they are not.** The browser's
`firstFreeName` returns null both when 999 names are taken and when a probe errors, and the caller
renders one message for both. Here, exhaustion is a Conflict naming how many attempts it made and
anything else is its own failure.

The 999 bound is the shipped behaviour carried across, not re-derived — it is a product decision
about how many numbered copies is too many, and this route is not the place to revisit it.
"""

from typing import Any

from apicommon import protected, s3_config
from apicommon.context import RequestContext
from apicommon.envelope import ApiError

from . import _objects


def free_name(context: RequestContext) -> dict[str, Any]:
    """Returns the first unused `{base} (N)` under a prefix.

    Args:
      context: The authenticated request.

    Returns:
      The free name, without its prefix.

    Raises:
      ApiError: ``AccessDenied`` on an unauthorized space or an escaping prefix; ``Conflict``
        carrying ``attempts`` when every candidate is taken.
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    body = context.body if isinstance(context.body, dict) else {}
    space = _objects.space_from_body(context)
    prefix = protected.contained_prefix(space, str(body.get("prefix", "")))
    base = str(body.get("baseName", ""))
    is_folder = str(body.get("kind", "file")) == "folder"

    client = _objects.client(context)
    for attempt in range(1, s3_config.FREE_NAME_MAX_ATTEMPTS + 1):
        candidate = numbered_name(base, attempt, is_folder)
        key = f"{prefix}{candidate}" + ("/" if is_folder else "")
        try:
            client.head_object(Bucket=space.bucket, Key=key)
        except Exception as exc:
            if _objects.is_missing(exc):
                return {"name": candidate}
            # A denial or a throttle is NOT a free name. Marching past it would propose a name
            # that is taken, and the copy would then overwrite somebody's object.
            raise

    raise ApiError(
        "Conflict",
        "every numbered candidate is taken",
        {"attempts": s3_config.FREE_NAME_MAX_ATTEMPTS},
    )


def numbered_name(base: str, attempt: int, is_folder: bool) -> str:
    """Builds the nth candidate for a base name.

    Lives here alone: the TypeScript copy is deleted, because two implementations of a naming rule
    look identical until one of them changes.

    Args:
      base: The original leaf name.
      attempt: The 1-based attempt number.
      is_folder: Whether the name is a folder, which has no extension to preserve.

    Returns:
      The candidate name.

    Raises:
      None.
    """
    if is_folder or "." not in base:
        return f"{base} ({attempt})"
    stem, _, extension = base.rpartition(".")
    return f"{stem} ({attempt}).{extension}"
