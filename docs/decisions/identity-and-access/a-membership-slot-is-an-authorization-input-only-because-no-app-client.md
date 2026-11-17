---
type: Decision
title: "A membership slot is an authorization input only because no app client can write it (SPEC-248)"
description: "Every app client declares `write_attributes = [\"email\"]` and `read_attributes = local.client_read_attributes` — both lists, set together, on every client, because an UNSET list was measured WRITABLE: a user holding a client secret wrote their own `custom:shared_space_k` by SRP and `UpdateUserAttributes`, and the API stamps whatever the ID token carries. The read list must name EVERY slot: one it omits drops that claim, which presents as the propagation delay. `SignUp` and managed-login sign-up are NOT measured against the write list, and this account keeps both until it is decommissioned. `test_every_app_client_declares_both_attribute_lists` sweeps every client and refuses `.tofu`, `.tf.json`, other client types and `ignore_changes`; nothing in the repo sees a client made outside it, so `list-user-pool-clients` is the check."
---

**The slot claims are the session's `shared_space_k` tags** under the `claims` membership source,
which every deployed environment runs, so a slot is an entitlement: one naming a space reaches its
objects and catalog, one naming a user reaches that user's catalog through `SharedSpaceGlue`. The
orchestrator role writes slots with `AdminUpdateUserAttributes`; the question this settles is
whether anyone else can.

**Measured, not assumed.** AWS's developer guide says a new client may read and write every
attribute; its API reference says an unset list means standard attributes only. Neither app client
set either list. A probe through the dev client — SRP sign-in with the client's secret, then
`UpdateUserAttributes` setting an empty slot to the empty string — **succeeded** before the change.
So any user who could read a client secret (every developer, through the dev client's parameter)
could write any space's or any user's name into their own account. After both lists were applied
the same call raised `NotAuthorizedException: A client attempted to write unauthorized attribute`.
The tokens the portal server holds come from the authorization-code flow with `openid email
profile` and carry no `aws.cognito.signin.user.admin`, so the server's own tokens never could.

**Both lists, set together.** Setting only the write list could send the read list to the default
one document says excludes custom attributes, removing every space from every token; a read list
that omits one slot drops that slot's claim, which looks like the documented propagation delay and
not like a fault. So the read list is one local over the pool schema's own `range`, and the test
pins its whole expression, not just its bounds.

**What it does not cover.** `SignUp` is documented to obey the write list and is not measured; it
needs a secret hash on both clients. Sign-up through Managed Login needs no secret, and whether a
crafted form carries a `custom:` attribute through it is unmeasured. The target environment has no
self-sign-up (Andrew, 2026-11-17), so the current account keeps that door until it is
decommissioned. A client created outside the infrastructure keeps the default lists and no repo
test can see it: `aws cognito-idp list-user-pool-clients` must return only the declared clients.

**Do NOT:**
- Drop either list, or let a new client omit them — the sweep fails by the client's name.
- Remove `ALLOW_USER_SRP_AUTH` as a substitute: it closes only `UpdateUserAttributes`, which the
  write list already closes, does nothing for sign-up, and Managed Login has not been measured
  without it.
- Read this as covering the successor pool: under federation every mapped attribute must be
  writable by the client, so there the guardrail is that no client allows the admin scope or an API
  sign-in flow (`docs/transition_plan.md` §6.1).

## History

### 2026-11-17

- **Settled:** entered the register with SPEC-248's FR-001, measured before and after the apply.
