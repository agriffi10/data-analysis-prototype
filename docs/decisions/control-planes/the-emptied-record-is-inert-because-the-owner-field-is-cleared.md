---
type: Decision
title: "The emptied record is inert because the `owner` FIELD is cleared (SPEC-205)"
description: "An emptied space is inert because the `owner` field is cleared, or for `add_members` and `remove_members` because `emptiedAt` refuses first; no authorization path reads `previousOwner`, and `revoke_portal_role` is not called on the emptying route."
---

`shared-space-common/auth.py` gates every owner-only action on `actor != registry.get("owner")` — the
field, never the roster. An `owner` retained through a delete would leave the original owner able to
`add-members` on the emptied space and revive it, with the previous cohort's files intact, in one call
and with no confirmation. Clearing it refuses every owner-only action (`actor != None`) and every
member-only action (the roster is empty). `previousOwner` survives for an operator and **no
authorization path reads it**.

**The inert-state test is driven as the ORIGINAL OWNER.** As a stranger it passes over the defect,
because the field `authorize` reads is exactly the one a delete clears.

> **Superseded in part by SPEC-217, for `add_members` and `remove_members` only.** Those two left
> `OWNER_ONLY_ACTIONS` for `auth.member_refusal`, which refuses an emptied record on `emptiedAt`
> **before any actor is consulted** — so for them the inertness no longer rests on the cleared
> `owner` field, and an assertion driven as the original owner would pass as a stranger too. The
> test keeps its discrimination by **pairing** the emptied assertion with a live-record one: the
> original owner allowed, a non-owner refused by code. `delete`, `leave` and `acknowledge_membership`
> are unchanged and still read the cleared field. Full entry:
> [*The operator door widens to member management, and that is a threat-model decision
> (SPEC-217)*](the-operator-door-widens-to-member-management-and-that-is-a-threat.md).

Three further doors are closed, and each was found separately: `_resolve_reserve_collision`'s
failed-retry overwrite additionally requires `not everActive`, or a failed *delete* is re-provisioned
into a revived space with the roster reset to its owner alone; `save_members` refuses an addition to a
record carrying `emptiedAt`, which covers the one record where the owner is back but the members are
gone — a fault after the emptying rewrite restores `owner` so the space stays retryable; and
`cpcommon.registry.is_active` stops being callable outside the module that defines it, because an
emptied space keeps `status: "active"` and the two destination validators used that predicate to
decide whether a space may receive a table or a file send.

**Do NOT call `revoke_portal_role` on the emptying route.** The entitlement design that became `transition_plan.md` §3.11 asked for it and this
supersedes that: with every member's slot cleared the grant reaches no user, and revoking it would
leave a restored workspace's catalog unusable for no benefit.

**The credential window is bounded, accepted, and worse than it used to be — in exactly one place.**
Clearing a Cognito slot ends a membership, but the principal tag is stamped when credentials are
vended, so every removed member keeps live access until their session expires. Under the old
semantics that was harmless: the data was already destroyed. Now it survives, so the window is a
window onto something real. Every browser surface that could reach a retained space derives from the
connections cache, which the delete clears, and both the refresh and the reconcile force a token
re-mint — so the deleter's own window closes within a poll, and a stale `?space=` link falls back
truthfully. **The residual is the query workspace**, which has no active database and takes a fully
qualified `database.table` straight from the editor: a removed member holding a live token can
`SELECT` from, and `DROP TABLE` in, the retained Glue database until it expires. Every other plane
refuses them through `is_active_member`. Recorded rather than fixed, because the fix is the
transition's — an entitlement checked at query time rather than a tag minted an hour earlier — and
because it is the one path by which the thing retention exists to preserve can still be destroyed.

## History

### 2026-08-31

- **Settled:** SPEC-205.
