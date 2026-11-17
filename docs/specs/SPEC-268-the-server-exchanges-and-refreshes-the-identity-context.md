---
type: Spec
id: SPEC-268
title: "The Server Exchanges and Refreshes the Identity Context"
description: "Would have had the Next.js server exchange the user's Cognito ID token for an Identity Center identity context at sign-in, keep it fresh, seal it to the user and forward it to the API; cancelled before it was built, and the design moved into the transition plan."
spec_status: Cancelled
depends_on: [SPEC-257, SPEC-262, SPEC-266, SPEC-267]
---

**Dependency notes:** SPEC-257 (the session item and its compare-and-set refresh), SPEC-262 (the browser signs in through the server), SPEC-266 and SPEC-267 (both cancelled with it).
**Transition context:** `docs/transition_plan.md`. This spec was cancelled while still Draft; nothing
was built.

## Why this spec was cancelled

**User decision, 2026-11-17: work meant for after the move into the client environment gets no spec;
it lives in [`docs/transition_plan.md`](../transition_plan.md).** This repeats the rule of 2026-09-01
(SPEC-204's tombstone): a spec that can only be built or proved in another environment is a spec
whose claims drift with no test to catch them. Its own Phase 0 gate, G11 (the cross-account exchange against the client's organization instance), can only run in the client environment, and the spec said it would merge inert and stay off until G11 passed there.

**The design was not discarded. It is now [`transition_plan.md` §4.7, *The server's
half*](../transition_plan.md#the-servers-half)**, with the header contract in *The interface between
the server and the API*, the server's three variables and the inert state in §4.4, and the owed live
checks in Phase 5's verification. What moved: the exchange's mechanics (presented once,
`maxAttempts: 1`, the deadlines, the scope check), the seal, the refusals-and-faults table, the
identity's four states and the one transition function, the separate identity write under the shared
`version`, the retry claim, the refresh-fault and forced-refresh rules, the dependencies and the
logging rule. **Andrew's decision of 2026-11-16, that a refused Identity Center refresh leaves the
context absent until the next sign-in, is recorded in §4.7 with its reasons**, and the plan's
"open" markers for it in Phase 0, Phase 5 and §8, and the admin request list's "still to be
designed", are rewritten.

## What validating it against the built code found, 2026-11-17

Recorded because the corrections are the reason a client-environment design should not sit in
`docs/specs/` unbuilt.

- **The session store's rules it built on hold.** `REFRESH_MARGIN_SECONDS = 300`
  (`apps/portal/src/server/session/session.ts`); the store's replace condition is
  `attribute_exists(#pk) AND #version = :expectedVersion` and writes only the token fields
  (`store.ts`); only `invalid_grant` ends a session, and any other provider failure answers
  `unavailable`; the pass-through's request-header allow-list is exactly `content-type`, `accept`
  and `x-request-id` (`forward.ts`); the token call's deadline is 5 seconds (`oidc.ts`).
- **The task role's KMS statement holds**: it works only via DynamoDB and only for the session table
  (`infra/modules/spa/policies/task-session-policy.json.tftpl`).
- **One premise was wrong, in the spec and in the plan alike.** Both said the browser answers a 401
  "with one forced refresh and then a sign-out". `apps/portal/src/lib/apiClient.ts` calls the 401
  handler once and returns `SessionExpired`; the handler in `AuthProvider.tsx` re-reads the session
  and signs out locally only if no session is found. The conclusion, never 401 for an identity
  reason, still holds; the consequence is mislabelled copy for a signed-in user, not a sign-out. §4.7
  is corrected at both sites.
- **The narrowing it said must precede the security review exists**: SPEC-270 (Draft) narrows the
  session table's key to the roles that use it, which covers the Identity Center refresh token too.
