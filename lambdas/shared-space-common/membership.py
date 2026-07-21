"""Per-user membership slots stored in Cognito custom attributes.

Each user holds up to ``MAX_SHARED_MEMBERSHIPS`` ``custom:shared_space_k`` attribute
slots; the slot's value is the space name it grants (the IAM membership tag the
portal role is scoped to). This module owns assigning and clearing those slots —
``admin_get_user`` doubles as the User-Pool existence check (unknown user ->
UserNotFoundException). All operations are idempotent / replay-safe.
"""

from cpcommon import config as cpconfig

import config
from cpcommon import clients
from registry import ProvisioningError


def normalize_members(raw: list | None, owner: str) -> list[str]:
    """Trim/lowercase/de-dupe the requested usernames and drop the owner.

    The owner is implicitly a member and is never added or removed. Defensive — the
    browser already cleans the list, but the pipeline is the real authority.
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
    return f"custom:shared_space_{k}"


def assign_or_find_slot(username: str, name: str) -> int:
    """Return the slot index holding ``name`` for ``username``, assigning one if needed.

    Idempotent on re-run (an existing assignment is returned as-is).

    Raises:
        ProvisioningError: the user already holds MAX_SHARED_MEMBERSHIPS spaces.
        cognito.exceptions.UserNotFoundException: the user does not exist.
    """
    cognito = clients.cognito()
    user = cognito.admin_get_user(UserPoolId=cpconfig.USER_POOL_ID, Username=username)
    attrs = {a["Name"]: a.get("Value", "") for a in user.get("UserAttributes", [])}
    free = None
    for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1):
        value = attrs.get(_slot_attr(k), "")
        if value == name:
            return k  # already assigned (replay-safe)
        if not value and free is None:
            free = k
    if free is None:
        raise ProvisioningError("membership limit reached")
    cognito.admin_update_user_attributes(
        UserPoolId=cpconfig.USER_POOL_ID,
        Username=username,
        UserAttributes=[{"Name": _slot_attr(free), "Value": name}],
    )
    return free


def clear_slot(username: str, name: str) -> None:
    """Clear the membership slot holding ``name`` for ``username``.

    Sets the slot empty, which assign_or_find_slot treats as free. Idempotent — a
    missing slot or a pool-absent user is a no-op.
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
