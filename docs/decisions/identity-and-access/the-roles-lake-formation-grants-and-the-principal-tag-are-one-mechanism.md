---
type: Decision
title: "The role's Lake Formation grants and the principal tag are ONE mechanism (2026-09-01)"
description: "Shared-space isolation is the intersection of the role-level Lake Formation grant and the tag-scoped Glue ARNs, retired together or not at all; no portal-role template may gain `glue:DeleteDatabase` or `glue:UpdateDatabase`."
---

**Isolation between shared spaces is the intersection of a grant in Python and a condition in HCL,
and each half reads as complete on its own.** `shared-space-create` grants Lake Formation `Database`
and `Table` permissions to `config.PORTAL_ROLE_ARN` — the **shared** portal role — once per space,
naming no member. Every portal user assumes that role, so that grant alone entitles everyone to
everything. What narrows it lives in `portal-role-shared-space.json.tftpl`, where every Glue database
and table ARN is scoped by `$${aws:PrincipalTag/shared_space_k}`, so the ARNs resolve only to the
spaces the caller's session tags name.

**Neither artefact mentions the other, and they are two trees apart.** A reader standing in either
one sees a complete-looking mechanism. That is why this is a register entry and a test rather than a
comment: `lambdas/test_shared_space_isolation_coupling.py` fails when create stops granting to the
portal role, when a Glue resource in that statement loses its tag scoping, or when any portal-role
template gains `glue:DeleteDatabase` or `glue:UpdateDatabase`.

**The two failure directions, which matter because the edit looks like housekeeping.** Retire the
principal tags and leave the role-level grants: every portal user holds catalog access to every
shared space. Revoke the grants first: every member is locked out. The ordering that avoids both is
transition work — `transition_plan.md` §3.11 — and the trigger for the union is the **policy
rewrite**, not the tags going quiet: if tags simply stop being stamped and the statement is
untouched, the ARNs resolve to nothing and the outcome is a lockout.

**A third fact falls out of the same intersection, and it is a live security property rather than a
transition one.** The Lake Formation grant carries `ALTER` and `DROP` on the Database. The role
cannot use them because **no** portal-role template grants `glue:DeleteDatabase` or
`glue:UpdateDatabase` — the shared-space template names ten Glue actions and the analytics one
eleven, and neither names either of those two. So a member cannot destroy a shared space's catalog today, and the reason is an
omission in IAM rather than anything in the grant. **Adding either action is not a widening; it is
the removal of the guard**, and it needs no other change to become reachable by any member of any
space. The same reasoning is why a future per-member grant must be the **intersection** — Database:
`DESCRIBE`, `CREATE_TABLE` — and not a copy of the role's constants.

## History

### 2026-09-01

- **Settled:** entered the register.
