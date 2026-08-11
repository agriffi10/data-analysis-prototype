"""Per-user membership slots stored in Cognito custom attributes.

Each user holds a bounded number of membership attribute slots, and a slot's value is the space
name it grants — the IAM membership tag the portal role is scoped to. This module owns
assigning and clearing those slots. Reading the user doubles as the user pool existence check.
All operations are idempotent and replay-safe.
"""

from cpcommon import clients, observability
from cpcommon import config as cpconfig
from registry import ProvisioningError

import config


def normalize_members(raw: list | None, owner: str) -> list[str]:
    """Trims, lowercases and de-duplicates requested usernames, dropping the owner.

    The owner is implicitly a member and is never added or removed. Defensive — the browser
    already cleans the list, but the pipeline is the real authority.

    Args:
      raw: The requested member names, or None.
      owner: The space's owner, excluded from the result.

    Returns:
      The cleaned member names, in request order.

    Raises:
      None.
    """
    seen = set()
    out = []
    for member in raw or []:
        if not isinstance(member, str):
            continue
        name = member.strip().lower()
        if not name or name == owner or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _slot_attr(k: int) -> str:
    """Names the Cognito custom attribute for one membership slot.

    Args:
      k: The one-based slot index.

    Returns:
      The attribute name.

    Raises:
      None.
    """
    return f"custom:shared_space_{k}"


def assign_or_find_slot(username: str, name: str) -> int:
    """Returns the slot index holding a space for a user, assigning a free one if needed.

    Idempotent on re-run: an existing assignment is returned as-is. A stable reason token is
    recorded alongside the user-facing failure when the cap is reached, because how often people
    hit the cap is a product question and a notification cannot be counted.

    Args:
      username: The member to assign.
      name: The space name the slot grants.

    Returns:
      The one-based slot index.

    Raises:
      ProvisioningError: When the user already holds the maximum number of spaces.
      UserNotFoundException: When the user does not exist in the pool.
    """
    cognito = clients.cognito()
    user = cognito.admin_get_user(UserPoolId=cpconfig.USER_POOL_ID, Username=username)
    attrs = {a["Name"]: a.get("Value", "") for a in user.get("UserAttributes", [])}
    free = None
    for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1):
        value = attrs.get(_slot_attr(k), "")
        if value == name:
            return k
        if not value and free is None:
            free = k
    occupied = sum(1 for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1) if attrs.get(_slot_attr(k), ""))
    if free is None:
        observability.error(
            "membership slots exhausted",
            space=name,
            member=username,
            slots_used=occupied,
            slots_cap=config.MAX_SHARED_MEMBERSHIPS,
            reason="membership-limit-reached",
        )
        raise ProvisioningError("membership limit reached")
    observability.info(
        "membership slot assigned",
        space=name,
        member=username,
        slot=free,
        slots_used=occupied + 1,
        slots_cap=config.MAX_SHARED_MEMBERSHIPS,
        store="cognito",
    )
    cognito.admin_update_user_attributes(
        UserPoolId=cpconfig.USER_POOL_ID,
        Username=username,
        UserAttributes=[{"Name": _slot_attr(free), "Value": name}],
    )
    return free


def clear_slot(username: str, name: str) -> None:
    """Clears the membership slot holding a space for a user.

    Sets the slot empty, which the assigner treats as free. Idempotent: a missing slot or a
    user absent from the pool is a no-op.

    Args:
      username: The member to clear.
      name: The space name whose slot should be cleared.

    Returns:
      None.

    Raises:
      ClientError: On any Cognito fault other than the user not existing.
    """
    cognito = clients.cognito()
    try:
        user = cognito.admin_get_user(UserPoolId=cpconfig.USER_POOL_ID, Username=username)
    except cognito.exceptions.UserNotFoundException:
        return
    attrs = {a["Name"]: a.get("Value", "") for a in user.get("UserAttributes", [])}
    for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1):
        if attrs.get(_slot_attr(k)) == name:
            cognito.admin_update_user_attributes(
                UserPoolId=cpconfig.USER_POOL_ID,
                Username=username,
                UserAttributes=[{"Name": _slot_attr(k), "Value": ""}],
            )
            return
