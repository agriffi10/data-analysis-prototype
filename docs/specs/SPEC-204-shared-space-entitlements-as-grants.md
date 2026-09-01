# Spec: Shared-Space Entitlements as Grants — the Projection that Replaces the Tag

**ID:** SPEC-204
**Status:** Cancelled
**Last Updated:** 2026-09-01
**Depends On:** SPEC-203 (the per-user membership index, the interim tag plane this spec eventually retires, and the index staleness residual FR-005's sweep closes), SPEC-196 (the tag set being replaced), SPEC-051/052/053/054/055 (the shared-space control plane, its registry, its verbs and its FIFO queue), SPEC-073 (acknowledge is display-only — access is granted at add time), SPEC-075 (the roster fan-out, and why its best-effort posture does **not** transfer here), SPEC-125 (`shared-space-common`, the domain layer), SPEC-151 (a partial teardown never frees the name — the ordering rule this spec extends), SPEC-152 (every plane notifies on a pre-verb failure), SPEC-157 (FIFO orders delivery, not executions), SPEC-107/156 (`cpcommon`, and the one-implementation rule), SPEC-106 (`toUserMessage`), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

**Transition context:** `transition_plan.md` §3.4, §3.9 and Phase 5. This spec was the work those
sections named and no spec owned; that work is now §3.11 of the plan itself.

## Why this spec was cancelled

**User decision, 2026-09-01: work that can only be done in the successor account belongs in
[`docs/transition_plan.md`](../transition_plan.md), not in a spec.** This spec could not be built or
tested here — it needs the S3 Access Grants instance, the Identity Center association and the
identity-enhanced session, none of which exist in the current account — and a spec that cannot be
built is a spec whose claims drift with no test to catch them. It had already begun to: it was last
revised on 2026-08-28, and SPEC-203 and SPEC-205 both completed on 2026-08-31.

**The design was not discarded. It is now
[`transition_plan.md` §3.11](../transition_plan.md#311-shared-space-entitlements--the-projection-that-replaces-the-tag)**,
and Phase 5's shared-space bullet points there. Everything load-bearing moved: the entitlement pair
and its ordering, the derived member permission set, why shared spaces force the literal grant form,
principal resolution and the requirement it places on Phase 0, the six triggers, the sweep and its
ETag re-read, idempotency in both directions, the failure semantics, the grant budget, and the
cutover ordering whose two failure directions are the reason any of this was written down.

## What validating it against the built code found, 2026-09-01

Four checks against the current account, recorded because the corrections are the reason a
successor-environment design should not sit in `docs/specs/` unbuilt.

- **The privilege-escalation finding is exactly right.** `shared-space-common/config.py` carries the
  two permission lists as quoted, and `portal-role-shared-space.json.tftpl` grants ten Glue actions
  with **no `glue:DeleteDatabase` and no `glue:UpdateDatabase`** — in either template that names Glue
  at all. A member genuinely cannot drop or alter a shared space's catalog today, and the reason is
  that omission rather than the Lake Formation grant, which does carry `DROP` and `ALTER`.
- **The cutover cliff is real and is now guarded on its current-account half.**
  `create_space.py` grants Database and Table permissions to `config.PORTAL_ROLE_ARN` per space, and
  the tag expansion in that template is the only thing narrowing them.
  `lambdas/test_shared_space_isolation_coupling.py` fails when either half moves without the other.
- **FR-011's delete semantics were wrong as built.** It said `delete_shared_prefix` and
  `drop_database` "stop being reachable on the `delete` route" and that `TeardownIncompleteError`
  does not apply. `delete_space.py` branches on `reg.is_destroyable(fresh)` and, on that branch,
  still calls both plus `revoke_portal_role` and `reg.delete`; its own docstring documents
  `TeardownIncompleteError` as reachable there. The destroying route lives in `delete` as well as in
  `forget`. §3.11 carries the corrected version.
- **FR-004's enumeration guard already exists.** The six triggers are exactly the six verbs that
  write the SPEC-203 membership index, and `lambdas/test_membership_index.py` already fails when a
  seventh membership-moving verb appears without one.

One naming detail worth carrying: `is_active_member` lives in `cpcommon.registry`, not in the
shared-space layer's own `registry.py`, and this spec referred to it as `registry.is_active_member`
throughout.
