# Spec: Table Builder — Request Contract, Browser Enqueue & Validate-Authorize

**ID:** SPEC-067
**Status:** Completed
**Last Updated:** 2026-06-27
**Depends On:** SPEC-066 (table-builder control plane skeleton + Lambda stubs + roles), SPEC-056 (shared-spaces registry = membership source of truth + ID-token actor binding), SPEC-006 (Cognito User Pool — token issuer), SPEC-034 (analytics clients + Glue per-DB model), SPEC-011 (portal role + module wiring)

> **Reference:** `docs/table-builder-architecture.md` §2/§3. Second of the arc. This spec defines the **request
> message contract**, gives the **browser** the one new permission it needs (`sqs:SendMessage` + the queue URL),
> and implements the **first real pipeline step — `validate-authorize`** (verify the caller's ID token → actor;
> authorize that the actor may create a table in the **target space/DB**; validate the table name + that the
> location is inside the space). Downstream verbs (check/inspect/infer/execute) stay stubs (SPEC-068→070). IAM is
> `.tftpl`; the Lambda follows `docs/best-practices/lambdas/lambdas.md`.

## Overview

Define how a create-table request is expressed and prove the first, security-critical step of the pipeline. The
browser, using its existing scoped credentials, enqueues a **request envelope** describing the target space
(bucket + prefix + the Glue database the space maps to), the desired table name, and the caller's Cognito **ID
token** — onto the SPEC-066 FIFO queue with **`MessageGroupId` = the target database** (so same-DB requests
serialize). The pipeline's first Lambda, **`validate-authorize`**, verifies the token offline against the User
Pool JWKS and derives the **actor** server-side (never trusting a body username), then **authorizes** the
request: for a **personal** target the DB must be the actor's own username; for a **shared** target the actor
must be an **active member** per the shared-spaces registry (SPEC-056). It also validates that the table name is
catalog-safe, that the location resolves **within** the target space's bucket+prefix, and that any
**user-declared `partitionKeys`** are well-formed (catalog-safe names in granularity order, each with a valid
projection type + range). A failed check is a clean, terminal no-op (recorded-failure state); a pass emits the
validated, normalized request for the next steps.

## Scope

### In Scope

- **Request-message contract** — a single JSON envelope (Data Model) carrying `idToken`, the `space`
  (`kind`/`bucket`/`prefix`/`database`), `tableName`, and an optional **`partitionKeys`** array (the
  user-declared keys in granularity order, each with a projection `type` + range; **empty/absent = flat table**
  — partition keys are **never** auto-detected from the path, decided 2026-06-30). Documented in
  `docs/testing/e2e.md` so the browser (SPEC-071) and the pipeline build to one shape. Sent FIFO
  with **`MessageGroupId` = `space.database`** + a `MessageDeduplicationId` (collapses a double-submit).
- **Browser producer access** — the **portal role** gains `sqs:SendMessage` on the table-build queue ARN **only**
  (a `.tftpl` statement); the queue URL is wired to the app as **`VITE_TABLE_BUILD_QUEUE_URL`** (SPEC-066 export).
  No other table-builder permission for the browser.
- **`validate-authorize` Lambda** — the real first step: verify the ID token (issuer/audience/expiry/signature
  via the pool JWKS, **offline**, no Cognito API) → `actor`; **authorize**:
  - personal (`space.kind='personal'`): `space.database === actor` (the actor's own username/DB) and
    `space.bucket` = the user-space bucket and `space.prefix` starts with `{actor}/`;
  - shared (`space.kind='shared'`): the actor is an **active member** of `space.database` per the shared-spaces
    registry (`<admin-bucket>/shared-spaces/{name}.json`), `space.bucket` = `dat-prod-shared-space`, and
    `space.prefix` starts with `{name}/`.
  - validate `tableName` against `CATALOG_IDENTIFIER_RE` (SPEC-033/048); normalize/trim the prefix.
  - validate `partitionKeys` (when present): each `name` is `CATALOG_IDENTIFIER_RE`-safe and unique; order is
    preserved (granularity order is the user's contract); `type ∈ {integer,date,string}` with the
    type-appropriate projection config well-formed (`integer`/`date` → a two-element `range`; `string` → a
    non-empty `values` list); names must not collide with each other. A malformed `partitionKeys` is terminal
    `invalid_partition_keys`.
  Emits a small validated payload (`actor`, normalized `space`, `tableName`, `partitionKeys`,
  `location = s3://{bucket}/{prefix}/`) for the next state.
- **Validator role** — the SPEC-066 `validate-authorize` role's `.tftpl` policy is finalized: `s3:GetObject` on
  `<admin-bucket>/shared-spaces/*` (registry reads for shared authorization) + `logs`; **offline JWKS** ⇒ no
  Cognito IAM. Scoped + `simulate-custom-policy`-verified.
- **Step Function `validate` state** — the first Task runs `validate-authorize`; a terminal failure is routed by
  the existing `Catch` (SPEC-066) to the **recorded-failure** state (with the reason); a pass proceeds to the
  (stubbed) `check-table-absent`.
- **Deploy-role IAM** — the portal-role `sqs:SendMessage` grant + the validator role's registry-read grant (added
  to the table-builder deploy fragment).

### Out of Scope

- **check-table-absent / inspect-source / infer-schema / execute-ddl** logic — SPEC-068→070 (stubs after this
  spec; the validate→… handoff payload shape is defined here).
- **Notifications** on validation failure — SPEC-072 (this spec records the failure in the SFN execution; the
  user-facing notification is wired by the producer spec).
- **The browser UI** that builds + sends the envelope (button, name dialog, space→DB mapping) — SPEC-071 (this
  spec defines the contract + grants the send permission + exports the env var).
- Any change to the shared-spaces registry **shape** or who may be a member (consumed read-only here).

---

## Functional Requirements

### FR-001: Request-message contract

#### Acceptance Criteria:

- [ ] The queue accepts a JSON body matching the **Data Model** envelope: `idToken`, `space` (`kind` ∈
  `personal|shared`, `bucket`, `prefix`, `database`), `tableName`, an optional **`partitionKeys`** array
  (user-declared; empty/absent = flat), and an optional client `requestId`.
- [ ] Every message is sent with **`MessageGroupId` = `space.database`** (per-DB serialization, FR rationale in
  `table-builder-architecture.md` §2) and a `MessageDeduplicationId` (e.g. `requestId`) so a double-submit is
  collapsed by FIFO.
- [ ] A message failing schema validation (missing/garbled fields) is a **terminal** failure (logged → recorded;
  no partial progress), never a silent pass.
- [ ] The contract is documented in `docs/testing/e2e.md`.

### FR-002: Browser producer access

#### Acceptance Criteria:

- [ ] The **portal role** gains a `.tftpl` statement allowing `sqs:SendMessage` on the **table-build queue ARN
  only** (no other table-builder action; no DLQ, no Lambda invoke, no Step Function).
- [ ] `aws iam simulate-custom-policy` confirms the portal role can `SendMessage` to the table-build queue and
  **cannot** to an unrelated queue.
- [ ] The queue URL is exposed to the app as **`VITE_TABLE_BUILD_QUEUE_URL`** (documented in
  `apps/portal/.env.example`); because the queue is FIFO, the browser send must include `MessageGroupId` +
  `MessageDeduplicationId` (FR-001) — the send helper lands in SPEC-071.

### FR-003: ID-token actor binding

#### Acceptance Criteria:

- [ ] `validate-authorize` **requires** `idToken` and verifies it against the User Pool **offline** (issuer,
  audience, expiry, signature via the pool JWKS) before trusting any claim; the **actor** = the verified
  `cognito:username` claim — a body `username`/`actor`, if present, is **ignored** (`lambdas.md` §9).
- [ ] A missing/expired/invalid token is a **terminal** failure with reason `unauthorized`; no downstream step
  runs.

### FR-004: Authorization against the target space

#### Acceptance Criteria:

- [ ] **Personal** (`space.kind='personal'`): the request is authorized only if `space.database === actor`,
  `space.bucket` is the user-space bucket, and `space.prefix` begins with `{actor}/`. Otherwise terminal
  `forbidden`.
- [ ] **Shared** (`space.kind='shared'`): the request is authorized only if the actor is an **active member** of
  `space.database` per `<admin-bucket>/shared-spaces/{database}.json` (status `active`, actor ∈ `members`),
  `space.bucket` = `dat-prod-shared-space`, and `space.prefix` begins with `{database}/`. A non-member, an
  unknown/inactive space, or an out-of-space prefix is terminal `forbidden`. (Any active member may create — not
  owner-only.)
- [ ] The check is performed **before** any side effect; it is a pure authorization decision (no table touched
  yet).

### FR-005: Name + location validation and the validated payload

#### Acceptance Criteria:

- [ ] `tableName` must match `CATALOG_IDENTIFIER_RE` (lowercase, leading letter, `[a-z0-9_]`, 3–63 chars; the
  SPEC-033/048 rule); otherwise terminal `invalid_table_name`.
- [ ] `partitionKeys` (when present) are validated: each `name` is `CATALOG_IDENTIFIER_RE`-safe + unique,
  `type ∈ {integer,date,string}`, and the projection config is well-formed for the type (`integer`/`date` →
  two-element `range`; `string` → non-empty `values`); order is preserved as sent. A malformed array is
  terminal `invalid_partition_keys`.
- [ ] On success the Lambda returns a minimal, normalized payload the next states consume:
  `{ actor, space:{kind,bucket,prefix,database}, tableName, partitionKeys, location:"s3://{bucket}/{prefix}/" }`
  — small ids/keys only, not large blobs (`lambdas.md` §10).
- [ ] The SFN `validate` Task runs `validate-authorize`; a terminal failure routes via `Catch` to the
  recorded-failure state carrying the reason; a pass proceeds to `check-table-absent`.

### FR-006: Validator role + deploy IAM

#### Acceptance Criteria:

- [ ] The `validate-authorize` role's `.tftpl` policy grants `s3:GetObject` on `<admin-bucket>/shared-spaces/*`
  (registry reads) + `logs` and **nothing else** (offline JWKS ⇒ no Cognito IAM); verified with
  `simulate-custom-policy` (read a registry object = allowed; any write or other-bucket read = implicitDeny).
- [ ] The deploy-role table-builder fragment is extended for the portal-role `sqs:SendMessage` and the validator's
  registry-read grant; `tofu validate`/`plan` clean.

### FR-007: Tests + e2e

#### Acceptance Criteria:

- [ ] Python unit tests for `validate-authorize` (pure logic, AWS stubbed): valid personal request passes; valid
  shared-member request passes; a valid **partitioned** request (well-formed `partitionKeys`) passes and carries
  them through; **wrong-user personal**, **non-member shared**, **inactive/unknown space**, **out-of-space
  prefix**, **bad table name**, **malformed `partitionKeys`** (bad name / unknown type / missing range/values /
  duplicate name → `invalid_partition_keys`), and **missing/expired token** each produce the correct terminal
  reason with **no** side effect; the validated payload shape matches FR-005. Idempotent (re-running validation is
  side-effect-free).
- [ ] `docs/testing/e2e.md`: a real browser-style message (valid token, personal space) passes
  `validate` and reaches the (stub) `check-table-absent`; a forged/cross-user message is recorded-failed at
  `validate` with no downstream run.

---

## Data Model

```jsonc
// SQS message body — the create-table request envelope.
// Sent to the FIFO queue with MessageGroupId = space.database + MessageDeduplicationId = requestId.
{
  "idToken": "<cognito id token>",      // REQUIRED; actor derived from the verified claim (FR-003)
  "space": {
    "kind": "personal",                 // 'personal' | 'shared'
    "bucket": "dat-prod-user-space",    // user-space bucket | 'dat-prod-shared-space'
    "prefix": "alice/sales/2026/",      // the folder being turned into a table (within the space)
    "database": "alice"                 // Glue DB the space maps to (= username | shared name)
  },
  "tableName": "sales_2026",            // catalog-safe (CATALOG_IDENTIFIER_RE)
  "partitionKeys": [                    // OPTIONAL; user-declared in granularity order. Omit/[] = flat table.
    { "name": "year",  "type": "integer", "range": [2000, 2100], "digits": 4 },
    { "name": "month", "type": "integer", "range": [1, 12],      "digits": 2 },
    { "name": "day",   "type": "integer", "range": [1, 31],      "digits": 2 }
    // date  key: { "name":"dt",     "type":"date",   "range":["2020-01-01","NOW"], "format":"yyyy-MM-dd" }
    // string key: { "name":"region", "type":"string", "values":["us-east-1","eu-west-1"] }  // → projection enum
  ],
  "requestId": "f3a1…"                  // client-generated; dedup + correlation (optional)
}
```

```python
# validate-authorize output (passed to check-table-absent) — small, normalized
{
  "actor": "alice",
  "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice"},
  "tableName": "sales_2026",
  "partitionKeys": [   # [] when flat; carried verbatim to inspect-source / infer-schema
    {"name": "year",  "type": "integer", "range": [2000, 2100], "digits": 4},
    {"name": "month", "type": "integer", "range": [1, 12],      "digits": 2},
    {"name": "day",   "type": "integer", "range": [1, 31],      "digits": 2}
  ],
  "location": "s3://dat-prod-user-space/alice/sales/2026/",
  "requestId": "f3a1…"
}

# terminal reasons added here: invalid_partition_keys
```

## Environment Variables

```
# apps/portal/.env.example  (consumed by the SPEC-071 send helper)
VITE_TABLE_BUILD_QUEUE_URL=<table-build FIFO queue URL, ends in .fifo>   # exported by SPEC-066
```

Server-side (`validate-authorize`): `USER_POOL_ID` / issuer + `ADMIN_BUCKET` (registry) as module env vars.

## File & Folder Structure

```
lambdas/table-builder-validate-authorize/
├── validate_authorize.py        # real logic: verify token → actor; authorize personal/shared; name+location checks
└── test_validate_authorize.py   # NEW

lambdas/table-builder-common/
├── auth.py                      # shared offline JWT verify (reused by later verbs if needed)
└── registry.py                  # shared-spaces registry read helper (membership check)

infra/modules/table-builder/
├── policies/validate-authorize.tftpl   # S3 registry read + logs (FR-006)
├── state-machine.asl.json.tftpl        # validate Task + Catch → recorded-failure (FR-005)
└── variables.tf                        # + admin/user/shared bucket ARNs, user_pool_id

infra/modules/<portal-role module>/policies/   # + sqs:SendMessage on the table-build queue ARN (FR-002)
infra/modules/base/policies/                    # deploy-policy-table-builder additions (FR-006)
apps/portal/.env.example                        # + VITE_TABLE_BUILD_QUEUE_URL (FR-002)
docs/testing/e2e.md               # contract + validate flow (FR-001/FR-007)
```

## Implementation Phases

### Phase 1: Contract + browser grant + token/actor binding

- Document the envelope; portal-role `sqs:SendMessage` + `VITE_TABLE_BUILD_QUEUE_URL`; implement offline
  ID-token verification → actor in `validate-authorize` (FR-001, FR-002, FR-003).

### Phase 2: Authorization + validation + SFN validate state

- Personal/shared authorization (registry read for shared) + name/location validation + the normalized payload;
  wire the SFN `validate` Task + Catch; validator role policy + deploy IAM; unit tests + e2e doc
  (FR-004, FR-005, FR-006, FR-007).
