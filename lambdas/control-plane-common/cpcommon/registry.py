"""Read-only access to the shared-spaces registry.

The registry is one S3 control object per space under ``shared-spaces/`` in the analytics
admin bucket, owned by the shared-spaces control plane. Every other control-plane verb only
ever reads it — to authorize that the actor is an active member of a space, and to confirm
a share target exists.
"""

import json
from typing import cast

from . import clients, config


def load(name: str) -> dict | None:
    """Reads one shared space's registry record from the admin bucket.

    Args:
      name: The shared space name.

    Returns:
      The record, or None if no such space is registered.

    Raises:
      ClientError: On any S3 failure other than a missing key.
      ValueError: If the stored record is not valid JSON.
    """
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.ADMIN_BUCKET, Key=f"shared-spaces/{name}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return cast("dict", json.loads(obj["Body"].read()))


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


def is_active_member(record: dict | None, actor: str) -> bool:
    """Reports whether a space is live and the actor is one of its members.

    "Active" here is the space's provisioning status, not a member's pending/active join
    chip. Access is granted at add time, so a member whose chip still reads pending passes
    this check.

    Args:
      record: A record from ``load``, or None.
      actor: The verified username to look for.

    Returns:
      True if the space is active and lists the actor.

    Raises:
      None.
    """
    return is_active(record) and actor in ((record or {}).get("members") or [])
