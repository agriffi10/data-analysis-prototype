---
type: Spec
id: SPEC-107
title: "Shared `control-plane-common` Lambda Layer"
description: "Merges the near-duplicate table-builder and table-share helpers for auth, errors, clients, registry, listing and notify into one shared cpcommon control-plane Lambda layer for developers."
spec_status: Completed
depends_on: [SPEC-062, SPEC-066, SPEC-088, SPEC-106]
arc: control-plane-common
arc_order: 1
---

**Dependency notes:** SPEC-062 (shared-space verb decomposition), SPEC-066 (`tbcommon`), SPEC-088 (`tscommon`), SPEC-106 (error messaging)
> **Read `docs/architecture-review-2026-07-11.md` §5.5 first.** This is a **prerequisite refactor**, not a feature. It exists so the data-quality (SPEC-108→114) and file-converter (SPEC-115→121, +122 optional) arcs do not create a third and fourth independent copy of the JWT verification path. It ships **no user-visible change**.

## Overview

`lambdas/table-builder-common/tbcommon/auth.py` and `lambdas/table-share-common/tscommon/auth.py` are **near-identical twins** today — same logic, differing only in an import order and one error string (`tbcommon/auth.py:18` raises `"missing idToken"`, `tscommon/auth.py:18` raises `"missing actor token"`). `errors.py` is identical, and `clients.py`/`registry.py` differ only additively (`tscommon` adds a memoized `cognito()` client and `is_active` alongside `is_active_member`) — `cpcommon` takes the **union**. The rest is *not* a clean twin set. `s3_listing.py` diverges in **yield semantics**: `tbcommon` yields **absolute** keys — table-builder's `inspect_source.py` depends on them for `sampleObjectKey` — while `tscommon` yields keys **relative** to the prefix (`key[len(prefix):]`); FR-003 resolves this explicitly rather than "keeping one version". `config.py` shares a core but each carries domain constants (`tbcommon`'s `PARTITION_TYPES`; `tscommon`'s `SHARE_MAX_OBJECTS`/`SHARE_MAX_TOTAL_BYTES`/`RECIPIENT_KINDS`) — only the core moves (FR-001). `notify.py` shares only `emit_notification` and the `notifies_on_failure` skeleton; the emitters are domain-specific (see In Scope). `events.py` exists only in `tbcommon`. (`messages.py` is genuinely domain-specific in each layer, which is why FR-005 gives it a registration hook rather than a straight merge.) The two new control-plane arcs would add `dqcommon` and `fccommon`, taking the count to **four independent copies of security-critical token verification** — meaning a JWKS handling fix or a claim-validation fix must land in four places, and will eventually land in three.

**Note the drift already present.** The two `auth.py` files are *not* byte-identical, and the extraction must not silently adopt one layer's error strings for the other. No test asserts those strings today, so a regression here would pass CI unnoticed — FR-002 makes it explicit.

This spec extracts the shared surface into **one `control-plane-common` (`cpcommon`) Lambda layer** that every control-plane verb attaches alongside its domain layer. It also fixes a latent correctness bug the extraction surfaces (the basename-only hidden-path rule), and closes a CI gap that the new arcs would otherwise walk into (the layer-size guard measures one layer in isolation, while Lambda's 250 MB ceiling is per-function across *all* layers plus code).

Doing this **before** the two arcs is deliberate: consolidating four layers after they exist is a refactor of live code that historically never happens.

## Scope

### In Scope

- A new **`cpcommon` Lambda layer** (`lambdas/control-plane-common/cpcommon/`), CI-built and published like `tbcommon`/`tscommon`, holding: `config` (shared env core + `_require` — domain constants stay in domain configs, FR-001), `clients` (memoized boto3 + JWKS client — the union, incl. `tscommon`'s `cognito()`), `errors` (`TerminalError`/`TransientError`), `auth` (ID-token verify → actor), `registry` (shared-space record load + `is_active` + `is_active_member`), `s3_listing` (absolute keys, `relative: bool = False` opt-in — FR-003), `notify` (`emit_notification(username, message, dedup_id=None)` + a `notifies_on_failure` **skeleton** that takes a domain-supplied unexpected-failure emitter as an explicit seam; `emit_failure`/`emit_unexpected`/context extraction stay in the domain layers — their signatures differ, `tbcommon` deduplicates via `{requestId}:{step}` while `tscommon` relies on content-based dedup), `messages` (SPEC-106 base mapping + a per-domain extension hook), `events` (event-shape validation — today `tbcommon`-only, already generic; table-share verbs do **not** adopt it in this spec).
- **`tbcommon` and `tscommon` reduced to domain-only code** — the duplicated modules deleted, their verbs importing from `cpcommon`. `tbcommon` keeps its DDL/Hive/partition-projection helpers; `tscommon` keeps its copy/DDL helpers.
- Both existing layers' verb Lambdas re-attached as **`cpcommon` + domain layer** (2 layers; `infer-schema` becomes polars + `tbcommon` + `cpcommon` = 3, within the 5-layer limit).
- **Fix: the hidden-path rule becomes segment-level.** `cpcommon.s3_listing` adopts `tscommon`'s rule (any `_`/`.`-prefixed **path segment** excludes the object), replacing `tbcommon`'s basename-only check.
- **Fix: the CI layer-size guard becomes a combined, per-function measurement** — unzipped size of all attached layers **plus** the function package, checked against a 240 MB threshold (Lambda's hard limit is 250 MB).
- A **per-domain `messages` extension hook**, so `tbcommon`/`tscommon`/`dqcommon`/`fccommon` register their own reason-code → friendly-text entries on top of the shared base table without forking the module.

### Out of Scope

- Any behaviour change **except the two named fixes** — FR-003's segment-level listing rule and FR-004's CI guard. Every other verb path must behave **identically** before and after.
- `dqcommon` / `fccommon` themselves — SPEC-108 / SPEC-115.
- The `shared-space-common` layer. It predates the `tbcommon`/`tscommon` convention, has its own registry semantics (CAS/`If-None-Match`), and its verbs are stable. Folding it in is a **follow-up**, not this spec — the goal here is to stop the bleeding before two new copies appear, not to boil the ocean. (Note this explicitly so a reviewer doesn't read its absence as an oversight.)
- Per-verb IAM roles, new resources, new env vars, any SPA change.
- A DLQ alarm (a known cross-cutting gap, see the architecture docs).

---

## Functional Requirements

### FR-001: The `cpcommon` layer exists and is the single source of the shared surface

#### Description

One CI-built, published Lambda layer carrying every helper that is genuinely shared between `tbcommon` and `tscommon` — the shared core; domain constants and domain emitters stay domain-side.

#### Acceptance Criteria:

- [ ] `lambdas/control-plane-common/cpcommon/` exists with modules `config`, `clients`, `errors`, `auth`, `registry`, `s3_listing`, `notify`, `messages`, `events`.
- [ ] The layer is built + published in `deploy-lambdas.yml` using the same mechanism as `tbcommon`/`tscommon`; Terraform owns the functions with `ignore_changes=[layers]`.
- [ ] `cpcommon.auth` verifies a Cognito ID token offline against the User Pool JWKS (PyJWT, RS256, `require` = `exp`/`iss`/`aud`), rejects a non-`id` `token_use`, and returns the `cognito:username` claim as the actor — never a body-supplied value.
- [ ] The `PyJWKClient` is memoized in a module global (per-container cache), matching today's `tbcommon/clients.py:51-58`.
- [ ] `cpcommon.registry.is_active_member(record, actor)` returns true iff the record's `status == "active"` **and** `actor` is in `members`. Its docstring states explicitly that this is the **space's** status and is unrelated to SPEC-073's per-member Pending/Active join chip (a Pending member passes).
- [ ] `cpcommon.clients` and `cpcommon.registry` take the **union** of today's twins: the memoized `cognito()` client (`tscommon/clients.py`) and `is_active` alongside `is_active_member` (`tscommon/registry.py`) come along.
- [ ] `cpcommon.events` is `tbcommon.events` moved (it exists only in `tbcommon` today and is already generic; `tscommon` has no `events.py` — its verbs validate inline). Table-share verbs do **not** adopt it in this spec — that would be a behaviour change, left to a later spec.
- [ ] **Domain constants do not move.** `PARTITION_TYPES` stays in a `tbcommon` domain `config`; `SHARE_MAX_OBJECTS`, `SHARE_MAX_TOTAL_BYTES`, and `RECIPIENT_KINDS` stay in a `tscommon` domain `config`. `cpcommon.config` carries only the shared core.
- [ ] Every env var `cpcommon.config` `_require()`s (e.g. `COGNITO_USER_POOL_ID` / `COGNITO_APP_CLIENT_ID`) is present in the **common Lambda env of every function that attaches the layer** — verified for all ten verbs. A shared layer's import-time `_require` runs at cold start for every attaching function, so one missing var on one verb is a cold-start crash — the PR #196 lesson (`tscommon/config.py:23-27`).
- [ ] `PyJWT` + `cryptography` are declared **once**, in `cpcommon`'s requirements — not in any domain layer.

### FR-002: `tbcommon` and `tscommon` are reduced to domain-only code, with identical behaviour

#### Description

Delete the duplicates; the verbs import the shared surface from `cpcommon`.

#### Acceptance Criteria:

- [ ] The duplicated modules are **deleted** from `tbcommon` and `tscommon` (not left as re-export shims — a one-line shim is still a file that drifts).
- [ ] Every table-builder and table-share verb imports the shared surface from `cpcommon` and its domain helpers from its own layer; all five table-builder and five table-share functions attach `cpcommon` **and** their domain layer.
- [ ] `tbcommon` retains only its domain surface (DDL generation, dtype→Hive mapping, partition projection, its domain `config` constants + notify emitters); `tscommon` retains only its (copy, recipient DDL, its domain `config` constants + notify emitters).
- [ ] The **entire existing Lambda test suite passes unchanged** except for import paths. Any test that has to change its *assertions* is a behaviour change and a spec violation — stop and escalate.
- [ ] **Error strings are preserved per domain.** `cpcommon.auth` raises the same reason text each caller raises today (`"missing idToken"` for table-builder, `"missing actor token"` for table-share) — parameterize the message rather than picking one. A test pins both strings, because nothing pins them today and a silent change would pass CI.
- [ ] A fixture-based test asserts `cpcommon.auth`'s accept/reject outcome for each token fixture (valid, expired, wrong audience, wrong issuer, access-token-not-ID-token, malformed), with the expected outcomes **captured from the pre-refactor module during development** — the same PR deletes that module, so the test pins the recorded outcomes rather than comparing against it live.
- [ ] Post-deploy, **re-run the documented live smoke procedure** for the table-builder and table-share control planes — a manual verification step, not an automated CI gate.

### FR-003: The hidden-path rule is segment-level

#### Description

`tbcommon/s3_listing.py:35` checks only the **basename**, so `alice/_data-quality-reports/x/report.json` is **not** ignored — the `_` is in a path segment. `tscommon/s3_listing.py:32-37` already fixed this and says so. The shared module adopts the fixed rule for everyone. This is a **prerequisite** for the data-quality arc, which puts reports under a `_`-prefixed folder that Table Builder would otherwise ingest as source data.

The move must also resolve the **yield-semantics divergence**: `tbcommon`'s `list_data_objects` yields **absolute** keys (table-builder's `inspect_source.py` depends on them for `sampleObjectKey`), while `tscommon`'s yields keys **relative** to the prefix (`key[len(prefix):]`, re-rooted by the copy step). `cpcommon.s3_listing` standardizes on **absolute** keys with an explicit `relative: bool = False` parameter; `tscommon`'s call sites pass `relative=True`.

#### Acceptance Criteria:

- [ ] `cpcommon.s3_listing` excludes an object if **any path segment** under the request prefix starts with `_` or `.`.
- [ ] `cpcommon.s3_listing.list_data_objects` yields **absolute** keys by default and takes `relative: bool = False`; the table-share call sites pass `relative=True` and receive today's prefix-relative keys unchanged.
- [ ] A test pins that inspect-source's `sampleObjectKey` remains **absolute** after the move.
- [ ] A test asserts `alice/_data-quality-reports/abc/report.json` is excluded when listing `alice/`, and that `alice/data/part-0.csv` is not.
- [ ] Table Builder's existing exclusions still hold: `athenaresults/`, the `DO_NOT_DELETE.txt` marker, zero-byte objects.
- [ ] **`user_settings/` is excluded too.** It has no leading underscore, so the segment rule does not catch it. Today this is nearly unreachable (the space root isn't a selectable row), but a folder-level scan that reaches a space root would otherwise treat the user's notification inbox and saved queries as source data. One extra exclusion closes it; a test asserts `alice/user_settings/notifications.json` is never listed.
- [ ] The table-builder inspect-source tests still pass (the rule only ever excludes *more*, and nothing legitimate relies on a `_`-segment being ingested).

### FR-004: The CI layer-size guard measures the combined per-function footprint

#### Description

Lambda's 250 MB unzipped ceiling applies to **all attached layers plus the function package, combined**. Today's guard (`deploy-lambdas.yml:121-128`) measures **one layer directory in isolation**, so it cannot catch a combined overflow — which is exactly the failure mode the file-converter foundation (SPEC-115) risks (`cpcommon` + `fccommon` + polars on one function).

#### Acceptance Criteria:

- [ ] CI computes, for **every** function, the unzipped total of its attached layers **plus** its own package, and fails the build above **240 MB** (leaving headroom under the 250 MB hard limit).
- [ ] The failure message names the function, its layers, and the measured total — not just "too big."
- [ ] The check runs **before** publish/attach, so an oversized combination fails the build rather than the deploy.
- [ ] A note in the workflow records *why* the per-layer check was insufficient, so it isn't "simplified" back.

### FR-005: Domain-extensible error messages (SPEC-106)

#### Description

The SPEC-106 mapping must stay one source of wording while letting each domain add its own reason codes.

#### Acceptance Criteria:

- [ ] `cpcommon.messages` holds the shared reason-code → friendly-text table (`unauthorized`, `forbidden`, `unexpected_error`, the transient/terminal generics) and exposes a registration hook for domain tables.
- [ ] Registries are **domain-scoped**: each domain layer gets its own resolver, bound to (shared base table + its own domain table). The duplicate hard-error applies only to a domain re-registering a shared-base code or its own code twice — **never across domains**. (`tbcommon` and `tscommon` both define `invalid_table_name` today with different wording, and CI runs one `pytest lambdas/` process that imports both domain packages — a single global registry would hard-error there by design.)
- [ ] Reason codes are **exported constants** from the messages module (base codes from `cpcommon.messages`, domain codes from the domain table's module) — no bare string literals at raise sites.
- [ ] Raising a `TerminalError` with a reason code not present in the resolved (base + domain) registry is itself an error **at raise-time**, not a silent fallback at message-resolution time. The data-quality and file-converter arcs rely on this (SPEC-110 FR-005 and SPEC-114 FR-002 cite it).
- [ ] Raw AWS/Athena/Python text never reaches a notification body: the resolver returns the friendly string and the raw detail is logged only (preserving `tbcommon/messages.py`'s SPEC-106 FR-008 behaviour).
- [ ] Substitution uses `str.replace` on named tokens, never `str.format` — a literal brace in a table or database name must not raise (`tbcommon/messages.py:45-47`).

---

## Data Model

```
lambdas/control-plane-common/
├── cpcommon/
│   ├── __init__.py
│   ├── config.py        # shared core: REGION, USER_POOL_ID, APP_CLIENT_ID, buckets, _require(); domain constants stay domain-side
│   ├── clients.py       # memoized boto3 clients (union — incl. tscommon's cognito()) + PyJWKClient
│   ├── errors.py        # TerminalError, TransientError
│   ├── auth.py          # verify ID token → actor  (was tbcommon/auth.py ≡ tscommon/auth.py)
│   ├── registry.py      # shared-space record load + is_active + is_active_member
│   ├── s3_listing.py    # segment-level hidden-path rule; absolute keys, relative=False opt-in (FR-003)
│   ├── notify.py        # emit_notification(username, message, dedup_id=None) + notifies_on_failure w/ domain-emitter seam; emit_failure/emit_unexpected stay domain-side
│   ├── messages.py      # SPEC-106 base table + domain registration hook (FR-005)
│   └── events.py        # event-shape validation → typed terminals (was tbcommon-only; table-share doesn't adopt it in this spec)
└── requirements.txt     # PyJWT[crypto]  (declared ONCE, here)
```

After the refactor, a verb's layer stack is:

| Function | Layers |
|---|---|
| every table-builder / table-share verb | `cpcommon` + domain layer |
| `table-builder-infer-schema` | `cpcommon` + `tbcommon` + polars (3 of a max 5) |

## File & Folder Structure

```
lambdas/control-plane-common/…                 # new (above)
lambdas/table-builder-common/tbcommon/…        # duplicated modules DELETED; domain code stays
lambdas/table-share-common/tscommon/…          # duplicated modules DELETED; domain code stays
lambdas/table-builder-*/…                      # imports updated
lambdas/table-share-*/…                        # imports updated
infra/modules/table-builder/lambda.tf          # attach cpcommon (ignore_changes=[layers] already set)
infra/modules/table-share/lambda.tf            # attach cpcommon
infra/modules/base/policies/*.tftpl            # deploy-role: publish/attach the new layer
.github/workflows/deploy-lambdas.yml           # build+publish cpcommon; combined size guard (FR-004)
```

## Implementation Phases

> **This spec ships as TWO PRs.** The `cpcommon` layer is a **new resource**, and every existing layer grant in the deploy role is name-scoped (`…:layer:${project_name}-*-table-builder-*` / `…-table-share-*`, `base/policies/github-actions-deploy-table-share.json.tftpl:84-96`). None of them matches `control-plane-common`, so **CI cannot publish the layer until the grant has applied.** The deploy-perms-before-resources rule (`base/iam.tf:145-146`) is not optional here — inverting these phases fails the first apply.

### Phase 1 (PR 1): Deploy-role IAM — must apply first

- The layer publishes as **`${project_name}-${environment}-control-plane-common`** — the same `deploy-lambdas.yml` naming convention as `…-table-builder-common` / `…-table-share-common` (`LAYER_NAME="${PROJECT_NAME}-${ENVIRONMENT}-…"`).
- Expand the deploy role via a **new `infra/modules/base/policies/github-actions-deploy-control-plane-common.json.tftpl`**, rendered into its own customer-managed policy + attachment in `base/iam.tf` — the same per-arc structure as the table-builder/table-share grants (each arc's grants live in their own managed policy, off the role's inline-policy aggregate limit). Grant publish/delete in **both** ARN forms: `arn:aws:lambda:${aws_region}:*:layer:${project_name}-*-control-plane-common` and `…-control-plane-common:*`. Apply and confirm green **before** PR 2 lands.

### Phase 2 (PR 2): Extract the layer

- Create `lambdas/control-plane-common/cpcommon/`. The two `auth.py` files are near-identical but **not** byte-identical (see Overview) — parameterize the differing error string rather than picking one (FR-002). For `s3_listing`, adopt `tscommon`'s segment-level hidden rule but **not** its yield semantics: standardize on absolute keys with `relative: bool = False`, `tscommon` call sites passing `relative=True` (FR-003).
- Add the `messages` domain-registration hook (FR-005), the segment-level listing rule and the `user_settings/` exclusion (FR-003), with tests.
- Fixture-based `auth` tests against the token fixture set (expected outcomes captured from the pre-refactor module during development), pinning both domains' error strings (FR-002).

### Phase 3 (PR 2): Refactor the two existing layers onto it, + the CI guard

- Delete the duplicated modules from `tbcommon`/`tscommon`; update every verb's imports; keep domain code in place.
- Re-attach layers in Terraform + `deploy-lambdas.yml` (one `--layers` call per function — it **replaces** the whole list); confirm the 5-layer limit holds.
- Combined per-function size guard (FR-004), with the explanatory note on why the per-layer check was insufficient.
- Run the full Lambda test suite: **only import paths may change**, plus the new FR-003 assertions (segment rule, `user_settings/`, absolute `sampleObjectKey`) — every other assertion change is a spec violation. Post-deploy, re-run the documented live smoke procedure for both control planes (FR-002). Delivery doc, INDEX status, component-inventory row for the layer.
