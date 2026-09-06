"""Destination authorization for the results-conversion plane.

One question: may the verified actor write the DESTINATION space? A personal space authorizes
only when its name equals the verified username — never a lookup, because the username IS the
prefix. A shared space authorizes on the registry saying it is provisioned and lists the actor as
an active member, so a space still provisioning, deleting or failed fails here, as does one that
does not exist and one the actor does not belong to.

**Neither refusal may act as an existence oracle.** A destination the actor cannot reach reads
identically whether the space does not exist or exists and excludes them; both paths return one
sentence, and a test renders both and compares.

Written here rather than borrowed from another plane's ``authz``: those carry their planes'
wording, and importing one would merge two domain vocabularies to save a dozen lines. What IS
shared is the registry read and its predicate, from ``cpcommon.registry`` — including that a
record that cannot be read because of a real ``AccessDenied`` raises rather than reading as
absence.

The ``messages`` import is load-bearing: ``TerminalError`` validates its reason at the raise site
against the registered table, and importing that module is what registers this plane's codes.

Attributes:
  _UNREACHABLE: The one operator detail for both refusals.
"""

from cpcommon import config
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root

from . import messages as _messages  # noqa: F401
from . import reasons
from .config import SPACE_KINDS

__all__ = ["authorize_destination"]

_UNREACHABLE = "that space is not available to you"


def authorize_destination(username: str, space: object) -> dict:
    """Authorizes the actor's access to the space they are saving into, and resolves it.

    Args:
      username: The trusted username, from the API's identity block and nowhere else.
      space: The request's destination space, naming a kind and a name.

    Returns:
      The resolved destination: the bucket it lives in, its root prefix, its kind and its name.

    Raises:
      TerminalError: ``forbidden`` when the space is missing or malformed, names an unknown
        kind, is a personal space that is not the actor's own, or is a shared space the actor
        cannot reach.
    """
    if not isinstance(space, dict):
        raise TerminalError(reasons.FORBIDDEN, "missing destination space")
    kind, name = space.get("kind"), space.get("name")
    # The isinstance is not belt-and-braces: `kind not in SPACE_KINDS` HASHES the value, so a
    # request naming a list or a dict raises TypeError out of the membership test itself — an
    # unpredicted fault where the honest answer is a named refusal.
    if not isinstance(kind, str) or kind not in SPACE_KINDS:
        raise TerminalError(reasons.FORBIDDEN, f"unknown destination space kind {kind!r}")
    if not isinstance(name, str) or not name.strip():
        raise TerminalError(reasons.FORBIDDEN, "destination space name missing")
    name = name.strip()
    if kind == "personal":
        if name != username:
            raise TerminalError(reasons.FORBIDDEN, _UNREACHABLE)
        bucket = config.USER_SPACE_BUCKET
    else:
        if not reg.is_active_member(reg.load(name), username):
            raise TerminalError(reasons.FORBIDDEN, _UNREACHABLE)
        bucket = config.SHARED_SPACE_BUCKET
    return {"bucket": bucket, "root": normalize_root(name), "kind": kind, "name": name}
