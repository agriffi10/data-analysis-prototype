"""Space authorization for the file-operations control plane.

Two questions, not one, and that is what makes this module different from every other plane's:
**may the verified actor read the SOURCE, and may they write the DESTINATION?** The other planes
ask only the first — a file-send recipient is a lookup rather than an authorization, because the
execution role does the write and the sender's own access question was about the source. Here the
destination is a place the actor chose inside a space they claim, so it is authorized
independently and by the same rules.

Written here rather than borrowed from ``fscommon.authz``: that module carries file-send's wording
and ships in a separately-attached layer, so importing it would merge two domain layers to save a
dozen lines. What IS shared is the registry read and its predicates, from ``cpcommon.registry``.

**Neither refusal may act as an existence oracle.** A destination the actor cannot reach must read
identically whether the space does not exist or exists and excludes them — otherwise this plane
answers "is there a shared space called X?" for any name a caller cares to try. The two paths
return the same sentence, and a test renders both and compares rather than trusting inspection.

The ``messages`` import is load-bearing rather than tidy: ``TerminalError`` validates its reason at
the RAISE site against the registered table, and importing that module is what registers this
plane's codes. A future module importing only ``authz`` would otherwise get a ``ValueError`` where
it wrote a refusal, which is a worse failure than the one it was reporting.
"""

from cpcommon import config
from cpcommon import registry as reg
from cpcommon.errors import TerminalError

from . import messages as _messages  # noqa: F401
from .config import SPACE_KINDS
from .paths import normalize_root

__all__ = ["authorize_destination", "authorize_source"]

_UNREACHABLE = "that space is not available to you"


def _resolve(username: str, space: object, side: str) -> dict:
    """Authorizes one side's space and resolves it to a bucket and root prefix.

    A ``personal`` space authorizes only when its name equals the verified username — never a
    lookup, because the username IS the prefix. A ``shared`` space authorizes on the registry
    saying it is provisioned and lists the actor as an active member, so a space still
    provisioning, deleting or failed fails here, as does one that does not exist and one the actor
    does not belong to.

    **A member whose join chip still reads pending is authorized**, deliberately: the chip is
    display and bookkeeping only, and access is granted at add time. Refusing here would make this
    the only plane where such a member cannot touch files they can already browse and download.

    The unreachable and non-existent cases share one sentence, which is the whole point of routing
    both through this function.

    Args:
      username: The verified username, from the ID token claim and nowhere else.
      space: The request's space for this side, naming a kind and a name.
      side: ``source`` or ``destination``, for the operator detail only.

    Returns:
      The resolved location: the bucket it lives in and its root prefix.

    Raises:
      TerminalError: ``forbidden`` when the space is missing or malformed, names an unknown kind,
        is a personal space that is not the actor's own, or is a shared space the actor cannot
        reach.
    """
    if not isinstance(space, dict):
        raise TerminalError("forbidden", f"missing {side} space")
    kind, name = space.get("kind"), space.get("name")
    if kind not in SPACE_KINDS:
        raise TerminalError("forbidden", f"unknown {side} space kind {kind!r}")
    if not isinstance(name, str) or not name.strip():
        raise TerminalError("forbidden", f"{side} space name missing")
    name = name.strip()

    if kind == "personal":
        if name != username:
            raise TerminalError("forbidden", _UNREACHABLE)
        return {"bucket": config.USER_SPACE_BUCKET, "root": normalize_root(name)}

    if not reg.is_active_member(reg.load(name), username):
        raise TerminalError("forbidden", _UNREACHABLE)
    return {"bucket": config.SHARED_SPACE_BUCKET, "root": normalize_root(name)}


def authorize_source(username: str, space: object) -> dict:
    """Authorizes the actor's access to the space they are operating on.

    Args:
      username: The verified username.
      space: The request's source space.

    Returns:
      The resolved source: bucket and root prefix.

    Raises:
      TerminalError: ``forbidden`` when the actor cannot reach the space.
    """
    return _resolve(username, space, "source")


def authorize_destination(username: str, space: object) -> dict:
    """Authorizes the actor's access to the space they are sending items to.

    Independently and by the same rules as the source, which is what this function exists to make
    true: a request may name two different spaces, and authorizing only the one it reads from would
    let an actor write into a space they may read nothing of.

    Authorizing the SPACE is not the whole question — the prefix within it is constrained by
    containment, and the portal's own folders by the protected-location rules. This answers only
    "may they write anywhere in here at all".

    Args:
      username: The verified username.
      space: The request's destination space.

    Returns:
      The resolved destination: bucket and root prefix.

    Raises:
      TerminalError: ``forbidden`` when the actor cannot reach the space.
    """
    return _resolve(username, space, "destination")
