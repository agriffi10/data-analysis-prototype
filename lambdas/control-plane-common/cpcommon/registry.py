"""Read-only access to the shared-spaces registry.

The registry is one S3 control object per space under ``shared-spaces/`` in the analytics
admin bucket, owned by the shared-spaces control plane. Every other control-plane verb only
ever reads it — to authorize that the actor is an active member of a space, and to confirm
a share target exists.

**Every role that calls this needs ``s3:ListBucket`` on the admin bucket covering
``shared-spaces/``, and the None below is unreachable without it.** S3 reports a missing object
as ``NoSuchKey`` only to a caller that can list; to one that cannot, the same missing object is
``AccessDenied``. So a plane holding only the ``GetObject`` grant reads a registered space
correctly and faults on an unregistered one — which is the case the None exists for. Measured
live on 2026-08-17: a send naming an unregistered space raised out of ``load`` under a role with
no list statement, instead of taking its caller's ``unknown_space`` refusal. The grant is
conditioned to the registry prefix on every plane, which is sufficient and keeps the space names
themselves unlistable; ``lambdas/test_absence_is_answerable.py`` holds each plane to it.
"""

import json
from typing import cast

from . import clients, config
from .budget import Budget


def load(name: str, client=None) -> dict | None:
    """Reads one shared space's registry record from the admin bucket.

    Args:
      name: The shared space name.
      client: The S3 client to read with, the per-container default when None. ``owner_of``
        passes the bounded one.

    Returns:
      The record, or None if no such space is registered.

    Raises:
      ClientError: On any S3 failure other than a missing key.
      ValueError: If the stored record is not valid JSON.
    """
    s3 = client or clients.s3()
    try:
        obj = s3.get_object(Bucket=config.ADMIN_BUCKET, Key=f"shared-spaces/{name}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return cast("dict", json.loads(obj["Body"].read()))


def owner_of(name: str, calls: Budget) -> str:
    """Reads a space's registered owner for a notice sent after the work it reports, in time.

    Table share and file send tell a space recipient's owner once the sender has been told, so
    the lookup is optional work after the outcome, and a stall on it must not hold the verb to its
    timeout. The whole read, the body included, runs as one call under ``calls`` on the bounded
    client, which is built here on the caller's thread.

    Args:
      name: The shared space name.
      calls: The budget the lookup shares with the notices around it.

    Returns:
      The owner's username, or an empty string for a space with no record or no owner.

    Raises:
      TimeoutError: When the budget's deadline has passed, or the read is still running at the cap.
      ClientError: On any S3 failure other than a missing key.
      ValueError: If the stored record is not valid JSON.
    """
    s3 = clients.s3_bounded()
    record = calls.call(lambda: load(name, client=s3))
    return (record or {}).get("owner") or ""


def is_active(record: dict | None) -> bool:
    """Reports whether a registry record is a provisioned, live space.

    Args:
      record: A record from ``load``, or None. Anything that is not a dict answers False
        rather than raising — this is an authorization predicate, and the only safe direction
        for an unreadable record is closed.

    Returns:
      True if the space exists and is a valid share target.

    Raises:
      None.
    """
    return isinstance(record, dict) and record.get("status") == "active"


def may_receive_share(record: dict | None) -> bool:
    """Reports whether a space may be pushed a table or sent files.

    **``is_active`` alone is not that question, and reading it as though it were is a live
    disclosure.** A space that has been deleted keeps an active status by design — nothing about
    its objects or its database changed — and what ends is its membership: a blank roster and no
    owner. So a former member who remembers the name could push a table or send files into a
    workspace every surface tells them is gone, the objects would land under a prefix nobody
    holds a claim to, and the owner notification would be skipped for want of an owner. Nobody
    would be told at all.

    An owner is therefore the second half of the test, and it is expressed here once rather than
    at each call site, because the two callers are different planes.

    The owner must be a string, for the reason spelled out under ``is_active_member``: these
    predicates are the whole of the decision on planes that never look at the record themselves,
    so a field's type is checked here rather than assumed. A truthy non-string owner is not a
    person anybody could be notified at.

    Args:
      record: A record from ``load``, or None.

    Returns:
      True if the space exists, is live, and still names an owner.

    Raises:
      None.
    """
    if not is_active(record):
        return False
    owner = cast("dict", record).get("owner")
    return isinstance(owner, str) and bool(owner)


def is_active_member(record: dict | None, actor: str) -> bool:
    """Reports whether a space is live and the actor is one of its members.

    "Active" here is the space's provisioning status, not a member's pending/active join
    chip. Access is granted at add time, so a member whose chip still reads pending passes
    this check.

    **The roster has to be a list, and asserting that is half the test.** ``in`` is not one
    operator: against a list it compares whole elements, against a string it matches substrings,
    and against a dict it matches keys. A record whose ``members`` arrived as ``"alice,bob"``
    would therefore authorize ``alice`` and ``bob`` and equally ``ali``, ``lic`` and ``ce,b`` —
    a predicate that reads as a membership test behaving as a substring match. Nothing writes a
    roster that shape today, the shared-spaces plane being the only writer and always writing a
    list. This is the read side, and every plane on it hands a loaded record straight to this
    function and never reads the roster itself, so the type is checked where the decision is made
    rather than trusted from a JSON document one plane away. The planes are deliberately not
    listed here: ``lambdas/test_space_reachability_predicates.py`` derives that population from
    the tree for the reason its own docstring gives, and a count written down beside the code
    goes stale the week a plane is added.

    The shared-space layer's own authorizer is not covered from here. It reads the same roster
    with the same operator, in its own module.

    The status is tested before the roster is read, so a record that is not a dict at all
    answers False rather than raising, as it does through ``is_active``.

    Args:
      record: A record from ``load``, or None.
      actor: The verified username to look for.

    Returns:
      True if the space is active and its roster is a list naming the actor.

    Raises:
      None.
    """
    if not is_active(record):
        return False
    members = cast("dict", record).get("members")
    return isinstance(members, list) and actor in members
