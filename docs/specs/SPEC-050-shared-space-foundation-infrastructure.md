# Spec: Shared-Space Foundation Infrastructure (Bucket 2 + Control Plane)

**ID:** SPEC-050
**Status:** Completed
**Last Updated:** 2026-06-26
**Depends On:** SPEC-032 (analytics foundation: admin bucket + LF bootstrap/hybrid registration), SPEC-010 (user-space bucket conventions), SPEC-012 (Lambda code/infra split + `deploy-lambdas.yml`), SPEC-011 (deploy role + module wiring)

> **Reference:** `docs/shared-spaces-architecture.md` — read it first. This spec builds the **plumbing only**:
> the shared bucket, the registry storage, and the async control plane (SQS → EventBridge Pipe → Step Function
> + provisioner Lambda) with a privileged orchestrator role. It deliberately ships **no access model and no
> action semantics** — **SPEC-056** adds the membership tags / portal-role slots / LF registration / request
> contract, and SPEC-051→055 add the per-action behavior. Splitting the original SPEC-050 in two keeps the
> buckets/pipeline applyable and reviewable separately from the IAM/access wiring (which trips the most
> deploy-role/self-grant traps). All IaC is OpenTofu; IAM is `.tftpl`; Lambda code/infra are split.

## Overview

Stand up the shared-connections **infrastructure scaffold** with no user-visible behavior and no access grants
yet: the `dat-prod-shared-space` bucket; the pipeline-only registry (a `shared-spaces/` prefix in the existing
analytics admin bucket, with its lifecycle scoped so registry objects don't expire); and the asynchronous control
plane — an **SQS** request queue + **DLQ**, an **EventBridge Pipe** routing it to a **Step Function** state-machine
skeleton, and a **provisioner Lambda** invoked by the machine, all under a single privileged **orchestrator role**.
When this spec is done a message placed on the queue flows through the Pipe into the Step Function and reaches the
Lambda (which, for now, just dispatches/echoes) — proving the control plane end-to-end — while nothing yet grants a
user access to anything. The membership/access model and the request contract land in **SPEC-056**; the create and
membership actions in SPEC-051→055.

## Scope

### In Scope

- **`dat-prod-shared-space` S3 bucket** — browser-facing CORS for the app origin; all public access blocked; SSE-S3;
  `BucketOwnerEnforced`; versioning off (MVP); abort-incomplete-multipart lifecycle (7-day, SPEC-016) — mirrors the
  user-space bucket hygiene (`infra/modules/data/s3.tf`). Bucket name exported for later `VITE_*` wiring
- **Registry storage** — a `shared-spaces/` prefix in the **existing analytics admin bucket** (SPEC-032), with that
  bucket's `expire-admin-results` lifecycle rule **scoped to exclude `shared-spaces/`** so registry objects never
  expire. No new registry bucket; no browser CORS on the admin bucket
- **Control plane** — an **SQS** request queue + **DLQ** (redrive policy); an **EventBridge Pipe** (SQS source →
  Step Function target) + its role; a **Step Function** (Standard) **state-machine skeleton** (an entry state that
  invokes the provisioner Lambda and a terminal success/failure pair — no per-action logic yet); the **provisioner
  Lambda** infra (placeholder zip + `ignore_changes`, a dispatch/echo handler) + a `deploy-lambdas.yml` matrix row;
  CloudWatch log groups (14-day retention) for the Lambda and the machine
- **Orchestrator role** — the single privileged IAM role the Step Function/Lambda run under, with its **permission
  policy** (`.tftpl`): Glue create/get/delete + table ops; Lake Formation `GrantPermissions`/`RevokePermissions`/
  `GetDataLakeSettings`; S3 on the shared bucket + the admin registry prefix; Cognito
  `AdminUpdateUserAttributes`/`AdminGetUser`/`ListUsers` on the User Pool; `states`/`logs` — scoped to the relevant
  ARNs, non-scopable actions isolated to `"*"` statements (architecture.md trap list), verified with
  `aws iam simulate-custom-policy`. (The role *can* do these things; the *resources/grants* it acts on arrive in
  SPEC-056 + the action specs)
- **New bounded-context module** `infra/modules/shared-spaces/`, **standalone-deployable** like `module.analytics`
  (cross-module ARNs as `compact()`-safe constructed-string locals — architecture.md "unknown ARN in list" trap)
- **Deploy-role IAM** expanded for every new resource type introduced here (SQS queue + DLQ, Pipes, Step Functions,
  the new bucket, the new Lambda + its exec/orchestrator role incl. scoped `iam:PassRole`, the log groups)
- A **control-plane smoke test** (documented in `docs/testing/`): a message placed on the queue reaches the Step
  Function and the Lambda (CloudWatch shows the execution + the echo)

### Out of Scope

- **The access model** — membership Cognito attributes, Identity-Pool principal-tag mappings, the portal-role
  membership-slot statements, `sqs:SendMessage` for the portal role, the shared-results delete-denies, Lake
  Formation registration of the shared bucket, the **request-message contract**, and trusted-actor binding — all
  **SPEC-056**
- **All action semantics** — create / add / remove / leave / delete behavior (SPEC-051→055); the Lambda here only
  dispatches/echoes, it provisions nothing
- **Any browser/UI behavior** (SPEC-051+)
- Changing the **personal**-space model (user-space bucket, `username`-tag scoping, personal Glue DBs) — untouched

---

## Functional Requirements

### FR-001: Shared-space bucket

#### Acceptance Criteria:

- [ ] `dat-prod-shared-space` is created in a new `infra/modules/shared-spaces/` module with the same hygiene as the
  user-space bucket: all public access blocked, SSE-S3, `BucketOwnerEnforced`, versioning **off**, and an
  **abort-incomplete-multipart** lifecycle rule (7-day, SPEC-016)
- [ ] **CORS** allows the app origin (GET/PUT/POST/DELETE/HEAD + required headers) — without it all browser SDK calls
  fail (architecture.md CORS note); no CORS is added to the admin/registry bucket
- [ ] The bucket name is a module variable defaulting to `${project_name}-prod-shared-space` (e.g.
  `dat-prod-shared-space`) and is exported as an output for later app wiring

### FR-002: Registry storage (admin-bucket prefix)

#### Acceptance Criteria:

- [ ] No new bucket for the registry: it lives under `shared-spaces/` in the existing analytics admin bucket
  (SPEC-032); this spec adds whatever module wiring references that bucket
- [ ] The admin bucket's `expire-admin-results` lifecycle rule (currently `filter {}` = all objects,
  `infra/modules/analytics/s3.tf`) is **scoped to exclude** the `shared-spaces/` prefix (add a prefix filter, or a
  dedicated non-expiring rule) so registry objects are retained indefinitely; verify a registry object is not
  subject to expiry
- [ ] Only the **orchestrator role** (and the deploy role) can write `shared-spaces/`; the portal role is **never**
  granted access to the admin bucket (unchanged from SPEC-032)

### FR-003: Control plane (SQS → Pipe → Step Function → Lambda) + orchestrator role

#### Acceptance Criteria:

- [ ] An **SQS** request queue + **DLQ** (redrive `maxReceiveCount`) is created; an **EventBridge Pipe** consumes the
  queue and targets the **Step Function**; the pipe's role can `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes`
  on the queue and `states:StartExecution` on the machine
- [ ] The **Step Function** (Standard) is created with explicit **entry → (Lambda dispatch) → success/failure** states
  (the per-action bodies are filled by SPEC-051→055; here the Lambda is a dispatch/echo skeleton)
- [ ] The **provisioner Lambda** source lives at `lambdas/shared-space-provisioner/shared_space_provisioner.py`
  (Python 3.12, underscores in filename); Terraform owns only the function infra with the placeholder-zip +
  `ignore_changes` pattern, and `deploy-lambdas.yml` gains a matrix row
- [ ] The **orchestrator role** is created with a `.tftpl` permission policy granting exactly what the pipeline will
  need (Glue create/get/delete + tables; LF grant/revoke/get-settings; S3 on the shared bucket + admin registry
  prefix; Cognito `AdminUpdateUserAttributes`/`AdminGetUser`/`ListUsers`; `states`/`logs`), scoped to the relevant
  ARNs with non-scopable actions in their own `"*"` statements (architecture.md offenders), verified with
  `aws iam simulate-custom-policy`
- [ ] CloudWatch log groups (14-day retention, as SPEC-012/033) for the Lambda and the state machine

### FR-004: Deploy-role IAM expansion

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` is extended for every new resource type: SQS (queue + DLQ), Pipes, Step
  Functions (machine + execution), the new bucket (`s3:*` on its ARN as for other buckets), the new Lambda + its
  exec/orchestrator role (incl. scoped `iam:PassRole`), the log groups
- [ ] Non-scopable actions isolated to `"*"` statements; the PR `tofu plan` succeeds with the deploy role; document
  the expected one first-apply self-grant-propagation failure → clean re-run for any first-use-gated resource
  (architecture.md `time_sleep` caveat)

### FR-005: Standalone module + control-plane smoke test

#### Acceptance Criteria:

- [ ] The module is **standalone-deployable** (`compact()`-safe constructed-string locals for any cross-module ARN;
  no unknown-ARN-in-list drop — architecture.md trap)
- [ ] `tofu -chdir=infra validate` + `plan` succeed; IAM scopability for the new actions checked with
  `aws iam simulate-custom-policy`
- [ ] A documented **smoke test** (`docs/testing/e2e.md`): placing a message on the queue drives the
  Pipe → Step Function → Lambda and is observable in CloudWatch (the Lambda echoes/dispatches); no provisioning yet

---

## Data Model

No app types. Infra-level constants/vars:

```hcl
# infra/modules/shared-spaces/variables.tf
variable "shared_space_bucket_name" { default = null }   # → {project_name}-prod-shared-space in root locals
# (max_shared_memberships + the request-message schema are defined in SPEC-056)
```

The registry object + per-user cache **shapes** are defined where they're first written (SPEC-056 / SPEC-051);
this spec creates only the *storage location* (FR-002).

## File & Folder Structure

```
infra/modules/shared-spaces/
├── s3.tf                 # dat-prod-shared-space bucket (+ CORS, lifecycle, hygiene)
├── sqs.tf                # request queue + DLQ
├── pipe.tf               # EventBridge Pipe (SQS → Step Function) + pipe role
├── stepfunction.tf       # state-machine skeleton + orchestrator role + log group
├── lambda.tf             # provisioner function infra (placeholder + ignore_changes)
├── policies/             # .tftpl: orchestrator role, pipe role, sfn execution role
├── variables.tf          # names + cross-module ARNs (constructed-string locals)
└── outputs.tf            # bucket name, queue URL/ARN, orchestrator role ARN, state-machine ARN

lambdas/shared-space-provisioner/
└── shared_space_provisioner.py    # dispatch/echo skeleton (SPEC-051+ add per-action logic)

infra/modules/analytics/s3.tf       # lifecycle rule scoped to exclude shared-spaces/ (FR-002)
infra/modules/base/policies/         # deploy-role expansion (FR-004)
.github/workflows/deploy-lambdas.yml # + shared-space-provisioner matrix row
docs/testing/e2e.md    # control-plane smoke test (FR-005)
```

## Implementation Phases

### Phase 1: Buckets + registry storage

- Module scaffold; shared bucket (FR-001); admin-bucket registry prefix + lifecycle exclusion (FR-002); deploy-role
  IAM for the bucket (FR-004 partial)

#### Checkpoint

`tofu plan/apply` creates `dat-prod-shared-space` with correct hygiene/CORS; a test object under
`<admin-bucket>/shared-spaces/` is **not** expired by the (now prefix-scoped) lifecycle rule. `tofu validate`/`plan` clean.

### Phase 2: Control plane + orchestrator role

- SQS+DLQ, Pipe, Step Function skeleton, orchestrator role + permission policy, provisioner Lambda infra + matrix
  row; remaining deploy-role IAM; smoke test (FR-003, FR-004, FR-005)

#### Checkpoint

(Expect one self-grant re-run.) A message placed on the queue reaches the Step Function and the Lambda (CloudWatch
execution + echo); `simulate-custom-policy` confirms the orchestrator role's scoped actions. Documented in
`docs/testing/e2e.md`.

## Implementation Decisions (in-session, 2026-06-26)

Reversible/technical choices made during build (per `docs/process/session-rhythm.md` — decided in-session, recorded here):

- **FIFO request queue + single `MessageGroupId`** (not a standard queue). The user
  required the control plane to process requests **one at a time, not in parallel**, to
  prevent two users creating the same shared-space name concurrently. The queue is FIFO
  with a constant producer-supplied `MessageGroupId` and the Pipe reads `batch_size = 1`,
  so intake is strictly serial. The Pipe → Standard-state-machine hop is `FIRE_AND_FORGET`
  (Standard machines outlive a synchronous call; user chose Standard over Express to keep
  per-execution history), so the **race-proof** duplicate-name guard is the atomic
  conditional `PutObject` (`If-None-Match: *`) on the registry object — added with the
  create action in **SPEC-051**, not here. `content_based_deduplication = true` absorbs a
  double-click; it is not the correctness guard.
- **One privileged orchestrator role for BOTH the Step Function and the Lambda**
  (trust = `states.amazonaws.com` + `lambda.amazonaws.com`), per FR-003's "the single
  privileged IAM role the Step Function/Lambda run under." A separate SFN execution role
  is folded in; the only other role is the EventBridge Pipe role.
- **FR-002 lifecycle mechanism = prefix-scoped expiry.** S3 lifecycle has no "exclude"; it
  can only *include* a prefix. So the workgroup's fallback `OutputLocation` moved to
  `s3://<admin>/fallback-results/` and `expire-admin-results` now filters
  `prefix = "fallback-results/"`. The `shared-spaces/` registry prefix is simply never
  matched → retained indefinitely.
- **Deploy-role grants split into a second inline policy** (`deploy-policy-shared-spaces`).
  The main `deploy-policy` is already ~8.5k of IAM's 10,240 non-whitespace-char inline
  limit; adding the seven SPEC-050 statements there pushed it to ~11.2k (over). The
  shared-space grants live in their own inline policy on the same role (a role may carry
  multiple inline policies) — also the clean extension point for SPEC-056's additions.
- **Cognito admin actions scoped to `userpool/*`** in the orchestrator policy (one pool;
  avoids a cross-module dependency on `module.auth`'s generated pool ID), mirroring the
  deploy policy's existing `userpool/*` scoping.
- **Module bucket-name var is required (computed in root locals)**, not `default = null`
  as the spec's Data Model sketch showed — matches the established analytics/data
  cycle-free pattern (name computed once in root, passed to both the module and base's
  deploy-policy scope).

## Open Questions

- [x] **Resolved (2026-06-21):** registry **reuses the analytics admin bucket** under `shared-spaces/` (lifecycle
  scoped to exclude it) rather than a new control bucket (`shared-spaces-architecture.md` §4).
- [x] **Resolved (2026-06-21, default):** the control plane is **SQS → EventBridge Pipe → Step Function** (user
  decision); the Step Function invokes a single **provisioner Lambda** with an `action` switch rather than one Lambda
  per action (simpler deploy matrix). Flag if you prefer per-action Lambdas / Step Function-native SDK integrations.
- [x] **Resolved (2026-06-21):** this spec is **foundation only** — the access model + request contract are
  **SPEC-056**, and action semantics are SPEC-051→055 (the original SPEC-050 was split for reviewability).
