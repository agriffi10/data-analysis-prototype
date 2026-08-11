"""Source authorization for the file-send control plane.

The question this module answers is narrow and is the only one that matters at this stage:
**may the verified sender READ what they are sending?** The recipient's side is not an
authorization question at all — a space is any space by name and a user is any user, because
the execution role does the write, matching table-share's recorded decision.

The registry read and its predicates live in ``cpcommon.registry``; this module holds the
file-send question and its wording.

The ``messages`` import is load-bearing rather than tidy: ``TerminalError`` validates its reason
at the RAISE site against the registered table, and importing that module is what registers
this plane's codes. Every verb pulls it in transitively through ``fscommon.notify``, so this
module worked without it — but a future module importing only ``authz`` would get a
``ValueError`` where it wrote a refusal, which is a worse failure than the one it was reporting.
"""

from cpcommon import config
from cpcommon import registry as reg
from cpcommon.errors import TerminalError

from . import messages as _messages  # noqa: F401
from .config import ATHENA_RESULTS_FOLDER, SPACE_KINDS
from .paths import normalize_root


def authorize_source(username: str, space) -> dict:
    """Authorizes the sender's read access to the source space and resolves it to a location.

    A ``personal`` source is authorized only when its name equals the verified username —
    never a lookup, because the username IS the prefix. A ``shared`` source is authorized only
    when the registry says the space is provisioned and lists the sender: ``cpcommon.registry
    .is_active_member`` requires ``status == "active"``, so a space still provisioning,
    deleting or failed fails here, as does one that does not exist and one the sender is not a
    member of.

    **A member whose join chip still reads pending is authorized**, and that is deliberate:
    SPEC-073 settled that the chip is display and bookkeeping only and that access is granted
    at add time. Denying a send here would make this the only plane where such a member is
    refused — for files they can already browse, download and share as a table.

    Args:
      username: The verified username, from the ID token claim and nowhere else.
      space: The request's source space, naming a kind and a name.

    Returns:
      The resolved source location: the bucket it lives in and its root prefix.

    Raises:
      TerminalError: ``forbidden`` when the space is missing or malformed, names an unknown
        kind, is a personal space that is not the sender's own, or is a shared space the
        sender is not an active member of.
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
            raise TerminalError("forbidden", f"{username!r} may not send from {name!r}")
        return {"bucket": config.USER_SPACE_BUCKET, "root": normalize_root(name)}

    if not reg.is_active_member(reg.load(name), username):
        raise TerminalError("forbidden", f"{username!r} is not a member of {name!r}")
    return {"bucket": config.SHARED_SPACE_BUCKET, "root": normalize_root(name)}


def assert_not_results_folder(root: str, key: str) -> str:
    """Refuses the space's own Athena results folder as a send source.

    The refusal is anchored at the SPACE ROOT — ``{root}athenaresults/`` — which leaves
    ``alice/reports/athenaresults/`` an ordinary folder the user made and may send, the same
    anchoring ``isUndeletableRootFolder`` uses in the browser.

    **This rule is written here rather than reused from anywhere**, and the reason is worth
    stating because reuse would look like the tidier choice: ``protectedFolders.ts`` keeps
    three divergent lists answering three different questions — may a data-quality check read
    it, does the user see it, may the user paste into it — and in none of them is copying
    *out* of ``athenaresults/`` refused. A send is a copy, so no existing list answers this,
    and that file's own note says unioning them is the wrong repair.

    **THREE WAYS TO SELECT IT, NOT TWO.** The folder itself and anything beneath it are the
    obvious two. The third is an ANCESTOR: selecting the space root as a folder refuses
    nothing under the first two rules, and SPEC-165 expands a folder by listing its prefix —
    so ``{"kind": "folder", "key": "sales/"}`` would carry ``sales/athenaresults/`` out with
    everything else. In a shared space that is other members' query results leaving the space
    to a recipient who is not in it, which is the whole exposure this rule exists to close.
    The results folder sits directly at the space root, so its only ancestor is the root — but
    the check is written as containment rather than as an equality, because a rule that
    depends on the layout not changing is a rule that fails silently when it does.

    The ancestor test applies to PREFIXES only. A file whose key merely starts the same way —
    ``alice/a`` against ``alice/athenaresults/`` — is an ordinary file and must still send,
    which is why the key is compared in its trailing-slash form rather than raw.

    Args:
      root: The authorized, normalised space root prefix.
      key: The selected item's key, already confirmed inside the root.

    Returns:
      The key, unchanged.

    Raises:
      TerminalError: ``results_not_sendable`` when the key is the results folder, anything
        beneath it, or a folder that contains it.
    """
    results = f"{normalize_root(root)}{ATHENA_RESULTS_FOLDER}/"
    if key == results.rstrip("/") or key.startswith(results):
        raise TerminalError("results_not_sendable", f"{key!r}")
    as_prefix = key if key.endswith("/") else f"{key}/"
    if results.startswith(as_prefix):
        raise TerminalError("results_not_sendable", f"{key!r} contains the results folder")
    return key
