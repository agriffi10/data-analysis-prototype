---
type: Spec
id: SPEC-267
title: "The API Assumes the Carrier Role from a Sealed Context"
description: "Would have given the API a third credential plane, declared per route, that unseals the forwarded identity context and assumes the carrier role with it; cancelled before it was built, and the design moved into the transition plan."
spec_status: Cancelled
depends_on: [SPEC-266]
arc: carrier
arc_order: 2
---

**Dependency notes:** SPEC-266 (the carrier role, the sealing key and the API's environment).
**Transition context:** `docs/transition_plan.md`. This spec was cancelled while still Draft; nothing
was built.

## Why this spec was cancelled

**User decision, 2026-11-17: work meant for after the move into the client environment gets no spec;
it lives in [`docs/transition_plan.md`](../transition_plan.md).** This repeats the rule of 2026-09-01
(SPEC-204's tombstone): a spec that can only be built or proved in another environment is a spec
whose claims drift with no test to catch them. It is inert until a route declares the carrier plane, and no route can usefully declare it until the client's Identity Center, the consumers and the server's exchange exist, so nothing here could prove it.

**The design was not discarded. It is now [`transition_plan.md` §4.7, *The API's half* and *The
interface between the server and the API*](../transition_plan.md#the-apis-half)**, and Phase 5's API
item points there. What moved: the third plane that never falls back, the `AssumeRole` call's
parameters, the cache keyed on the sealed value and the verified `sub` with eviction on insert, the
whole answer table (none of it 401) and the browser's sentences, the decision to scrub the context
from stacks explicitly, the build-time botocore check for `ProvidedContexts`, and the end-to-end
check that gates the first carrier route (Phase 5's verification).

## What validating it against the built code found, 2026-11-17

Recorded because the corrections are the reason a client-environment design should not sit in
`docs/specs/` unbuilt.

- **Its seams exist as described.** `Route.plane` is `Literal["user", "api"]`
  (`lambdas/api/apicommon/contract.py`); `for_request` takes no headers today and the identity layer
  forbids a request-scoped global; the verifier requires only `exp`, `iss` and `aud`
  (`cpcommon/auth.py`), so `sub` must be checked on a context route; `aws_error_code` and the
  Dockerfile's build-time botocore check both exist.
- **The cache's eviction would be new.** Today's cache is keyed on the whole tag set and evicts
  nothing on insert.
- **One claim was false.** The spec mapped an `ApiUnavailableError` to the existing 503. No such class
  exists: the 503 is made through `SERVER_FAULT_CODE` and `server_fault`
  (`lambdas/api/apicommon/errors.py`). §4.7 says so.
