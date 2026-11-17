---
type: Spec
id: SPEC-265
title: "The Bridge Pool Signs In Through Entra"
description: "Would have given the successor account a Cognito User Pool federated to Entra ID over SAML, keyed on Entra's object id, with a pre-token trigger that looks the portal username up; cancelled before it was built, and the design moved into the transition plan."
spec_status: Cancelled
depends_on: [SPEC-195, SPEC-203, SPEC-262]
---

**Dependency notes:** SPEC-195 (the API's verifier reads its issuer, audience and username claim from configuration), SPEC-203 (the membership index), SPEC-262 (the Next.js server is the only OIDC client).
**Transition context:** `docs/transition_plan.md`. This spec was cancelled while still Draft; nothing
was built.

## Why this spec was cancelled

**User decision, 2026-11-17: work meant for after the move into the client environment gets no spec;
it lives in [`docs/transition_plan.md`](../transition_plan.md).** This repeats the rule of 2026-09-01
(SPEC-204's tombstone): a spec that can only be built or proved in another environment is a spec
whose claims drift with no test to catch them. The bridge pool exists only in the successor account, and every acceptance criterion that mattered (a federated sign-in, the trigger's claims, the presence test against a SAML provider) needs Entra upstream of it.

**The design was not discarded. It is now [`transition_plan.md` §6.1, *The bridge pool as
designed*](../transition_plan.md#the-bridge-pool-as-designed)**, and Phase 1's [B] list points there.
What moved: the identity index (its key, its entry shape, who writes it and its fence), how the
pre-token trigger validates a subject and the two claims it emits, its two ways of failing, its IAM,
timeout and warm-up, the `entra_federation` flag and the literal-branch shape the guard test reads,
the SAML provider's settings, the provider reference and the development client's removal, unwiring
rather than deleting the old triggers, the deploy-role grant, and the three things that must land
before the flag is set anywhere. The role guardrail's wider population (any `cognito-idp:` action,
the identity index, the trigger's code) is in §6.1's guardrail paragraph. Andrew's two decisions of
2026-11-16 (SAML, and the lookup as a Pre-Token-Generation trigger) are recorded in place in §6.1,
Phase 0, Phase 1 and §8.

## What validating it against the built code found, 2026-11-17

Recorded because the corrections are the reason a client-environment design should not sit in
`docs/specs/` unbuilt.

- **The guardrail's premises hold.** The shared-spaces plane's `CognitoMembershipAttributes`
  statement grants `AdminUpdateUserAttributes`, `AdminGetUser` and `ListUsers` on `userpool/*`
  (`infra/planes/shared-spaces/execution.json.tftpl`). Exactly five plane templates name `{admin}/*`,
  and all five are Denies.
- **The fail-closed premise holds.** The server refuses a sign-in whose ID token lacks the username
  claim (`apps/portal/src/server/session/handlers.ts`), and `active()` treats a refreshed token
  without it as an ended session (`session.ts`).
- **One claim was wrong.** The spec said `user_pool_tier = "ESSENTIALS"` "is what the pool has
  today". No tier is declared anywhere under `infra/modules/auth/`, so the live tier is unverified;
  §6.1 now says to read it before declaring one.
- **It exposed stale text in the plan**, now corrected: the plan said three app clients carry
  `["COGNITO"]` and the API accepts three audiences, where `infra/modules/auth/cognito.tf` declares
  two (`server` and `dev`) since SPEC-262 retired the public client.
