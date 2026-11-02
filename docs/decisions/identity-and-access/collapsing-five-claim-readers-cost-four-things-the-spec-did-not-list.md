---
type: Decision
title: "Collapsing five claim readers cost four things the spec did not list (SPEC-201)"
description: "Control planes read the actor through one reader, but `notifications_writer`'s `create` arm must stay outside it, as hoisting it refuses every notification; `COGNITO_USER_POOL_ID` is required lazily, on the planes that call `AdminGetUser`."
---

The collapse itself was the easy part — thirteen call sites onto one reader. What it actually cost:

1. **The whole Cognito arm of `cpcommon.auth`, not the two entry points the spec named.** Once
   `verified_username` and the two domain wrappers were gone, `verify_id_token`, `_verify`,
   `_cognito_detail`, `_cognito_config` and the hard-coded claim name had no callers. Leaving
   `_cognito_config` was not the conservative option: it reads `config.USER_POOL_ID`, which this
   change removes from `_REQUIRED_VARS`, so it would have been an `AttributeError` on a path no test
   exercises. `verify_exp` went too — no caller wants a relaxation, so there is now no flag, private
   or public, that turns expiry off.
2. **`COGNITO_USER_POOL_ID` could not follow its twin.** `cpcommon/cognito.py` and
   `shared-space-common/membership.py` read it for `AdminGetUser`, which FR-004 requires to survive.
   It moved out of the fleet-wide `_REQUIRED_VARS` — that set is a contract every plane must satisfy,
   so a variable only three planes set would fail every other plane's guard — to a lazy
   `config.require` at the call site, and stays in Terraform on **shared-spaces, file-send and
   table-share** alone. The trade is real: a lazily-required variable that is missing raises
   **mid-request** rather than at cold start, which is why `test_pool_id_reaches_its_readers.py`
   pins both sets and why the live pass aimed at it deliberately.
3. **What it did NOT reach.** The SPA's `getCurrentUser().username` is the same value but never the
   claim string; `identity-pool.tf`'s principal-tag mapping retires in SPEC-202; and
   `notifications_writer`'s `create` branch never had a token to read.
4. **A correction worth keeping:** `notifications_writer` had not had "its own verification path"
   since SPEC-156 FR-004. `transition_plan.md` §6.1 said it did, and a build session hunting for a
   second `jwt.decode` would not have found one. It was a claim *reader*, which is why the count of
   five still held.

**`notifications_writer`'s branch is the one that must not be simplified.** `trusted_actor` replaces
the reader on the `USER_ACTIONS` arm **only**. The `create` arm is the trusted-producer path —
written by the control-plane execution roles, carrying a body `username` with no actor and no token —
and hoisting the reader above the branch is the obvious tidy that a "one reader, every call site"
sweep pushes toward. It refuses **every notification the fleet produces**, and it does so silently:
the producers notify best-effort, so archives and shares complete and users are simply never told.
Planted during the build, six tests redden.

## History

### 2026-08-18

- **Settled:** SPEC-201.
