"""Source authorization for the archive control plane.

The question is narrow and is the only one that matters here: **may the verified actor read —
and delete — what they are archiving?** There is no second party: an archive always lands under
the space it came from, so there is no recipient to resolve and no cross-space question to ask.

**The check must be at least as strict as delete's, because archiving IS a delete.** That is the
one difference in posture from file-send, where a send only ever copies. The registry read and
its predicates live in ``cpcommon.registry``; this module holds archive's question and wording.

The ``messages`` import is load-bearing rather than tidy: ``TerminalError`` validates its reason
at the RAISE site against the registered table, and importing that module is what registers this
plane's codes. Every verb pulls it in transitively through ``arcommon.notify``, so this module
would work without it — but a future module importing only ``authz`` would get a ``ValueError``
where it wrote a refusal, which is a worse failure than the one it was reporting.
"""

from cpcommon import config
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root

from . import messages as _messages  # noqa: F401
from .config import PROTECTED_MARKER_BASENAME, RESERVED_SOURCE_ROOTS, SPACE_KINDS


def authorize_source(username: str, space) -> dict:
    """Authorizes the actor's access to the source space and resolves it to a location.

    A ``personal`` source is authorized only when its name equals the verified username — never
    a lookup, because the username IS the prefix. A ``shared`` source is authorized only when
    the registry says the space is provisioned and lists the actor:
    ``cpcommon.registry.is_active_member`` requires ``status == "active"``, so a space still
    provisioning, deleting or failed fails here, as does one that does not exist and one the
    actor is not a member of.

    **ANY active member may archive, and that is deliberate rather than permissive.** It matches
    the space's existing write model exactly: every member already holds ``DeleteObject`` across
    the whole space prefix, so a member who wanted to destroy the folder can do it today, one
    object at a time, with no receipt. Restricting archiving to an owner would add a rule the
    bucket policy does not have and would not prevent anything.

    **A member whose join chip still reads pending is authorized**, matching file-send and
    The chip is display and bookkeeping only, and access is granted at add time.

    Args:
      username: The trusted username, from the API's identity block and nowhere else.
      space: The request's source space, naming a kind and a name.

    Returns:
      The resolved source location: the bucket it lives in, its root prefix, its kind and its
      name. The kind and name are carried forward because the archive key layout needs both, and
      re-deriving them downstream is how a personal archive comes to be written under
      ``shared/``.

    Raises:
      TerminalError: ``forbidden`` when the space is missing or malformed, names an unknown
        kind, is a personal space that is not the actor's own, or is a shared space the actor is
        not an active member of.
    """
    if not isinstance(space, dict):
        raise TerminalError("forbidden", "missing source space")
    kind, name = space.get("kind"), space.get("name")
    if kind not in SPACE_KINDS:
        raise TerminalError("forbidden", f"unknown source space kind {kind!r}")
    if not isinstance(name, str) or not name.strip():
        raise TerminalError("forbidden", "source space name missing")
    name = name.strip()

    if kind == "personal":
        if name != username:
            raise TerminalError("forbidden", f"{username!r} may not archive from {name!r}")
        bucket = config.USER_SPACE_BUCKET
    else:
        if not reg.is_active_member(reg.load(name), username):
            raise TerminalError("forbidden", f"{username!r} is not a member of {name!r}")
        bucket = config.SHARED_SPACE_BUCKET

    return {"bucket": bucket, "root": normalize_root(name), "kind": kind, "name": name}


def assert_not_reserved(root: str, key: str) -> str:
    """Refuses the space's own portal-managed folders as archive sources.

    Every rule is anchored at the SPACE ROOT — ``{root}{folder}/`` — which leaves
    ``alice/reports/archive/`` an ordinary folder the user made and may archive, the same
    anchoring ``isUndeletableRootFolder`` uses in the browser.

    **THREE WAYS TO SELECT ONE, NOT TWO.** The folder itself and anything beneath it are the
    obvious two. The third is an ANCESTOR: selecting the space root as a folder passes both, and
    the archive expands a folder by listing its prefix — so ``{"kind": "folder", "key": "alice/"}``
    would carry ``alice/user_settings/`` out with everything else *and then delete it*. The
    reserved folders sit directly at the space root, so their only ancestor is the root — but
    the check is written as containment rather than as an equality, because a rule that depends
    on the layout not changing is a rule that fails silently when it does.

    The ancestor test applies to PREFIXES only. A file whose key merely starts the same way —
    ``alice/archived-notes.txt`` against ``alice/archive/`` — is an ordinary file and must still
    archive, which is why the key is compared in its trailing-slash form rather than raw.

    Args:
      root: The authorized, normalised space root prefix.
      key: The selected item's key, already confirmed inside the root.

    Returns:
      The key, unchanged, so this reads as a checkpoint at the call site.

    Raises:
      TerminalError: ``reserved_folder`` when the key is a reserved folder, anything beneath
        one, or a folder that contains one.
    """
    prefix = normalize_root(root)
    as_prefix = key if key.endswith("/") else f"{key}/"
    for folder in RESERVED_SOURCE_ROOTS:
        reserved = f"{prefix}{folder}/"
        if key == reserved.rstrip("/") or key.startswith(reserved) or reserved.startswith(as_prefix):
            raise TerminalError("reserved_folder", f"{key!r} is or contains {folder!r}")
    return key


def assert_not_protected_marker(key: str) -> str:
    """Refuses a selection naming a prefix marker, for the WHOLE request.

    **Both bucket policies deny ``s3:DeleteObject`` on ``*/DO_NOT_DELETE.txt`` and ``*`` matches
    ``/``, so a marker at any depth is already undeletable.** Archiving deletes the source, so
    the run would copy the object into Glacier and then fail on the delete — after some of the
    user's data had already moved. Refusing the whole request up front is the only outcome that
    leaves nothing behind.

    A FILE selection is the only reachable case, and that is the point of checking it here rather
    than only during expansion: a marker inside a selected FOLDER is a different question, and
    the archive answers it by excluding markers from the expansion the way file-send excludes
    ``user_settings/`` — a folder must stay archivable, or a marker at the space root would make
    the whole space un-archivable.

    Args:
      key: The selected item's key.

    Returns:
      The key, unchanged.

    Raises:
      TerminalError: ``protected_marker`` when the key's basename is the marker. It carries the
        BASENAME as a token, not the key: the message names what the user must deselect, and a
        full key in a user-facing sentence is operator text the error-wording rule forbids rendering. The key
        still rides in ``detail``, which reaches the logs and the Step Functions record only.
    """
    basename = key.rstrip("/").rsplit("/", 1)[-1]
    if basename == PROTECTED_MARKER_BASENAME:
        raise TerminalError("protected_marker", f"{key!r}", tokens={"itemName": basename})
    return key
