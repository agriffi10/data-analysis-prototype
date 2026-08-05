"""Publish the username directory: every personal workspace on the user-space bucket (SPEC-146).

Once a day an EventBridge schedule fires this function. It lists the user-space bucket's
top-level common prefixes, keeps the ones that are catalog-safe usernames, and publishes a
small sorted JSON document to ``s3://{USER_SPACE_BUCKET}/_directory/usernames.json``. The
browser reads that document to suggest usernames as a user types (SPEC-147/148).

**The source is S3 common prefixes, NOT Cognito ``ListUsers``, and that is a decision rather
than a convenience** (settled 2026-08-03, after reading ``docs/transition_plan.md``). Today
Cognito is the complete record and S3 is not: the personal prefix is created BY THE BROWSER on
the first visit to ``/files`` (``ensurePrefixMarker``, SPEC-014 — a deliberate no-backend
decision), so a confirmed user who never opened the file browser has no prefix here. The
transition reverses it. ``transition_plan.md`` §2 item 7 settles that sign-in provisions
nothing — the sync pre-creates every space and ``ensurePrefixMarker`` is deleted outright
(§6.3) — while federated login makes ``cognito:username`` a synthetic ``identitycenter_<subject>``
value (§6.1) and users appear in the pool only after their first sign-in. So S3 becomes
complete and Cognito becomes both incomplete and wrong-keyed.

**Do not "fix" this back to ``ListUsers``, and do not add it as a union "to be safe":** a
second source with different completeness properties is a second thing to reason about every
time the directory looks wrong. A test asserts this module never imports or clientises Cognito.

**The document is ADVISORY. A name's presence in it grants nothing.** No control plane reads
it, no membership check consults it, and no browser field refuses a name that is missing from
it. Existence is still decided where it always was — ``admin_get_user`` against the User Pool,
in ``shared-space-common/membership.py`` and ``tscommon/cognito.py`` — and an unknown name is
still reported back to the user as a notification. The residual gap (a confirmed user who has
never opened the file browser is absent until the transition lands) is therefore bounded: they
can still be added, just without a suggestion.
"""

import json
import logging
from datetime import UTC, datetime

from cpcommon import clients, config, observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="user-directory")

#: The reserved root prefix this document lives under. Safe as the user-space bucket's ONE
#: exception to "every top-level prefix is a username" for a mechanical reason:
#: CATALOG_IDENTIFIER_RE requires a leading lowercase letter, so `_directory` can never BE a
#: username. That is precisely why the name was chosen, and it is also why the builder needs
#: no special case to exclude its own output — the regex filter already does (FR-001/FR-003).
DIRECTORY_PREFIX = "_directory"

#: The published document's key.
DIRECTORY_KEY = f"{DIRECTORY_PREFIX}/usernames.json"

#: Bumped only when the SHAPE changes. Present from day one so the browser can refuse a
#: document it does not understand (SPEC-147 FR-001) rather than crash on it.
DOCUMENT_VERSION = 1


@observability.step("list-workspaces")
def list_workspace_usernames(bucket: str) -> tuple[list[str], int, int]:
    """Return ``(sorted usernames, dropped_count, pages_listed)``.

    Every top-level common prefix on the user-space bucket is a personal workspace.
    ``Delimiter="/"`` makes S3 return those prefixes rather than every object under them, so
    the cost is one page per ~1000 users rather than one per ~1000 objects.

    Anything that is not a catalog-safe username is dropped and counted — including this
    module's own ``_directory`` output. Dropping by REGEX rather than by a special case is
    deliberate: ``CATALOG_IDENTIFIER_RE`` requires a leading lowercase letter, which is the
    property that makes ``_directory`` a safe reserved name in the first place.
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
    """Write the document and return the bytes written.

    **A plain ``PutObject``, with no ETag CAS, and that is correct here rather than an
    oversight.** There is exactly one writer on a 24-hour schedule, the document is rebuilt
    from scratch every run with no incremental state, and the right behaviour on a concurrent
    write is last-wins. The CAS loops in ``log_sweep`` and ``dqcommon.index_store`` exist
    because those objects are APPENDED to by many writers — a lost update there loses data
    that exists nowhere else. Do not "harden" this into the same pattern.

    **No ``Cache-Control``.** The browser fetches this through the S3 SDK with SigV4, not
    through CloudFront, and whether an HTTP cache directive affects an SDK-issued request is
    not a property this repo should rely on. SPEC-147's TanStack ``staleTime`` is the caching
    mechanism, and it is the only one.
    """
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
    """Rebuild and publish the username directory.

    **The event payload is ignored entirely**, which is what makes a manual rebuild possible
    without waiting for the schedule::

        aws lambda invoke --function-name dat-prod-user-directory-build \\
            --payload '{}' --cli-binary-format raw-in-base64-out /dev/stdout

    **An empty result never overwrites a non-empty document.** A bucket-listing failure that
    returned an empty page would otherwise erase the directory, and an erased directory is
    indistinguishable to a user from a broken feature — the suggestions simply stop appearing,
    with nothing to indicate why. So a run that finds no usernames logs an error and exits
    without writing, leaving yesterday's document in place.

    The event count here is O(1) in the number of users: one root span, two child spans, and a
    bounded handful of level events. Nothing iterates users to emit. A per-username emitter
    would turn a growing organisation into a growing log bill, in a store retained forever —
    the same bound SPEC-131 put on the sweep, for the same reason. **The username list itself
    is not logged**: usernames are metadata and individually permitted under the field rule,
    but the whole list IS the document, it is already durable in S3, and ``logs/`` never
    expires.
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
