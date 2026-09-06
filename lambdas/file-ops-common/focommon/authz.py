"""Space authorization for the file-operations control plane.

Two questions, not one, and that is what makes this module different from every other plane's:
**may the verified actor read the SOURCE, and may they write the DESTINATION?** The other planes
ask only the first — a file-send recipient is a lookup rather than an authorization, because the
execution role does the write and the sender's own access question was about the source. Here the
destination is a place the actor chose inside a space they claim, so it is authorized
independently and by the same rules.

Written here rather than borrowed from ``fscommon.authz``: that module carries file-send's wording,
so importing it would merge two planes' domain vocabularies to save a dozen lines. The image now
puts both on ``/opt/python``, so the import would resolve — the separation is a code decision, not
a packaging one, and that is exactly the split the register says not to collapse. What IS shared is the registry read and its predicates, from ``cpcommon.registry``.

**Neither refusal may act as an existence oracle.** A destination the actor cannot reach must read
identically whether the space does not exist or exists and excludes them — otherwise this plane
answers "is there a shared space called X?" for any name a caller cares to try. The two paths
return the same sentence, and a test renders both and compares rather than trusting inspection.

The ``messages`` import is load-bearing rather than tidy: ``TerminalError`` validates its reason at
the RAISE site against the registered table, and importing that module is what registers this
plane's codes. A future module importing only ``authz`` would otherwise get a ``ValueError`` where
it wrote a refusal, which is a worse failure than the one it was reporting.
"""

from cpcommon import config, events
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

    **The kind is type-checked before it is looked up, and that is not caution:** ``in``
    against a frozenset HASHES its left operand, so a request naming a list or a dict raised
    ``TypeError`` out of the membership test itself — reported by ``notifies_on_failure`` as an
    unexpected error, with the named refusal this plane owes never rendered. The API's request
    types declare the kind as a literal and its door refuses such a body today, but this plane
    is the authority on its own requests and does not depend on the door.

    Args:
      username: The trusted username, from the API's identity block and nowhere else.
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
    if not events.in_vocabulary(kind, SPACE_KINDS):
        raise TerminalError("forbidden", f"unknown {side} space kind {kind!r}")
    if not isinstance(name, str) or not name.strip():
        raise TerminalError("forbidden", f"{side} space name missing")
    name = name.strip()

    if kind == "personal":
        if name != username:
            raise TerminalError("forbidden", _UNREACHABLE)
        return {"bucket": config.USER_SPACE_BUCKET, "root": normalize_root(name), **_identity(kind, name)}

    if not reg.is_active_member(reg.load(name), username):
        raise TerminalError("forbidden", _UNREACHABLE)
    return {"bucket": config.SHARED_SPACE_BUCKET, "root": normalize_root(name), **_identity(kind, name)}


def _identity(kind: str, name: str) -> dict:
    """Returns the space's own identity, which the resolved bucket and root do NOT carry.

    **A root is not a name and a bucket is not a kind**, and the difference only surfaces at the
    far end of the plane: the notification producer has to say which space a run touched and link
    into it, and a re-submit built from that notification needs the SOURCE space — which no
    absolute key contains. Recovering either by parsing the root back apart would be a second
    answer to a question this function has already answered.

    They ride from here rather than being re-read off the request, because this is the point at
    which the request's claim has been AUTHORIZED. A later verb reading the untrusted body would be
    naming a space the actor may not have been granted.

    Args:
      kind: The space kind, already checked against the closed set.
      name: The space name, already stripped and authorized.

    Returns:
      The identity fields to merge into the resolved location.

    Raises:
      None.
    """
    return {"kind": kind, "name": name}


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
