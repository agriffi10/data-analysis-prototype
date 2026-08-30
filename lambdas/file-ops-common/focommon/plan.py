"""The copy plan, passed between states by pointer rather than inline.

inspect-source writes the expanded object list here and threads its key onward; the destination
guard loads it back, and the transfer will. It is not on the state, and the reason is the one this
fleet has learned twice: at ``FILE_OPS_MAX_OBJECTS`` the plan is tens of megabytes against a 256 KB
payload limit, so the list could not ride even once — let alone through a Map's item selector,
which copies the whole state into every item.

It lives in the admin bucket rather than a user's space: the SPA never browses it, so the plan needs
no hidden-folder convention, and a user cannot delete it out from under a running execution — they
do hold delete rights in their own space. Nothing deletes it here either; a lifecycle rule expires
the prefix.

**THE PLAN CARRIES THE THREE FIELDS A LATER VERB WOULD OTHERWISE TAKE OFF THE STATE.** ``requestId``
is what ``assert_describes`` compares, so without it a run can pass its own gate over another
execution's selection. ``submittedAt`` and ``onConflict`` are the two the overwrite predicate turns
on, and reading them from the state rather than the plan is exactly the substitution the
supersession check exists to catch: the plan is the object that knows which request its destination
keys were derived for.

**The write is UNCONDITIONAL, and that is the difference from the lock.** The lock's ``PutObject``
is a compare-and-set and belongs to ``cpcommon.lock``; this one is a plain write of this plane's own
artifact at a key that is a pure function of the request id, so a ``Retry`` of the verb rewrites the
same object with the same content rather than leaving a second plan behind.

``messages`` is imported for its side effect as well as tidiness: it registers this domain's reason
codes, and a terminal error validates its reason at construction. Without the import, a process
importing only this module raises a validation error where it meant to write a refusal.

**THIS MODULE OWNS EVERY ADMIN-BUCKET KEY LAYOUT ON THIS PLANE** — the plan, the transfer
manifest, the Map Run's result export and the transfer-results document — for one reason: one
module, one place a key can be wrong. Where they live is this plane's business; a manifest's BYTES
and an export's reader belong to ``cpcommon.transfer``, which is shared with three other planes.

**Two of the four are pure functions of the request id and two are keyed by the EXECUTION as well.**
The plan and the results prefix are execution-stable, so a ``Retry`` rewrites the same object rather
than leaving a second one behind. The manifest and the transfer-results document are
execution-unique, because two overlapping executions of one request must not clobber each other's
dataset while a Map is reading it.

Attributes:
  BASENAME: The plan object's basename, under ``{PLAN_PREFIX}/{requestId}/``.
  MANIFEST_BASENAME: The transfer manifest's basename, under the EXECUTION's folder.
  RESULTS_BASENAME: The transfer-results document's basename, under the EXECUTION's folder. It
    holds what the collector decided and what the deletion did — the deletable item keys, the
    per-item object counts and the per-item deletion records.

    **It exists because those three terms cannot ride on the state.** Measured at the selection
    cap they are ~156 KB on top of a state already holding the selection and one outcome record
    per item, which is over Step Functions' 256 KB limit — and the overflow would land on the
    collector's result AFTER the copy, or on delete-source's AFTER the deletion, where
    ``States.DataLimitExceeded`` escapes every ``Catch`` and the user is told nothing at all. Only
    the COUNT rides.
  RESULTS_FOLDER: The folder the Distributed Map's ``ResultWriter`` exports into. Step Functions
    appends its own Map Run component below it, so this is a prefix rather than a key.
"""

import json

from cpcommon import clients, errors, events
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root

from . import messages  # noqa: F401
from .config import PLAN_PREFIX

BASENAME = "plan.json"
MANIFEST_BASENAME = "transfer-manifest.jsonl"
RESULTS_BASENAME = "transfer-results.json"
RESULTS_FOLDER = "results"

__all__ = [
    "BASENAME",
    "MANIFEST_BASENAME",
    "RESULTS_BASENAME",
    "RESULTS_FOLDER",
    "assert_describes",
    "assert_request_id_unused",
    "load",
    "load_results",
    "plan_key",
    "transfer_manifest_key",
    "transfer_results_key",
    "transfer_results_prefix",
    "write",
    "write_results",
]


def _request_folder(request: dict) -> str:
    """Derives the folder every artifact of one request shares, from the request id.

    Args:
      request: The validated request.

    Returns:
      The folder under the admin bucket, ending in a slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id. Falling back to a
        shared or random key would give up the property the id buys — a Retry writing the same
        object rather than a second one — so it refuses instead. validate-authorize type-checks the
        id long before this can be reached; the guard is here because the value becomes a KEY, and
        a key built from ``None`` is a real object in a real bucket.
    """
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, "a plan key needs the request id")
    return f"{PLAN_PREFIX}/{request_id.strip()}/"


def plan_key(request: dict) -> str:
    """Derives the plan's S3 key from the request id.

    Args:
      request: The validated request.

    Returns:
      The plan key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request)}{BASENAME}"


def _absent(key: str) -> bool:
    """Whether the plan key really is unoccupied, asked with a LIST rather than a read.

    **This exists because a denial and an absence are the same answer on a `GetObject`.** S3
    reports a missing object as ``NoSuchKey`` only to a caller that can list the bucket; to one
    that cannot, it is ``AccessDenied``. This role's list grant is conditioned on the plan prefix,
    and a ``GetObject`` carries no prefix for that condition to match, so the read is denied for
    every absent plan — which is every first submission.

    A list DOES carry the prefix, so it is answerable where the read is not, and it answers the
    question the caller actually has. The denial is never itself read as absence: only a list that
    comes back without the key is, so a genuine denial on an object that exists still raises and
    cannot plan over a run already copying.

    **One page is enough, and the reason is byte order rather than luck.** A key always sorts
    before any key that extends it, so if the exact key exists it is the first S3 returns under
    its own prefix and ``MaxKeys=1`` cannot miss it. Were that ever untrue — a sibling sorting
    first — the exact match would fail against a truncated page and this would answer "absent",
    which is the one way the probe could fail open. Widen the page before adding a sibling under a
    plan's own key.

    Args:
      key: The plan key.

    Returns:
      True when no object is at that key.

    Raises:
      TransientError: On a retryable S3 fault.
      TerminalError: ``plan_unreadable`` when the list itself is refused — the caller cannot tell
        absence from denial, so it must not guess.
    """
    try:
        listing = clients.s3().list_objects_v2(
            Bucket=cpconfig.ADMIN_BUCKET, Prefix=key, MaxKeys=1
        )
    except Exception as err:
        errors.raise_if_transient(err, f"list {cpconfig.ADMIN_BUCKET}/{key}")
        raise TerminalError(
            "plan_unreadable", f"could not check whether plan {key} exists: {err}"
        ) from err
    return not any(item.get("Key") == key for item in listing.get("Contents", []))


def _read(key: str) -> dict | None:
    """Reads a plan object back, or reports that there is none.

    Args:
      key: The plan key.

    Returns:
      The parsed plan, or None when no object is there.

    Raises:
      TransientError: On a retryable S3 fault.
      TerminalError: ``plan_unreadable`` when an object is there but is not a JSON object, and
        when a denied read cannot be shown to be an absence.
    """
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        if errors.error_code(err) in ("NoSuchKey", "404"):
            return None
        if errors.error_code(err) in ("AccessDenied", "403") and _absent(key):
            return None
        raise TerminalError("plan_unreadable", f"could not read plan {key}: {err}") from err

    try:
        plan = json.loads(body)
    except ValueError as err:
        raise TerminalError("plan_unreadable", f"plan {key} is not valid JSON: {err}") from err
    if not isinstance(plan, dict):
        raise TerminalError("plan_unreadable", f"plan {key} is not an object")
    return plan


def assert_request_id_unused(request: dict, execution_arn: object) -> None:
    """Refuses a request whose id has already been planned by a DIFFERENT execution.

    The request id is browser-supplied and it is the whole identity of a plan: the key is a pure
    function of it, and the guard, the transfer and the deletion all read whatever is at that key.
    The queue's FIFO ``MessageDeduplicationId`` is that id, but its window is five minutes against
    a three-hour ceiling and this plane accepts a hand-crafted envelope — so a second request
    carrying a used id is reachable, and without this check it would plan over the first run's
    object list while that run was still copying from it.

    **It compares the EXECUTION, not the presence of an object, and the difference is the whole
    correctness of the check.** Every task on this machine carries a three-attempt ``Retry``, so a
    transient fault after the write is an ordinary event: a guard that refused any occupied prefix
    would refuse the request it had itself just planned, on its own retry, and tell the user their
    id had been used before. Comparing the execution ARN refuses the case the check exists for and
    admits the one the machine creates.

    It narrows rather than closes, exactly as every other conflict guard on this fleet does: two
    concurrent executions can both find the key empty. What it removes is the ordinary case — an id
    reused minutes or days later.

    Args:
      request: The validated request, which determines the key.
      execution_arn: This execution's ARN, stamped onto the state by the machine.

    Returns:
      None.

    Raises:
      TerminalError: ``request_id_reused`` when a plan for this id names another execution,
        ``plan_unreadable`` when something unparseable is at the key, or ``malformed_event`` from
        the key derivation.
      TransientError: On a retryable S3 fault.
    """
    existing = _read(plan_key(request))
    if existing is None:
        return
    if existing.get("executionArn") != execution_arn:
        raise TerminalError(
            "request_id_reused",
            f"a plan for {request.get('requestId')!r} was written by "
            f"{existing.get('executionArn')!r}, not this run",
        )


def write(
    request: dict,
    source: dict,
    destination: dict | None,
    actor: object,
    execution_arn: object,
    items: list,
) -> str:
    """Writes the copy plan to the admin bucket and returns its key.

    Args:
      request: The validated request, which determines the key and the three fields a later verb
        must not take off the state instead.
      source: The authorized source, carrying the bucket and root.
      destination: The authorized destination, or None for a delete.
      actor: The verified actor, recorded so an operator reading a failed run does not have to join
        the plan back against the execution.
      execution_arn: This execution's ARN, which is what makes the reuse guard above retry-safe.
      items: The expanded items, each carrying its identity, label and object list.

    Returns:
      The key the plan was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb — safe,
        because the key is a pure function of the request id and the verb is read-only besides
        this write.
      TerminalError: ``malformed_event`` from the key derivation.
      ClientError: Any deterministic fault propagates.
    """
    key = plan_key(request)
    objects = sum(item["objectCount"] for item in items)
    body = json.dumps(
        {
            "requestId": request.get("requestId"),
            "operation": request.get("operation"),
            "submittedAt": request.get("submittedAt"),
            "onConflict": request.get("onConflict"),
            "actor": actor,
            "executionArn": execution_arn,
            "source": {"bucket": source["bucket"], "root": normalize_root(source["root"])},
            "destination": (
                {"bucket": destination["bucket"], "prefix": destination["prefix"]}
                if destination
                else None
            ),
            "items": items,
            "itemCount": len(items),
            "objectCount": objects,
            "totalBytes": sum(item["totalBytes"] for item in items),
        },
        separators=(",", ":"),
    ).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise
    return key


def assert_describes(loaded: dict, request: dict, key: str) -> dict:
    """Confirms a plan read back from S3 is the plan THIS execution wrote.

    The key is a pure function of the request id, which is what makes a ``Retry`` rewrite the same
    object rather than leave a second one behind — and which also means a second execution carrying
    the same id overwrites it. Every verb after the expansion takes its destination keys, its
    conflict answer and eventually its DELETION LIST from whatever it reads back, so without this
    check a run could pass its own gate on its own counts and then act on a different selection
    entirely, in either space bucket.

    Cheap and total: five fields the state already holds, compared against what the object claims.
    The object count is included because it is the term every later gate reasons about.

    Args:
      loaded: The parsed plan.
      request: The running request.
      key: The plan's key, for the refusal's detail.

    Returns:
      The plan, unchanged, so this reads as a checkpoint at the call site.

    Raises:
      TerminalError: ``plan_superseded`` when the plan describes a different request, execution,
        source or object count.
    """
    source = request.get("source") or {}
    loaded_source = loaded.get("source") or {}
    root = source.get("root")
    expectations = (
        ("request id", loaded.get("requestId"), request.get("requestId")),
        ("execution", loaded.get("executionArn"), (request.get("execution") or {}).get("arn")),
        ("source bucket", loaded_source.get("bucket"), source.get("bucket")),
        (
            "source root",
            loaded_source.get("root"),
            normalize_root(root) if root else None,
        ),
        ("object count", loaded.get("objectCount"), request.get("objectCount")),
    )
    for what, found, expected in expectations:
        if expected is not None and found != expected:
            raise TerminalError(
                "plan_superseded", f"plan {key} names a {what} of {found!r}, not {expected!r}"
            )
    return loaded


def load(key: str, request: dict) -> dict:
    """Reads a plan back and refuses every shape a later verb could act on wrongly.

    Every unreadable shape is a WHOLE-REQUEST terminal, never a partial plan handed onward. A plan
    short of its objects would have the guard clear destinations nobody checked and the transfer
    copy a subset, and the user would be told the operation went well while holding some of what
    they asked for.

    **The count check is what makes that true rather than aspirational**, and it is what an
    emptiness check could not do. A plan may legitimately hold no objects at all — every selected
    item can resolve to nothing, which is a per-item outcome on this plane rather than a
    whole-request refusal — so "carries something" says nothing. What is checked instead is that
    the plan holds exactly the items and objects it RECORDS holding, which is the shape a truncated
    read produces: a short copy that succeeds, over a user told everything went well.

    Args:
      key: The plan key, as inspect-source threaded it onward.
      request: The running request, which the plan must describe.

    Returns:
      The parsed plan.

    Raises:
      TerminalError: ``plan_unreadable`` when the plan is absent, unparseable, carries no item
        list, holds an item with no key or no object list, or is short of either count it records;
        ``plan_superseded`` when it is not this run's.
      TransientError: On a retryable S3 fault.
    """
    plan = _read(key)
    if plan is None:
        raise TerminalError("plan_unreadable", f"plan {key} is not there")

    items = plan.get("items")
    if not isinstance(items, list):
        raise TerminalError("plan_unreadable", f"plan {key} carries no item list")
    counted = 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("objects"), list):
            raise TerminalError("plan_unreadable", f"plan {key} holds an item with no objects")
        if not isinstance(item.get("itemKey"), str) or not item["itemKey"]:
            raise TerminalError("plan_unreadable", f"plan {key} holds an item with no key")
        counted += len(item["objects"])
    for what, held, recorded in (
        ("objects", counted, plan.get("objectCount")),
        ("items", len(items), plan.get("itemCount")),
    ):
        if not isinstance(recorded, int) or isinstance(recorded, bool) or held != recorded:
            raise TerminalError(
                "plan_unreadable", f"plan {key} holds {held} {what} but records {recorded!r}"
            )
    return assert_describes(plan, request, key)


def _execution_folder(request: dict, execution_name, what: str) -> str:
    """Derives the EXECUTION-unique folder a per-run artifact sits in.

    Args:
      request: The validated request.
      execution_name: The execution's name, stamped onto the state by a ``Pass`` — never read from
        ``$$`` inside the task's own ``Parameters``, which wraps the payload and would put the
        request one level below where every notify path reads it.
      what: The artifact being keyed, for the refusal's detail.

    Returns:
      The folder under the admin bucket, ending in a slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id, or when the
        execution name is missing. It refuses rather than falling back to the bare request id: the
        fallback is exactly the collision the execution segment exists to prevent, and it would
        appear only under concurrency.
    """
    folder = _request_folder(request)
    if not isinstance(execution_name, str) or not execution_name.strip():
        raise TerminalError(events.MALFORMED, f"a {what} key needs the execution name")
    return f"{folder}{execution_name.strip()}/"


def transfer_manifest_key(request: dict, execution_name) -> str:
    """Derives the transfer manifest's key, which is EXECUTION-unique where the plan is not.

    Args:
      request: The validated request.
      execution_name: The execution's name.

    Returns:
      The manifest key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id or execution name.
    """
    return f"{_execution_folder(request, execution_name, 'transfer manifest')}{MANIFEST_BASENAME}"


def transfer_results_key(request: dict, execution_name) -> str:
    """Derives the transfer-results document's key, EXECUTION-unique for the manifest's reason.

    Args:
      request: The validated request.
      execution_name: The execution's name.

    Returns:
      The document's key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id or execution name.
    """
    return f"{_execution_folder(request, execution_name, 'transfer results')}{RESULTS_BASENAME}"


def transfer_results_prefix(request: dict) -> str:
    """Derives the prefix the Map Run's ``ResultWriter`` exports into.

    Request-stable rather than execution-unique, because Step Functions appends its own Map Run
    component below whatever prefix it is given — so two runs of one request cannot collide here
    even though they share this prefix.

    Args:
      request: The validated request.

    Returns:
      The results prefix under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request)}{RESULTS_FOLDER}"


def write_results(key: str, results: dict) -> None:
    """Writes the transfer-results document, which is what keeps three unbounded terms off the state.

    Args:
      key: The document's key, from ``transfer_results_key``.
      results: The document — the deletable item keys, the per-item object counts and, once the
        deletion has run, its per-item records.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb — safe,
        because the key is a pure function of the request and the execution.
      ClientError: Any deterministic fault propagates.
    """
    body = json.dumps(results, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise


def load_results(key: str) -> dict:
    """Reads the transfer-results document back.

    **An absent or unreadable document is a WHOLE-REQUEST terminal, never an empty one.** The
    deletion reads its permission to delete from this object: an empty read would present as "no
    item may be deleted", which on a ``move`` silently leaves every source in place after a
    successful copy and reports it as done.

    Args:
      key: The document's key.

    Returns:
      The parsed document.

    Raises:
      TerminalError: ``plan_unreadable`` when the document is absent, unparseable, or carries no
        deletable list.
      TransientError: On a retryable S3 fault.
    """
    results = _read(key)
    if results is None:
        raise TerminalError("plan_unreadable", f"transfer results {key} are not there")
    if not isinstance(results.get("deletable"), list):
        raise TerminalError("plan_unreadable", f"transfer results {key} carry no deletable list")
    return results
