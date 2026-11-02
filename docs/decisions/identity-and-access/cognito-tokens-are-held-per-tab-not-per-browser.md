---
type: Decision
title: "Cognito tokens are held per TAB, not per browser (2026-08-27)"
description: "Cognito tokens live in the tab-scoped store, installed after `Amplify.configure` and never before, so there is no stay-signed-in and a second tab or a link opened in a new tab signs in again."
---

Amplify's default token store is `localStorage`, so an ID token survived a browser restart and was
readable by anything running on the origin. `configureAmplify` now hands the provider the
tab-scoped store instead.

**The cost is deliberate and user-visible**, which is why it is a decision rather than a tidy-up:
there is no "stay signed in" any more, a second tab signs in again rather than inheriting the
first one's session, and a link opened in a new tab lands on the Hosted UI first. Nothing in
`helpContent.ts` promised otherwise, so no guide became untrue — but a later spec adding one must
know this is the behaviour.

**Set AFTER `Amplify.configure`, never before**: the provider resolves the pool it was configured
with, and a store installed on an unconfigured provider is discarded. Both halves are guarded, and
both guards were verified by planting the mistake.

**It touches sign-in, which a warm session cannot exercise.** The offline tests assert which store
the provider is given; they cannot drive a real authorization-code round trip, and Amplify keeps
the OAuth `state` and PKCE verifier in its own store — so the two now live in different stores.
Expected to be fine, not observed. Recorded in `owed.md`, along with the SPEC-192 fresh-sign-in
check this **re-invalidates**.

Requested by Andrew alongside SPEC-197 and shipped as its own commit, so it can be reverted without
the port.

## History

### 2026-08-27

- **Settled:** entered the register.
