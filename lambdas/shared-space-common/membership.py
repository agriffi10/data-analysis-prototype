"""Per-user membership slots stored in Cognito custom attributes.

Each user holds a bounded number of membership attribute slots, and a slot's value is the space
name it grants — the IAM membership tag the portal role is scoped to. This module owns
assigning and clearing those slots. Reading the user doubles as the user pool existence check.
All operations are idempotent and replay-safe.
"""

import cache
import registry
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


def roster(registry) -> list:
    """The space's member list, or empty when the record does not carry one as a list.

    **``in`` is three operators and only one of them is a membership test.** Against a list it
    compares whole elements; against a string it matches substrings, so a roster that arrived as
    ``"alice,bob"`` answers True for ``ali`` and ``lic``; against a dict it matches keys. Every
    roster an AUTHORIZATION decision is made from comes through here, so the type is asserted
    once. Those three sites do not share a module — two are in the authorizer and the third is
    the forget verb, which the authorizer returns early for — so written at each site instead the
    copies drift, and each drift admits somebody silently.

    The verbs read a roster again once they are authorized, and those reads are deliberately not
    counted by that sentence: they decide what to apply rather than who may ask. Claiming them
    would make the sentence false without converting them.

    It lives beside ``normalize_members`` because that is the other place a roster's shape is
    decided, and splitting the two is how they come to disagree.

    Nothing writes a roster that shape today — this plane is the registry's only writer and
    always writes a list. The check is here because a membership test that reads as one and
    behaves as a prefix match is indistinguishable from a correct one at the call site.

    Args:
      registry: The loaded registry record, or None. Anything that is not a dict carrying a list
        answers empty rather than raising, which is the only safe direction for a roster an
        authorization decision is about to be made from.

    Returns:
      The member names, or an empty list.

    Raises:
      None.
    """
    members = registry.get("members") if isinstance(registry, dict) else None
    return members if isinstance(members, list) else []


def roster_is_readable(registry) -> bool:
    '''Whether the record carries a roster a membership question may be decided from.

    **``roster`` collapses an unreadable roster into an empty one, and that has a POLARITY.**
    Where the question is "refuse a non-member" — leaving, acknowledging, naming a transfer
    target — an empty roster refuses everybody and the collapse fails closed. Where the question
    is "refuse a MEMBER", which is how the forget verb protects a live space, an empty roster
    refuses nobody and the very same collapse fails open. One helper cannot serve both
    directions, and a caller reaching for the convenient one gets the wrong answer silently.

    So a site whose refusal is keyed on the actor BEING a member asks this first, and refuses
    when the roster cannot be read at all. Not knowing whether somebody is a member is not the
    same as knowing that they are not.

    Args:
      registry: The loaded registry record, or None.

    Returns:
      True when the record is a dict whose ``members`` is a list.

    Raises:
      None.
    '''
    return isinstance(registry, dict) and isinstance(registry.get("members"), list)


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
    user = cognito.admin_get_user(UserPoolId=cpconfig.require("COGNITO_USER_POOL_ID"), Username=username)
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
        UserPoolId=cpconfig.require("COGNITO_USER_POOL_ID"),
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
        user = cognito.admin_get_user(UserPoolId=cpconfig.require("COGNITO_USER_POOL_ID"), Username=username)
    except cognito.exceptions.UserNotFoundException:
        return
    attrs = {a["Name"]: a.get("Value", "") for a in user.get("UserAttributes", [])}
    for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1):
        if attrs.get(_slot_attr(k)) == name:
            cognito.admin_update_user_attributes(
                UserPoolId=cpconfig.require("COGNITO_USER_POOL_ID"),
                Username=username,
                UserAttributes=[{"Name": _slot_attr(k), "Value": ""}],
            )
            return



def reinstate_owner(cleared: list[str], name: str) -> None:
    """Gives a space's owner back the slot and card a refused removal cleared from them.

    A leave and a remove clear each name's slot and card BEFORE the roster write, so a fault
    part way leaves the name still listed and a retry repeats the idempotent clears. Both verbs
    refuse a removal naming the current owner before clearing anything, so this runs only when a
    transfer to one of the names committed in the moment between that check and the write. The
    owner is the one name nothing else can re-issue a slot for, because the add normalises an
    owner out; every other name the run cleared is left listed without one — a denial, which the
    owner mends by removing and re-adding them, where re-granting them could hand a slot to
    somebody a concurrent removal had just taken off the roster.

    **The slot and the card are written first and confirmed after**, and both are taken back
    unless the record read after them still names this person as owner, lists them, and is
    neither claimed by a delete nor emptied. A read before the grant cannot be trusted with it:
    a delete could empty the space between that read and the grant, leaving a slot on a roster
    naming nobody. Read after, it holds because every writer that ends someone's place on a
    roster revokes AFTER a write that read can see. A delete and a forget claim the record before
    they revoke anyone, so their claim is either seen, or their revocation lands after this
    grant. A leave and a remove revoke again after their own commit, so their commit is either
    seen, or their second revocation lands after this grant — which is the case a first pass
    alone lost, when a removal cleared this person early and committed after the space had gone
    to them and back.

    Args:
      cleared: The names whose slot and card this run cleared.
      name: The space name.

    Returns:
      None.

    Raises:
      ProvisioningError: When the owner already holds the maximum number of spaces again.
      ClientError: On an S3 or Cognito fault. Raised rather than logged, so the requester reads
        the generic failure — the owner's access was not given back — instead of the sentence
        about the space changing hands.
    """
    record = registry.load(name) or {}
    owner = record.get("owner")
    if not isinstance(owner, str) or owner not in cleared:
        return
    listed = roster(record)
    assign_or_find_slot(owner, name)
    try:
        cache.write_owner_projection(
            owner,
            name,
            listed,
            registry.effective_acknowledged(record) if listed else [],
            record.get("createdAt"),
        )
        after = registry.load(name) or {}
    except Exception:
        clear_slot(owner, name)
        cache.remove_entry(owner, name)
        raise
    if (
        after.get("owner") != owner
        or owner not in roster(after)
        or after.get("status") == "deleting"
        or after.get("emptiedAt")
    ):
        clear_slot(owner, name)
        cache.remove_entry(owner, name)
