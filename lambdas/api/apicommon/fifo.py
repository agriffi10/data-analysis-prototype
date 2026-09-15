"""Every FIFO key the enqueue routes send, derived in one module and nowhere else.

Four derivation families over eleven routes, and none of them has an error path: a wrong
``MessageGroupId`` still sends. It changes which requests are STARTED in order behind each other,
and the only symptom is a race nobody can reproduce. For a plane a Pipe feeds, that is all it does:
every Pipe starts its machine fire-and-forget, so a plane whose runs must not overlap needs a guard
of its own, a lock or a conditional write. The notifications queue is the exception: a Lambda event
source mapping drains it, and on a FIFO queue that runs one invocation per group at a time, so its
group id does serialize one user's writes. A wrong ``MessageDeduplicationId`` stops collapsing
double-submits, and the symptom is two shares, two archives, two builds. Every derivation here is
pinned to a golden vector captured from the browser's own TypeScript before it was deleted.

The bucket a space lives in is read from this function's configuration by ``kind`` alone. It is
deliberately NOT resolved through ``apicommon.spaces.resolve``, which also checks membership: the
API stamps identity and does not authorize, and a second authority for a question the plane's
validate-authorize verb already answers is a divergence waiting to happen.

What SQS accepts as a key is not decided here: ``cpcommon.config.FIFO_KEY_RE`` is the one rule,
shared with the notification sender, and ``_checked`` applies it to every derived key.

Attributes:
  DEDUP_BUCKET_MS: The width of table-share's dedup window, in milliseconds. Submits of one
    request inside one window collapse; a deliberate re-share later goes through.
"""

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any, cast

from cpcommon.app_managed import vault_archive_prefix
from cpcommon.auth import Principal
from cpcommon.config import FIFO_KEY_RE, MAX_FIFO_KEY_CHARS

from . import config
from .envelope import ApiError

DEDUP_BUCKET_MS = 60_000


def _sha(canonical: str) -> str:
    """Digests a canonical string the way every producer of a group id does.

    Args:
      canonical: The string to digest.

    Returns:
      The SHA-256 of its UTF-8 bytes, lower-case hex.

    Raises:
      None.
    """
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bucket_for(kind: str) -> str:
    """Resolves a space kind to the bucket that holds it.

    Args:
      kind: The space kind the request named.

    Returns:
      The bucket name from this function's configuration.

    Raises:
      ApiError: ``InvalidRequest`` if the kind is neither of the two. The request types declare a
        closed vocabulary, so a third value cannot reach here through the door; this is the guard
        for a caller that reaches a derivation another way.
      ConfigError: If the bucket variable is unset. Unlike the browser, which fell back to an
        empty string and silently digested ``/{name}/``, this raises at first read.
    """
    if kind == "personal":
        return config.user_space_bucket()
    if kind == "shared":
        return config.shared_space_bucket()
    raise ApiError("InvalidRequest", "unknown space kind")


def _space_digest(bucket: str, name: str) -> str:
    """Digests the one string every space-keyed plane orders its queue by.

    The name is trimmed and stripped of trailing slashes before the slash is appended, because the
    browser's twin did exactly that: a name arriving as ``alice/`` would otherwise produce
    ``.../alice//`` here against ``.../alice/`` there, and the file-operations plane hashes this
    same string again to key its per-space lock. Disagreement is silent — nothing reports that
    delivery is ordered on one key while the lock is held under another.

    Args:
      bucket: The bucket the space lives in.
      name: The space's name.

    Returns:
      The 64-character lower-case hex digest.

    Raises:
      ApiError: ``InvalidRequest`` if either part is empty once trimmed. Hashing an empty bucket
        would put every space behind one group id, and the browser's twin threw for the same
        reason.
    """
    trimmed = name.strip().rstrip("/")
    if not bucket or not trimmed:
        raise ApiError("InvalidRequest", "a space digest needs a bucket and a name")
    return _sha(f"{bucket}/{trimmed}/")


def _normalize_location(location: str) -> str:
    """Collapses a data-quality location to its canonical form.

    Strips leading AND trailing slashes after trimming whitespace, so the canonical string ends
    without a slash. That is the one place this family diverges from the space digest above, which
    ends with one, and the divergence is real rather than a transcription slip.

    Args:
      location: The location the request named.

    Returns:
      The location with surrounding whitespace and both ends' slashes removed.

    Raises:
      None.
    """
    return location.strip().strip("/")


def _space(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reads the space a payload names.

    Args:
      payload: The validated request body.

    Returns:
      The space mapping.

    Raises:
      None.
    """
    return cast("Mapping[str, Any]", payload["space"])


def _group_shared_space(principal: Principal, payload: Mapping[str, Any]) -> str:
    """One global group, so two users cannot create the same space name concurrently.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body. Unused.

    Returns:
      The constant group id.

    Raises:
      None.
    """
    return "shared-space"


def _group_notifications(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Groups a user's notification actions behind their own verified username.

    This is the one group id derived from the verified actor rather than from the body. The
    browser sent a caller-supplied username, which let a caller interleave into another user's
    FIFO group; for every real call the value is byte-identical to what it was.

    Args:
      principal: The verified caller.
      payload: The validated request body. Unused.

    Returns:
      The caller's verified username.

    Raises:
      None.
    """
    return principal.username


def _group_table_build(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Serializes table builds per target database, closing the duplicate-name race.

    Raw rather than hashed, which is safe here and not elsewhere: a database name is bounded at 63
    characters by the catalog identifier rule, where an S3 key reaches 1024 and would breach SQS's
    128-character cap for exactly the users with the deepest prefixes.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body.

    Returns:
      The target database name.

    Raises:
      None.
    """
    return cast("str", _space(payload)["database"])


def _group_table_share(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Serializes repeated shares of one source table while different sources run in parallel.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body.

    Returns:
      The source's ``database.table``, raw for the same bounded-length reason as table build.

    Raises:
      None.
    """
    source = payload["source"]
    return f"{source['database']}.{source['table']}"


def _group_data_quality(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Serializes checks of one location while different locations run in parallel.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body.

    Returns:
      The digest of ``{bucket}/{normalized location}`` — with no trailing slash.

    Raises:
      ApiError: ``InvalidRequest`` on an unknown space kind.
      ConfigError: If the bucket variable is unset.
    """
    bucket = _bucket_for(_space(payload)["kind"])
    return _sha(f"{bucket}/{_normalize_location(payload['location'])}")


def _group_space_root(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Groups one space's work, for the three planes keyed that way, so its starts are ordered.

    It does not serialize the runs. File-ops holds a per-space lock for that; file-send and archive
    hold none, and ``infra/modules/archive/README.md`` says what an overlapping archive does.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body, whose space is at the top level or under ``source``.

    Returns:
      The digest of ``{bucket}/{space name}/``.

    Raises:
      ApiError: ``InvalidRequest`` on an unknown space kind or an empty name.
      ConfigError: If the bucket variable is unset.
    """
    space = payload["source"]["space"] if "source" in payload else _space(payload)
    return _space_digest(_bucket_for(space["kind"]), space["name"])


def _group_archive_restore(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Groups the restores of ONE archive, so their starts are ordered apart from other archives'.

    It does not serialize them: the Pipe starts the machine fire-and-forget, so a double-submitted
    restore still runs twice at once and can pass the destination guard twice, and
    ``infra/modules/archive/README.md`` says what follows. The archive bucket is deliberately
    absent: the browser had no relationship with that bucket by decision, it is one constant across
    every restore this app can make, and the ``personal/``/``shared/`` segment already makes the
    archive root globally unique.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body.

    Returns:
      The digest of ``{kind}/{name}/archive/{archiveId}/``.

    Raises:
      None.
    """
    space = _space(payload)
    return _sha(vault_archive_prefix(space["kind"], f"{space['name']}/", payload["archiveId"]))


def _group_results_conversion(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Serializes one user's conversions behind their own verified username.

    Raw rather than hashed, which is safe here: a username is bounded by the catalog identifier
    rule at 63 characters, well inside the queue's 128. Derived from the verified actor rather
    than from the body, as the notifications group is, so a caller cannot interleave into
    another user's group.

    Args:
      principal: The verified caller.
      payload: The validated request body. Unused.

    Returns:
      The caller's verified username.

    Raises:
      None.
    """
    return principal.username


def _dedup_request_id(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Takes the caller's own per-submit request id as the dedup key.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body.

    Returns:
      The body's ``requestId``.

    Raises:
      None.
    """
    return cast("str", payload["requestId"])


def _dedup_fresh_uuid(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Mints the one id this service generates, for the plane with no request id.

    The notifications plane's actions are idempotent and carry no request id, so there is nothing
    to echo. This value is a queue key and never reaches a response or a message body.

    Args:
      principal: The verified caller. Unused.
      payload: The validated request body. Unused.

    Returns:
      A fresh UUID.

    Raises:
      None.
    """
    return str(uuid.uuid4())


def _dedup_table_share(principal: Principal, payload: Mapping[str, Any]) -> str:
    """Collapses a double-submitted share, keyed on the VERIFIED ACTOR rather than on a token.

    Table-share is the only plane with no request id, so this digest is the entire double-submit
    guard. The browser hashed the ID token in position 0, which meant two submits a minute apart
    with a token refresh between them were two shares — the guard lapsed silently. Substituting
    the verified actor fixes that and survives the token going away entirely.

    The source object is rebuilt in a fixed key order rather than passed through: the parsed body
    preserves the caller's key order, so a caller sending ``{"table": …, "database": …}`` would
    otherwise digest differently from one sending the same two fields the other way round.

    Args:
      principal: The verified caller.
      payload: The validated request body.

    ``ensure_ascii`` is off because it is on by default and would emit ``caf\\u00e9`` where
    ``JSON.stringify`` emits ``café`` — a divergence no test over ASCII fixtures can see, on a
    value that reaches here as a shared-space name, which is format-checked nowhere server-side.

    Returns:
      The digest of the canonical array, matching ``JSON.stringify`` byte for byte.

    Raises:
      None.
    """
    source = payload["source"]
    recipients = sorted(f"{r['kind']}:{r['name']}" for r in payload["recipients"])
    bucket = int(time.time() * 1000) // DEDUP_BUCKET_MS
    canonical = json.dumps(
        [
            principal.username,
            {"database": source["database"], "table": source["table"]},
            payload["tableName"],
            recipients,
            bucket,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha(canonical)


_GROUP: Mapping[str, Callable[[Principal, Mapping[str, Any]], str]] = {
    "sharedSpace.enqueue": _group_shared_space,
    "notifications.enqueue": _group_notifications,
    "tableBuild.create": _group_table_build,
    "tableBuild.refresh": _group_table_build,
    "tableShare.enqueue": _group_table_share,
    "dataQuality.enqueue": _group_data_quality,
    "fileSend.enqueue": _group_space_root,
    "archive.archive": _group_space_root,
    "archive.restore": _group_archive_restore,
    "fileOps.enqueue": _group_space_root,
    "resultsConversion.enqueue": _group_results_conversion,
}

_DEDUP: Mapping[str, Callable[[Principal, Mapping[str, Any]], str]] = {
    "sharedSpace.enqueue": _dedup_request_id,
    "notifications.enqueue": _dedup_fresh_uuid,
    "tableBuild.create": _dedup_request_id,
    "tableBuild.refresh": _dedup_request_id,
    "tableShare.enqueue": _dedup_table_share,
    "dataQuality.enqueue": _dedup_request_id,
    "fileSend.enqueue": _dedup_request_id,
    "archive.archive": _dedup_request_id,
    "archive.restore": _dedup_request_id,
    "fileOps.enqueue": _dedup_request_id,
    "resultsConversion.enqueue": _dedup_request_id,
}


def _checked(key: str, field: str) -> str:
    """Refuses a derived key the queue would not accept, before the send is attempted.

    Four of the ten group ids are a raw string rather than a digest, and two of those concatenate a
    value nothing upstream bounds: a source table name is only required to be a non-empty string,
    and a caller's own request id becomes a dedup id verbatim. Unchecked, an over-long or
    non-ASCII key is refused by SQS itself and comes back as a generic failure with nothing naming
    the key — on every attempt, for the one user whose table name or id is unusual.

    Args:
      key: The derived value.
      field: Which key it is, for the refusal's operator text.

    Returns:
      The value, unchanged.

    Raises:
      ApiError: ``InvalidRequest`` if it is too long or carries a character the queue refuses.
    """
    if not FIFO_KEY_RE.fullmatch(key):
        raise ApiError(
            "InvalidRequest",
            f"the derived {field} is longer than {MAX_FIFO_KEY_CHARS} characters "
            "or carries a character the queue refuses",
        )
    return key


def group_id_for(
    route_id: str, principal: Principal, payload: Mapping[str, Any]
) -> str:
    """Derives one route's ``MessageGroupId``.

    Args:
      route_id: The enqueue route's id.
      principal: The verified caller.
      payload: The validated request body.

    Returns:
      The group id to send.

    Raises:
      ApiError: ``InvalidRequest`` on an unknown space kind, an unusable space name, or a derived
        key the queue would refuse.
      KeyError: If the route id names no enqueue route. Every caller reaches this through a
        declared route, so an unknown id is a programming error rather than a caller's.
      ConfigError: If a bucket variable this derivation needs is unset.
    """
    return _checked(_GROUP[route_id](principal, payload), "message group id")


def dedup_id_for(
    route_id: str, principal: Principal, payload: Mapping[str, Any]
) -> str:
    """Derives one route's ``MessageDeduplicationId``.

    Set explicitly on every route, including the three queues deployed with content-based
    deduplication on. Omitting it there does not error — SQS falls back to hashing the body, which
    still mostly collapses double-submits — so the guard the plane was specified with would be
    gone with nothing going red.

    Args:
      route_id: The enqueue route's id.
      principal: The verified caller.
      payload: The validated request body.

    Returns:
      The dedup id to send.

    Raises:
      KeyError: If the route id names no enqueue route.
      ApiError: ``InvalidRequest`` if the derived id is unusable as a queue key.
    """
    return _checked(_DEDUP[route_id](principal, payload), "deduplication id")
