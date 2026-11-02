---
type: Spec
id: SPEC-125
title: "Fold `shared-space-common` onto the `cpcommon` layer"
description: "Folds the shared-space Lambdas' duplicated clients, config, ID-token verification, notify and error-code helpers onto the cpcommon layer, so a token-verification fix is made in one place."
spec_status: Completed
depends_on: [SPEC-107, SPEC-062, SPEC-082]
---

**Dependency notes:** SPEC-107 (`cpcommon` layer), SPEC-062 (shared-space verb decomposition), SPEC-082 (registry CAS)
> **Prerequisite refactor, not a feature — ships no user-visible change.** This completes the consolidation SPEC-107 deliberately deferred ("The `shared-space-common` layer… Folding it in is a **follow-up**, not this spec"). SPEC-107 folded `tbcommon`/`tscommon` onto `cpcommon`, and the 2026-07 code-health follow-ups (PRs #234/#235) folded the data-quality verbs' shared bits on too — so `shared-space-common` is now the **last** control-plane layer still carrying its own copy of the JWT-verification / boto-client / notification path.
>
> **Do NOT build this while the deploy pipeline (CI) is disabled.** FR-001 attaches the `cpcommon` layer to 8 production Lambdas, and `cpcommon.config` runs an import-time `_require("ATHENA_WORKGROUP")` at cold start (a var those verbs don't set today) — the exact failure mode as prod break PR #196. That is only truly verified by a real deploy. This spec was filed *because* it can't be safely validated with CI off; it waits for CI to come back.

## Overview

`lambdas/shared-space-common/` re-implements five modules that `cpcommon` already owns: `clients.py` (lazy boto3 factories), the shared **core** of `config.py` (`_require` + the User-Pool/bucket env reads), `auth.py`'s `verified_username` (the Cognito ID-token JWKS verification), `notify.py`'s `emit_notification` (the FIFO notifications send), and `casio.py`'s `error_code` extractor (whose `cpcommon` twin's docstring literally says it "mirrors shared-space-common/casio.error_code"). The security-critical one is `auth` — a JWKS-handling or claim-validation fix has to be made in two places and will eventually be made in one.

`shared-space-common` was left out of SPEC-107 for three real reasons, all still true, none of them "don't bother":

1. **It attaches its own layer, not `cpcommon`.** The 8 shared-space verbs deploy as `layer: true, cpcommon: false` (`deploy-lambdas.yml`), so they can't `from cpcommon import …` until the layer is attached — and attaching it means the `ATHENA_WORKGROUP` cold-start gap above.
2. **It uses a different exception model.** shared-space raises the domain `auth.AuthorizationError` (and `RuntimeError` for CAS exhaustion), where every `cpcommon` consumer raises `TerminalError`/`TransientError`. `verified_username` in particular needs an exception **seam**, not a straight import.
3. **It runs a Standard Step Function with no transient-retry concept.** There is **zero** `TransientError` anywhere in the shared-space verbs; the Standard SFN Catches domain exceptions directly. Nothing breaks, but it means `cpcommon.errors`' transient path is simply unused here.

This spec resolves all three: it plumbs the one missing env var and grows `cpcommon.clients` with the Lake-Formation factory shared-space needs (FR-001), extracts the JWKS-verification primitive with a domain-exception seam so both models survive (FR-003), deletes the duplicated modules and switches the flat imports to package imports (FR-002), and proves behaviour is identical by running the existing shared-space suite with only import-path changes (FR-004). The genuinely shared-space-specific modules — `registry` (the SPEC-082 ETag-CAS writer), `cache`, `membership`, `teardown`, `fakes`, the domain `config` constants, the `casio` CAS retry loop, and the seven lifecycle notification emitters — **stay** in a slimmed `shared-space-common`.

## Scope

### In Scope

- **Attach `cpcommon` to all 8 shared-space verbs** (`validate`, `create`, `add-members`, `remove-members`, `leave`, `delete`, `forget`, `acknowledge-membership`) as `cpcommon` + `shared-space-common` (2 layers), the same shape SPEC-107 gave `tbcommon`/`tscommon`.
- **Plumb `ATHENA_WORKGROUP` into the shared-spaces Lambda env** (a new `infra/modules/shared-spaces` variable wired from the analytics workgroup) so `cpcommon.config`'s import-time `_require` is satisfied at cold start — even though the shared-space verbs never call Athena.
- **Add `lf()` (Lake Formation client) to `cpcommon.clients`** — the one factory `shared-space-common/clients.py` has that `cpcommon` lacks; `cpcommon.clients` takes the union (it already has `athena()`, which shared-space lacks).
- **Extract a reusable JWKS-verify primitive** in `cpcommon.auth` (`verify_id_token(token) -> claims`, raising a new `cpcommon.errors.AuthError`), keep `cpcommon.auth.verified_username` mapping it to `TerminalError` for the tb/ts/dq callers, and reduce `shared-space-common/auth.py::verified_username` to a thin adapter that maps `AuthError → AuthorizationError` with the **same messages it raises today**.
- **Delete the duplicated modules/functions from `shared-space-common`**: `clients.py`, the config **core** (keep the domain `config` constants), `notify.emit_notification`, `casio.error_code`. Its verbs switch from flat imports (`import config`, `import clients`) to package imports (`from cpcommon import config, clients`).
- **CI matrix + deploy-role**: flip the 8 shared-space rows to `cpcommon: true`; verify/grant the deploy role `lambda:GetLayerVersion` on the `cpcommon` layer ARN so it can attach the layer to those functions.

### Out of Scope

- **Any behaviour change.** Every shared-space verb path must behave **identically** before and after; the Standard SFN definitions, the request contract (SPEC-056), the membership-tag model, and the registry/cache shapes are unchanged. A shared-space test whose *assertions* have to change is a spec violation — stop and escalate.
- **`shared-space-common/registry.py`.** It is the ETag-CAS **writer** (`reserve`/`finalize`/`save_members`/`set_status`/`delete`, SPEC-082) with its own `If-None-Match`/`If-Match` semantics — a cohesive domain module, not a copy of `cpcommon.registry`'s read-only `load`/`is_active_member`. It **stays**. (Called out so its absence isn't read as an oversight, per SPEC-107's own exclusion of it.)
- **`cache`, `membership`, `teardown`, `fakes`, the `casio` CAS retry loop, the domain `config` constants (`SCHEMA_VERSION`/`OWNER_ONLY_ACTIONS`/`VALID_ACTIONS`/`PORTAL_ROLE_ARN`), and the seven SPEC-061 lifecycle notification emitters.** Domain surface — stays in the slimmed `shared-space-common`.
- **Adopting `cpcommon.events`** (task-shape validation) in the shared-space verbs — they validate inline, and switching them would be a behaviour change (same stance SPEC-107 took for table-share).
- **Switching shared-space from `AuthorizationError` to `TerminalError`, or introducing `TransientError`/retry into its Standard SFN.** The exception model stays; only the JWKS *logic* is shared.
- New env vars beyond `ATHENA_WORKGROUP`, new resources, new SPA change, a DLQ alarm.

---

## Functional Requirements

### FR-001: The 8 shared-space verbs attach `cpcommon` without a cold-start regression

#### Description

Make `cpcommon` importable from the shared-space verbs: satisfy its import-time env contract, grow its client union with `lf()`, and attach it in CI — all validated by a real deploy before any shared-space code imports it.

#### Acceptance Criteria:

- [ ] `infra/modules/shared-spaces` gains an `athena_workgroup` variable, wired from root `locals`/the analytics workgroup name, and every shared-space Lambda's `environment.variables` sets `ATHENA_WORKGROUP` to it.
- [ ] Every var `cpcommon.config` `_require()`s — `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `ADMIN_BUCKET`, `USER_SPACE_BUCKET`, `SHARED_SPACE_BUCKET`, `ATHENA_WORKGROUP` — is present in **every** shared-space verb's env (the first five already are; `ATHENA_WORKGROUP` is the only gap). A cold start of each of the 8 verbs succeeds after the layer is attached.
- [ ] `cpcommon.clients` gains a memoized `lf()` Lake-Formation factory (module-global cache, matching the other factories); the shared-space verbs that use Lake Formation call `cpcommon.clients.lf()`. `cpcommon.clients` retains `athena()`; the union is complete.
- [ ] `deploy-lambdas.yml` sets `cpcommon: true` for all 8 shared-space matrix rows and attaches `cpcommon` alongside `shared-space-common`; each verb ends with exactly those 2 layers (under the 5-layer limit).
- [ ] The deploy role can attach the layer: it holds `lambda:GetLayerVersion` on `arn:aws:lambda:${aws_region}:*:layer:${project_name}-*-control-plane-common:*` (add the grant to the relevant `base/policies/*.tftpl` if absent). SPEC-107 already granted publish; this is the *attach* grant.
- [ ] **Sequencing:** the env + `lf()` + deploy-role grant land and apply in **PR 1**, verified green, **before** the PR 2 code that does `from cpcommon import …` deploys (the deploy-perms/env-before-resources rule, `base/iam.tf`).

### FR-002: `shared-space-common` is reduced to domain-only code, importing the shared surface from `cpcommon`

#### Description

Delete the duplicated modules; the verbs import `clients`/`config`-core/`error_code`/`emit_notification` from `cpcommon` and keep their domain helpers local.

#### Acceptance Criteria:

- [ ] `shared-space-common/clients.py` is **deleted**; the shared-space modules import `from cpcommon import clients`. (Not a re-export shim — a one-line shim is still a file that drifts, per SPEC-107 FR-002.)
- [ ] The shared **core** of `shared-space-common/config.py` (the `_require` helper + `USER_POOL_ID`/`APP_CLIENT_ID`/`ADMIN_BUCKET`/`SHARED_SPACE_BUCKET`/`USER_SPACE_BUCKET`) is removed; a slimmed domain `config` keeps `SCHEMA_VERSION`, `OWNER_ONLY_ACTIONS`, `VALID_ACTIONS`, `PORTAL_ROLE_ARN`, and the permission-list constants, sourcing the shared values from `cpcommon.config`.
- [ ] `shared-space-common/notify.py` drops its own `emit_notification` and calls `cpcommon.notify.emit_notification`; its seven domain lifecycle emitters (SPEC-061) stay.
- [ ] `shared-space-common/casio.py` drops its `error_code` helper and uses `cpcommon.errors.error_code`; the ETag-CAS retry loop stays.
- [ ] The shared-space verbs switch from **flat imports** (`import config`, `import clients`, `import registry as reg`) to **package imports** for the moved modules (`from cpcommon import config, clients`); the domain modules (`registry`, `cache`, `membership`, `teardown`, `casio`) keep their existing import style within the `shared-space-common` layer.
- [ ] `PyJWT` + `cryptography` are declared only in `cpcommon`'s requirements — not in `shared-space-common`'s.

### FR-003: The JWKS verification is shared, the two exception models are preserved

#### Description

Extract the ID-token verification into a `cpcommon` primitive both models can consume, so the security-critical path lives in one place while `shared-space` keeps raising `AuthorizationError` and tb/ts/dq keep raising `TerminalError`.

#### Acceptance Criteria:

- [ ] `cpcommon.auth.verify_id_token(id_token: str) -> dict` verifies a Cognito ID token offline against the User-Pool JWKS (PyJWT, RS256, `require` = `exp`/`iss`/`aud`), rejects a non-`id` `token_use`, and returns the verified claims; it raises a new `cpcommon.errors.AuthError` on a missing token, a JWKS/verification failure, a non-ID token, or a missing `cognito:username` claim. The `PyJWKClient` stays memoized.
- [ ] `cpcommon.auth.verified_username` (the tb/ts/dq entry point) is refactored to call `verify_id_token` and map `AuthError → TerminalError("unauthorized", …)` — its **external behaviour is unchanged**; a test pins that it still raises `TerminalError` with today's reason/detail.
- [ ] `shared-space-common/auth.py::verified_username` becomes a thin adapter over `cpcommon.auth.verify_id_token` that returns `cognito:username` and maps `AuthError → AuthorizationError` with the **same message text it raises today** (`"missing idToken"`, `"token verification failed: …"`, `"not an ID token"`, `"token missing cognito:username"`). A test pins each string, because nothing pins them today and a silent change would pass CI (the SPEC-107 FR-002 lesson).
- [ ] `shared-space-common/auth.py`'s **authorization** logic (`authorize`/action checks — `OWNER_ONLY_ACTIONS`, "space does not exist", "owner-only", "owner cannot leave") is untouched: it stays domain-side, still raising `AuthorizationError`, still reading the registry.
- [ ] The shared-space Standard Step Function still Catches an auth failure exactly as today (`AuthorizationError → Catch → Fail`, no verb runs) — **no SFN definition change**.
- [ ] A fixture-based test asserts `cpcommon.auth.verify_id_token`'s accept/reject outcome for each token fixture (valid, expired, wrong audience, wrong issuer, access-token-not-ID-token, malformed), reusing the SPEC-107 fixture set.

### FR-004: No behaviour change — the existing shared-space suite passes with only import-path changes

#### Description

The consolidation is structure-only. The proof is the existing test suite.

#### Acceptance Criteria:

- [ ] The **entire existing shared-space Lambda test suite passes** with changes limited to (a) import paths and (b) the new FR-003 error-string pins. Any test that has to change an assertion about *behaviour* is a spec violation — stop and escalate.
- [ ] `ruff check lambdas` and the full `pytest lambdas` run green (no unused imports left by the deletions; no cross-layer module-name collisions under the single pytest process — `cpcommon` is a package, `shared-space-common` stays flat, so `config`/`clients` names don't clash).
- [ ] Post-deploy, **re-run the documented shared-space live smoke procedure** (create → add-member → leave → delete across the 8 verbs) — a manual verification step, not an automated CI gate — confirming cold starts and each lifecycle action still work.
- [ ] The `shared-space-common` layer still builds/publishes in `deploy-lambdas.yml` (slimmed, domain-only); the combined per-function size guard (SPEC-107 FR-004) covers `cpcommon` + `shared-space-common` on each verb.

---

## Data Model

```
lambdas/control-plane-common/cpcommon/
├── clients.py     # + lf()  (Lake Formation) — the union now covers shared-space too
├── auth.py        # + verify_id_token(token) -> claims  (raises cpcommon.errors.AuthError)
│                  #   verified_username() now maps AuthError -> TerminalError (tb/ts/dq, unchanged)
└── errors.py      # + AuthError  (internal; verify_id_token raises it, callers translate)

lambdas/shared-space-common/          # SLIMMED to domain-only
├── clients.py        # DELETED -> from cpcommon import clients
├── config.py         # core removed; keeps SCHEMA_VERSION/OWNER_ONLY_ACTIONS/VALID_ACTIONS/PORTAL_ROLE_ARN/permission lists
├── auth.py           # verified_username -> thin adapter over cpcommon.auth.verify_id_token (AuthorizationError); authorize() unchanged
├── notify.py         # emit_notification removed -> cpcommon.notify.emit_notification; 7 lifecycle emitters stay
├── casio.py          # error_code removed -> cpcommon.errors.error_code; CAS retry loop stays
├── registry.py       # STAYS (ETag-CAS writer, SPEC-082)
├── cache.py          # STAYS
├── membership.py     # STAYS
├── teardown.py       # STAYS
└── fakes.py          # STAYS (test support)
```

Every shared-space verb's layer stack after the refactor:

| Function | Layers |
|---|---|
| every shared-space verb (all 8) | `cpcommon` + `shared-space-common` |

## File & Folder Structure

```
infra/modules/shared-spaces/variables.tf       # + athena_workgroup variable
infra/modules/shared-spaces/lambda.tf          # + ATHENA_WORKGROUP env on every verb
infra/<root>/…                                 # wire the analytics workgroup name into the shared-spaces module
infra/modules/base/policies/*.tftpl            # deploy role: lambda:GetLayerVersion on the cpcommon layer ARN (if absent)
lambdas/control-plane-common/cpcommon/…        # + lf(), verify_id_token, AuthError (above)
lambdas/shared-space-common/…                  # duplicated modules DELETED; domain code stays (above)
lambdas/shared-space-*/…                        # imports updated (flat -> cpcommon package) across the 8 verbs
.github/workflows/deploy-lambdas.yml           # cpcommon: true for the 8 shared-space rows; attach cpcommon
```

## Implementation Phases

> **Ships as (at least) TWO PRs**, because attaching `cpcommon` to the shared-space verbs is only safe once `ATHENA_WORKGROUP` is in their env — and the env change must **apply** before the code that imports `cpcommon` deploys (the same deploy-perms/env-before-resources rule that gated SPEC-107). Requires the deploy pipeline (CI) to be operational to validate the cold-start; do not build with CI disabled.

### Phase 1 (PR 1): Infra + `cpcommon` client union — must apply first

- Add the `athena_workgroup` variable to `infra/modules/shared-spaces`, wire it from root, and set `ATHENA_WORKGROUP` on every shared-space Lambda's env.
- Add `lf()` to `cpcommon.clients` (ships in the CI-built `cpcommon` layer).
- Add the deploy-role `lambda:GetLayerVersion` grant on the `cpcommon` layer ARN if not already present.
- Apply and confirm green — cold starts of the 8 verbs (still on the old imports) unaffected; the env + client union are now ready.

### Phase 2 (PR 2): Extract the JWKS primitive + the exception seam

- Add `cpcommon.errors.AuthError` and `cpcommon.auth.verify_id_token`; refactor `cpcommon.auth.verified_username` to use them (map to `TerminalError`, behaviour unchanged); pin both the `TerminalError` reason and the fixture accept/reject outcomes (FR-003).
- These land with tb/ts/dq unchanged (they only touch `cpcommon`), so this can merge independently of the shared-space edits if useful.

### Phase 3 (PR 2): Migrate `shared-space-common` onto `cpcommon` + attach the layer

- Reduce `shared-space-common/auth.py::verified_username` to the `AuthError → AuthorizationError` adapter (pin each message string); leave `authorize()` untouched.
- Delete `clients.py`, the config core, `notify.emit_notification`, and `casio.error_code`; switch the 8 verbs' flat imports to `from cpcommon import …`.
- Flip the CI matrix to `cpcommon: true` for the 8 rows and attach the layer; confirm the combined size guard (SPEC-107 FR-004) passes.
- Run the full Lambda suite: **only import paths + the FR-003 string pins may change** — every other assertion change is a spec violation. Post-deploy, re-run the shared-space live smoke procedure (FR-004). Delivery doc, INDEX status, and a component-inventory note that `shared-space-common` is now domain-only over `cpcommon`.
