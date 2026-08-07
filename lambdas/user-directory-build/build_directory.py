"""Publishes the username directory: every personal workspace on the user-space bucket.

Once a day a schedule fires this function. It lists the user-space bucket's top-level common
prefixes, keeps the ones that are catalog-safe usernames, and publishes a small sorted JSON
document the browser reads to suggest usernames as a user types.

The source is S3 common prefixes, not Cognito, and that is a decision rather than a
convenience — do not "fix" it back, and do not add Cognito as a union "to be safe". A test
asserts this module never imports or clientises Cognito. The document is advisory: a name's
presence in it grants nothing. Reasoning: ``docs/lambda-rationale.md``.

Attributes:
  DIRECTORY_PREFIX: The reserved root prefix this document lives under. Safe as the bucket's
    one exception to "every top-level prefix is a username" for a mechanical reason — the
    catalog identifier rule requires a leading lowercase letter, so this can never be a
    username. That is why the name was chosen, and why the builder needs no special case to
    exclude its own output.
  DIRECTORY_KEY: The published document's key.
  DOCUMENT_VERSION: Bumped only when the document's shape changes. Present from day one so the
    browser can refuse a document it does not understand rather than crash on it.
"""

import json
import logging
from datetime import UTC, datetime

from cpcommon import clients, config, observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="user-directory")

DIRECTORY_PREFIX = "_directory"

DIRECTORY_KEY = f"{DIRECTORY_PREFIX}/usernames.json"

DOCUMENT_VERSION = 1


@observability.step("list-workspaces")
def list_workspace_usernames(bucket: str) -> tuple[list[str], int, int]:
    """Lists every personal workspace on the user-space bucket.

    Every top-level common prefix is a personal workspace. Delimiting makes S3 return those
    prefixes rather than every object under them, so the cost is one page per thousand users
    rather than one per thousand objects.

    Anything that is not a catalog-safe username is dropped and counted, including this
    module's own output. Dropping by regex rather than by a special case is deliberate: the
    identifier rule requires a leading lowercase letter, which is the property that makes the
    reserved prefix safe in the first place.

    Args:
      bucket: The user-space bucket.

    Returns:
      A ``(sorted usernames, dropped count, pages listed)`` tuple.

    Raises:
      ClientError: On any S3 listing fault.
    """
    paginator = clients.s3().get_paginator("list_objects_v2")
    seen: set[str] = set()
    prefix_count = 0
    dropped = 0
    pages = 0
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        pages += 1
        for entry in page.get("CommonPrefixes", []):
            raw = str(entry.get("Prefix", ""))
            prefix_count += 1
            name = raw.rstrip("/")
            if not config.CATALOG_IDENTIFIER_RE.match(name):
                dropped += 1
                continue
            seen.add(name)
    observability.info(
        "listed workspaces",
        prefix_count=prefix_count,
        username_count=len(seen),
        dropped_count=dropped,
        pages_listed=pages,
    )
    return sorted(seen), dropped, pages


@observability.step("publish")
def publish(bucket: str, usernames: list[str]) -> int:
    """Writes the directory document and returns the bytes written.

    A plain put with no compare-and-swap, and that is correct here rather than an oversight:
    there is exactly one writer on a daily schedule, the document is rebuilt from scratch every
    run with no incremental state, and the right behaviour on a concurrent write is last-wins.
    The CAS loops elsewhere in this repo exist because those objects are appended to by many
    writers, where a lost update loses data that exists nowhere else. Do not harden this into
    the same pattern.

    No cache directive is set. The browser fetches this through the S3 SDK with signed requests
    rather than through the CDN, and whether an HTTP cache directive affects an SDK-issued
    request is not a property this repo should rely on — the client's own stale time is the
    caching mechanism, and the only one.

    Args:
      bucket: The user-space bucket.
      usernames: The sorted usernames to publish.

    Returns:
      The number of bytes written, or 0 when nothing was written.

    Raises:
      ClientError: On any S3 write fault.

    Note:
      An empty list is refused. The handler already decides this — it needs to, because it owns
      the error event and the return value — so this guard is unreachable today. It is here
      anyway because the refusal is a property of publishing rather than of one call site: a
      second caller added later would otherwise inherit no protection at all, and the failure it
      prevents is silent, wholesale erasure.
    """
    if not usernames:
        return 0
    body = json.dumps(
        {
            "version": DOCUMENT_VERSION,
            "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(usernames),
            "usernames": usernames,
        }
    ).encode("utf-8")
    clients.s3().put_object(
        Bucket=bucket,
        Key=DIRECTORY_KEY,
        Body=body,
        ContentType="application/json",
    )
    return len(body)


@observability.traced("build-directory")
def handler(event, context):
    """Rebuilds and publishes the username directory.

    An empty result never overwrites a non-empty document. A bucket-listing failure that
    returned an empty page would otherwise erase the directory, and an erased directory is
    indistinguishable to a user from a broken feature — the suggestions simply stop appearing,
    with nothing to indicate why. So a run that finds no usernames records an error and exits
    without writing, leaving yesterday's document in place.

    The event count is constant in the number of users: one root span, two child spans and a
    bounded handful of level events. A per-username emitter would turn a growing organisation
    into a growing log bill, in a store retained forever. The username list itself is not
    recorded: usernames are individually permitted metadata, but the whole list is the document,
    it is already durable in S3, and the log store never expires.

    Args:
      event: Ignored entirely, which is what makes a manual rebuild possible without waiting
        for the schedule — invoke the function with an empty payload.
      context: The Lambda context, unused.

    Returns:
      A dict reporting whether it published, the username count, and the bytes written when it
      did.

    Raises:
      ClientError: On an S3 write fault. A listing fault propagates too, before any decision.
    """
    bucket = config.USER_SPACE_BUCKET
    usernames, dropped, pages = list_workspace_usernames(bucket)

    if not usernames:
        logger.error(
            "user-directory: listing produced no usernames; leaving the existing document in place"
        )
        observability.error(
            "no usernames found; not publishing",
            dropped_count=dropped,
            pages_listed=pages,
        )
        return {"published": False, "username_count": 0}

    written = publish(bucket, usernames)
    logger.info("user-directory: published %d username(s) to %s", len(usernames), DIRECTORY_KEY)
    observability.info(
        "published",
        key=DIRECTORY_KEY,
        username_count=len(usernames),
        dropped_count=dropped,
        pages_listed=pages,
        bytes_written=written,
    )
    return {"published": True, "username_count": len(usernames), "bytes_written": written}
