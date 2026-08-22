"""Batched object deletion for the one plane that removes a user's own files.

``delete-source`` is the only verb in this portal that deletes data a user put there deliberately,
and it runs in buckets with versioning OFF. Everything here is shaped by that: the refusals happen
before the first batch is issued, the ETag comparison is the caller's own plan rather than anything
read from the state, and a partial failure is counted and reported rather than inferred from a
status code.

**``DeleteObjects`` answers HTTP 200 with a per-item ``Errors`` array.** A key that was denied or
lost a precondition does not raise, so a response inspected only by status code reads as a complete
deletion — the defect this repo has already shipped once, on a teardown that freed a space name
whose objects were still in the bucket. ``Quiet: False`` is set explicitly so the array is
populated at all.

**BOTH DELETE PATHS ARE BUILT, AND THE SAFE ONE IS ACTIVE.** A conditional delete carries the
plan's ETag so an object modified between the copy and the deletion is not removed. Whether S3
*enforces* that condition on these buckets is a question no offline check can answer:
``supports_conditional_delete`` reads the shape off the live service model, which proves botocore
will SERIALIZE the field and not that the service honours it — and a serialized-but-ignored
condition deletes a changed source silently, which is the single worst outcome this module has. So
the HEAD-compare path is the one that runs, and the conditional path is gated on
``CONDITIONAL_DELETE_ENABLED`` as well as on the model, to be turned on once a live probe has shown
a wrong-ETag delete is actually refused here.

**A CONDITIONAL DELETE IS NOT REPLAY-SAFE THE WAY AN UNCONDITIONAL ONE IS**, and that difference is
what ``_ALREADY_GONE`` exists for. The unconditional case rests on S3 reporting an absent key as
deleted, which is what makes this verb's ``Retry`` correct. With a condition attached, a key the
previous attempt already removed comes back on the ERROR side — so a verb that deleted five batches
of twenty, hit a throttle and retried would report every one of those five as a failure, and the
user would be told a completed move half-failed. "Gone" is therefore success and only a genuine
mismatch is ``source_changed``.

**ONE THING TO SETTLE BEFORE THE CONDITIONAL PATH IS SWITCHED ON.** A 409 raises ``TransientError``,
which is right for the object — the write is retryable — but it escalates to the whole REQUEST: after
the state's retries, ``DeleteSource``'s ``Catch`` reaches the failure path and the finaliser never
runs, so a ``move`` in which most items deleted cleanly reports a whole-request failure with no
per-item terminals. That is against this plane's rule that a whole-request terminal comes only from a
property of the request. It is unreachable today — ``ConditionalRequestConflict`` is a
conditional-request code and ``CONDITIONAL_DELETE_ENABLED`` is ``False`` — and it must be resolved,
by collecting the conflict as a per-item retryable outcome rather than raising, before that flag
flips.

**Counts and reasons, never keys.** What this returns reaches a user-facing message and the Step
Functions record; a failure naming file paths is a disclosure this plane has no reason to make.

Attributes:
  MAX_KEYS_PER_BATCH: S3's own limit on one ``DeleteObjects`` request.
  HEAD_CONCURRENCY: Worker pool for the HEAD-compare sweep, bounded by botocore's default
    connection pool exactly as the destination guard's is.
  CONDITIONAL_DELETE_ENABLED: Whether the conditional path may be used at all. False until a live
    probe demonstrates the condition is enforced on these buckets; see the module docstring.
  SOURCE_CHANGED: Reason for an object that no longer matches the ETag the plan recorded. Its
    destination copy holds bytes that are no longer the source's.
  SOURCE_DELETE_FAILED: Reason for an object that could not be removed for any other reason.
  DELETE_REFUSED: Reason for an item refused before any delete was issued, because one of its keys
    is somewhere this plane may not delete.
  _PRECONDITION_CODES: What S3 answers when the ETag does not match. 412 on the single-object path;
    on the batch path the ``Code`` string is UNDOCUMENTED and an owed live probe settles it.
    **Deliberately NOT generous**: a generic code such as ``InvalidRequest`` mapped here would tell
    the user their file "was changed while this was running" for a fault that has nothing to do with
    the ETag. Anything unrecognised falls to ``SOURCE_DELETE_FAILED``, which fails the object just
    as firmly and claims only what is known.
  _CONFLICT_CODES: A concurrent delete or put that beat this one. AWS documents it as a 409 and it
    is NOT a precondition mismatch — it is retryable, where a mismatch is terminal for that object.
  _ALREADY_GONE: The object is not there. On the unconditional path S3 never says this; on the
    conditional path it is what a replayed batch answers, and it means the deletion succeeded.
  _DENIED_CODES: The bucket policy or the role's own Deny refused it.
  _UNDELETABLE_FOLDERS: Folder names this plane may not delete AT ANY DEPTH, because the execution
    role Denies ``s3:DeleteObject`` beneath them with a wildcard that matches ``/``.

    **This list mirrors the IAM POLICY, deliberately NOT the browser's own rule.** The browser
    refuses ``athenaresults/`` root-anchored in a personal space and at any depth in a shared one,
    which is the asymmetry the two bucket policies have. This role carries no principal tag, so
    ``{bucket}/*/athenaresults/*`` cannot be root-anchored the way a policy written against
    ``${aws:PrincipalTag/username}`` can — an IAM ``Resource`` wildcard matches ``/`` and there is
    no way to say "one path segment". The strict side was taken, so a nested personal
    ``athenaresults/`` is undeletable by this plane while the browser still permits it directly.
    Mirroring IAM rather than the browser is what turns that divergence into a per-item refusal
    that has moved nothing, instead of an ``AccessDenied`` part way through a batch.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients, errors
from cpcommon.errors import TerminalError, TransientError
from cpcommon.paths import has_dot_segment

from . import messages  # noqa: F401
from .config import (
    ARCHIVE_FOLDER,
    ATHENA_RESULTS_FOLDER,
    FILE_OPS_HEAD_CONCURRENCY,
    MARKER_BASENAME,
    USER_SETTINGS_FOLDER,
)

logger = logging.getLogger(__name__)

MAX_KEYS_PER_BATCH = 1000

HEAD_CONCURRENCY = FILE_OPS_HEAD_CONCURRENCY

CONDITIONAL_DELETE_ENABLED = False

SOURCE_CHANGED = "source_changed"
SOURCE_DELETE_FAILED = "source_delete_failed"
DELETE_REFUSED = "delete_refused"

_PRECONDITION_CODES = frozenset({"PreconditionFailed", "412", "PreconditionNotMet"})

_CONFLICT_CODES = frozenset({"ConditionalRequestConflict", "409"})

_ALREADY_GONE = frozenset({"NoSuchKey", "NotFound", "404"})

_DENIED_CODES = frozenset({"AccessDenied", "403"})

_UNDELETABLE_FOLDERS = (ATHENA_RESULTS_FOLDER, USER_SETTINGS_FOLDER, ARCHIVE_FOLDER)

__all__ = [
    "CONDITIONAL_DELETE_ENABLED",
    "DELETE_REFUSED",
    "MAX_KEYS_PER_BATCH",
    "SOURCE_CHANGED",
    "SOURCE_DELETE_FAILED",
    "assert_item_deletable",
    "delete_item_keys",
    "supports_conditional_delete",
]


def supports_conditional_delete() -> bool:
    """Reports whether this runtime can send a per-object ETag on ``DeleteObjects``.

    Read off the live service model rather than a version string, because the question is whether
    THIS runtime's botocore carries the field — the Lambda runtime bundles its own, and a
    ``ParamValidationError`` here would fail every move's source deletion in production.

    **It is a necessary condition and not a sufficient one.** A model that carries the field proves
    only that botocore will serialize it; whether S3 enforces it on these buckets is what the owed
    live probe answers, and ``CONDITIONAL_DELETE_ENABLED`` is the gate that waits for it.

    Args:
      None.

    Returns:
      True when ``ObjectIdentifier`` carries an ``ETag`` member.

    Raises:
      None. A runtime that cannot be introspected reports False, which selects the path that works
      everywhere.
    """
    try:
        shape = clients.s3().meta.service_model.shape_for("ObjectIdentifier")
        return bool("ETag" in shape.members)
    except Exception:  # noqa: BLE001 - an unintrospectable client takes the path that always works
        logger.info("could not read the S3 model; taking the head-compare delete path")
        return False


def _reason_for(code: str) -> str | None:
    """Maps one ``Errors`` entry's code to this plane's reason, or None when it is not a failure.

    Args:
      code: The ``Code`` string S3 returned for that key.

    Returns:
      The reason code, or None when the object is in fact gone.

    Raises:
      TransientError: On a documented 409 conflict — a concurrent delete or put beat this one,
        which is retryable rather than a precondition mismatch. Raised so the state's own ``Retry``
        re-runs the verb.
    """
    if code in _ALREADY_GONE:
        return None
    if code in _CONFLICT_CODES:
        raise TransientError(f"a concurrent write beat this delete ({code})")
    if code in _PRECONDITION_CODES:
        return SOURCE_CHANGED
    if code in _DENIED_CODES:
        return DELETE_REFUSED
    return SOURCE_DELETE_FAILED


def assert_item_deletable(keys: list, allowed_prefix: str) -> None:
    """Confirms every key of ONE item may be deleted, BEFORE any delete is issued.

    **Scoped per ITEM, not over the whole list, and that is the difference from the archive's
    version of this rule.** A whole-list refusal would be the whole-request reversion this plane's
    model forbids — and on a ``move`` it runs after the copy, so it would leave every item copied
    and nothing deleted: a full duplicate of the entire selection. An item containing a denied key
    fails alone; its siblings are deleted.

    Four rules, and the ordering is the point of the function. The bucket policies deny
    ``s3:DeleteObject`` on the marker at any depth and the execution role denies the portal's own
    folders, so a list carrying one of those does not fail as a whole — it fails PART WAY THROUGH,
    after some of the user's data is already gone. Checking up front turns that into a refusal that
    has moved nothing.

    **Containment is BOTH rules, not just the prefix one.** A key is rebuilt from a root and a
    stored relative key, and ``"alice/../bob/secrets.csv"`` starts with ``"alice/"`` — so a prefix
    test alone accepts it. S3 resolves nothing, so such a key names an object that almost certainly
    does not exist; the rule is here because a containment rule that holds only while every
    consumer stays careful is not a rule, and this consumer is the one that deletes.

    Args:
      keys: The absolute keys of one item, about to be deleted.
      allowed_prefix: The only prefix these keys may sit under.

    Returns:
      None.

    Raises:
      TerminalError: ``forbidden`` for a key outside the allowed prefix or carrying a dot segment,
        ``marker_not_deletable`` for a protection marker, or ``delete_refused`` for a key under a
        folder this plane's own IAM denies.
    """
    for key in keys:
        if not isinstance(key, str) or not key.startswith(allowed_prefix):
            raise TerminalError("forbidden", f"{key!r} is not inside {allowed_prefix!r}")
        if has_dot_segment(key):
            raise TerminalError("forbidden", f"{key!r} carries a path segment that is not allowed")
        segments = key.split("/")
        if segments[-1] == MARKER_BASENAME:
            raise TerminalError(
                "marker_not_deletable",
                f"{key!r} is undeletable, so the deletion was not attempted",
                tokens={"itemName": MARKER_BASENAME},
            )
        if any(segment in _UNDELETABLE_FOLDERS for segment in segments[:-1]):
            raise TerminalError(
                DELETE_REFUSED,
                f"{key!r} sits under a folder this plane may not delete from",
            )


def _changed_keys(bucket: str, expected: dict) -> set:
    """Heads every key and returns the ones whose ETag is not what the plan recorded.

    The HEAD-compare path's whole content. It is weaker than a conditional delete — the object can
    change between the head and the delete — and slower, and it is the path that runs, because it
    depends on nothing but ``HeadObject``.

    An absent object is NOT reported as changed: it is already gone, which is the outcome asked for
    and what keeps a replayed verb from reporting failures for work its predecessor finished.

    Args:
      bucket: The source bucket.
      expected: Key to the ETag the plan recorded for it.

    Returns:
      The keys that no longer match.

    Raises:
      TransientError: On a throttle or 5xx — a sweep that cannot see the source must retry rather
        than conclude that nothing changed.
    """
    def compare(key: str) -> bool:
        """Reports whether one key has changed since the plan recorded it.

        Args:
          key: The source key.

        Returns:
          True when the object is present and its ETag differs from the plan's.

        Raises:
          TransientError: On a throttle or 5xx.
        """
        try:
            head = clients.s3().head_object(Bucket=bucket, Key=key)
        except Exception as err:  # noqa: BLE001 - classified below
            errors.raise_if_transient(err, f"head {bucket}/{key}")
            return errors.error_code(err) not in _ALREADY_GONE
        return bool((head.get("ETag") or "") != expected[key])

    keys = list(expected)
    with ThreadPoolExecutor(max_workers=HEAD_CONCURRENCY) as pool:
        return {key for key, changed in zip(keys, pool.map(compare, keys), strict=True) if changed}


def _issue(bucket: str, batch: list, etags: dict | None) -> dict:
    """Issues one ``DeleteObjects`` call and returns the per-key reasons it reported.

    Args:
      bucket: The bucket to delete from.
      batch: The keys in this batch.
      etags: Key to the ETag each delete is conditional on, or None for an unconditional delete.

    Returns:
      Key to reason for every key that did not go. Empty when the whole batch went.

    Raises:
      TransientError: When the call failed retryably, or when any key reported a 409 conflict.
    """
    objects = [
        {"Key": key, **({"ETag": etags[key]} if etags else {})} for key in batch
    ]
    try:
        response = clients.s3().delete_objects(
            Bucket=bucket, Delete={"Objects": objects, "Quiet": False}
        )
    except Exception as exc:  # noqa: BLE001 - classified below
        errors.raise_if_transient(exc, f"delete {len(batch)} object(s) in {bucket}")
        logger.warning("a delete batch of %d object(s) in %s failed", len(batch), bucket)
        return dict.fromkeys(batch, SOURCE_DELETE_FAILED)

    reasons = {}
    for entry in response.get("Errors") or []:
        reason = _reason_for(entry.get("Code") or "")
        if reason is not None:
            reasons[entry.get("Key")] = reason
    return reasons


def delete_item_keys(
    bucket: str, keys: list, etags: dict, allowed_prefix: str, *, conditional: bool
) -> dict:
    """Deletes one item's keys and reports what did not go and why.

    **``conditional`` IS THE CALLER'S DECISION AND IS NEVER INFERRED HERE.** A ``move``'s deletion is
    conditional because it protects bytes that were just copied; a ``delete`` operation's is
    deliberately unconditional, because there is no copy to protect and an object modified since the
    expansion is still one the user asked to remove. Deriving it from whether the ETags happen to be
    present would make a delete conditional on an empty string, which mismatches everything.

    Batched per ITEM rather than across the whole selection, so ``Errors[].Key`` attributes back
    without a key-to-item join that could be wrong — attribution on this plane is per item, and a
    batch spanning two items would need one.

    Replay-safety comes from ``_reason_for`` treating an absent key as deleted. That is what makes
    the state's ``Retry`` correct on a verb whose effect is a deletion, and it is NOT free on the
    conditional path the way it is on the unconditional one.

    Args:
      bucket: The bucket to delete from.
      keys: This item's absolute source keys, from the plan.
      etags: Key to the ETag the PLAN recorded. Read only when ``conditional`` is set.
      allowed_prefix: The only prefix these keys may sit under.
      conditional: Whether this deletion must confirm the object is unchanged first.

    Returns:
      ``{"deleted": n, "failed": m, "reason": code or ""}`` — the reason is the first distinct one
      encountered, because an item reports one outcome and a list of codes is a list of keys by
      another name.

    Raises:
      TerminalError: ``forbidden``, ``marker_not_deletable`` or ``delete_refused`` from the
        pre-check, before any delete is issued.
      TransientError: On a retryable S3 fault, after every batch has been attempted.
    """
    assert_item_deletable(keys, allowed_prefix)

    send_etags = conditional and CONDITIONAL_DELETE_ENABLED and supports_conditional_delete()
    reasons: dict = {}
    if conditional and not send_etags:
        for key in _changed_keys(bucket, {key: etags.get(key, "") for key in keys}):
            reasons[key] = SOURCE_CHANGED

    to_delete = [key for key in keys if key not in reasons]
    transient = None
    for start in range(0, len(to_delete), MAX_KEYS_PER_BATCH):
        batch = to_delete[start : start + MAX_KEYS_PER_BATCH]
        try:
            reasons.update(
                _issue(bucket, batch, {key: etags[key] for key in batch} if send_etags else None)
            )
        except TransientError as retryable:
            transient = transient or retryable

    if transient is not None:
        raise transient
    failed = len(reasons)
    return {
        "deleted": len(keys) - failed,
        "failed": failed,
        "reason": next(iter(reasons.values()), "") if reasons else "",
    }
