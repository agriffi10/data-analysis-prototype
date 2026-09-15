# Spec: Table Builder — Foundation Infrastructure + polars Runtime

**ID:** SPEC-066
**Status:** Completed
**Last Updated:** 2026-06-27
**Depends On:** SPEC-032 (analytics foundation: admin bucket + Athena workgroup + LF bootstrap), SPEC-050 (shared bucket + the control-plane pattern this mirrors), SPEC-012 (Lambda code/infra split + `deploy-lambdas.yml`), SPEC-011 (deploy role + module wiring)

> **Reference:** `docs/table-builder-architecture.md` — read it first. **First of the table-builder arc
> (066 → 067 → 068 → 069 → 070 → 071, + 072 producer).** This spec builds the **plumbing only**: a dedicated
> FIFO control plane (SQS → EventBridge Pipe → Step Function skeleton), the five single-task Lambda **infra
> stubs** each with its own least-privilege role, the **polars Lambda layer**, log groups, the new module, and
> deploy-role IAM. It ships **no request contract and no action logic** — those land in SPEC-067→070. When done,
> a message on the queue flows through the Pipe into the Step Function and reaches the (stub) Lambdas. All IaC is
> OpenTofu; IAM is `.tftpl`; Lambda code/infra are split.

## Overview

Stand up the **dedicated, asynchronous control plane** for creating Glue/Athena tables from a folder of files,
with no user-visible behavior and no provisioning yet. Mirroring the shared-spaces foundation (SPEC-050) and the
dedicated-notifications precedent (SPEC-058), this is a **separate** SQS → EventBridge Pipe → Step Function
pipeline in a new `infra/modules/table-builder/` module — reusing the *pattern*, not the shared-spaces
resources. The Step Function will orchestrate **five single-task Lambdas** (`validate-authorize`,
`check-table-absent`, `inspect-source`, `infer-schema`, `execute-ddl`); this spec creates each function's infra
stub and its **own least-privilege role**, plus the **polars Lambda layer** that the `infer-schema` function
will use (SPEC-069). When this spec is complete, a message placed on the queue drives the Pipe → Step Function →
the (echo/stub) Lambdas — proving the control plane end-to-end — while nothing yet validates a request or creates
a table.

## Scope

### In Scope

- **Dedicated control plane** — a **FIFO SQS** request queue (`.fifo`) + a **FIFO DLQ** (redrive
  `maxReceiveCount`); an **EventBridge Pipe** (SQS source → Step Function target) + its role; a **Step Function**
  (Standard) **state-machine skeleton** that runs the five Lambda **Tasks in sequence** with `Retry`/`Catch`
  scaffolding and terminal **success/recorded-failure** states (the Task bodies are stubs here; per-step logic is
  SPEC-067→070). Queue URL/ARN + state-machine ARN are module outputs.
- **Five single-task Lambda infra stubs** — `validate-authorize`, `check-table-absent`, `inspect-source`,
  `infer-schema`, `execute-ddl`; each source at `lambdas/table-builder-<verb>/<verb>.py` (Python 3.12, underscores
  in filename), each owned by Terraform as **placeholder zip + `ignore_changes`**, each a `deploy-lambdas.yml`
  matrix row, each an echo/dispatch stub for now.
- **Per-verb least-privilege roles** — one execution role **per** Lambda (`.tftpl` permission policies), created
  here with the *shape* each verb will need (refined as actions land): validator (later: registry read + logs),
  checker (Glue GetTable + logs), inspector (S3 list/get on both data buckets + logs), infer (S3 get on both data
  buckets + logs + the polars layer), execute-ddl (Athena run + Glue table ops + S3 read/write + LF + logs). No
  single shared "god" role (`lambdas.md` §7). Trust = `lambda.amazonaws.com`; the SFN execution role may invoke
  the five functions.
- **polars Lambda layer** — a published Lambda layer containing **polars** (Python 3.12, native readers — **no
  pyarrow**), built reproducibly and **published by CI** (`deploy-lambdas.yml` `polars_layer` job; **not** a TF
  `aws_lambda_layer_version` — the artifact is too large to vendor, so it follows the `shared-space-common`
  CI-owned-layer pattern); attached to the `infer-schema` function via `update-function-configuration`
  (TF `ignore_changes=[layers]`), pinned + minimal (`lambdas.md` §12).
- **CloudWatch log groups** (14-day retention, as SPEC-012/033) for each Lambda and the state machine.
- **New bounded-context module** `infra/modules/table-builder/`, **standalone-deployable** like
  `module.analytics`/`module.shared-spaces` (cross-module ARNs as `compact()`-safe constructed-string locals —
  architecture.md "unknown ARN in list" trap).
- **Deploy-role IAM** expanded for every new resource type introduced here (FIFO SQS queue + DLQ, Pipes, Step
  Functions, the five Lambdas + their roles incl. scoped `iam:PassRole`, the **Lambda layer**, the log groups).
- A **control-plane smoke test** (`docs/testing/e2e.md`): a message placed on the queue reaches the
  Step Function and drives the five (stub) Lambdas in order, observable in CloudWatch.

### Out of Scope

- **The request contract + browser enqueue + `validate-authorize` logic** — **SPEC-067** (this spec's validator
  is a stub; portal-role `sqs:SendMessage` + the `VITE_*` queue URL are SPEC-067).
- **All action semantics** — name-uniqueness, source inspection, schema inference, DDL execution — SPEC-068→070
  (the Lambdas here echo/dispatch; they provision nothing). The execute-ddl role's **actual** LF/Glue/Athena/S3
  grants are finalized with SPEC-070 (created here at stub shape).
- **Notifications** emission — SPEC-072 (no `NOTIFICATIONS_QUEUE_URL` wiring here).
- **Any browser/UI behavior** — SPEC-071.
- Changing the personal/shared space, analytics, or notifications infrastructure beyond consuming their ARNs.

---

## Functional Requirements

### FR-001: Dedicated FIFO control plane (SQS → Pipe → Step Function)

#### Acceptance Criteria:

- [ ] A **FIFO SQS** request queue (`.fifo`) + a **FIFO DLQ** (redrive `maxReceiveCount`, e.g. 3) is created in a
  new `infra/modules/table-builder/` module; queue URL + ARN are module outputs.
- [ ] An **EventBridge Pipe** consumes the queue (**batch size 1**) and targets the **Step Function**; the pipe's
  role can `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on the queue and `states:StartExecution` on
  the machine. (Intake is serial per `MessageGroupId`; the producer sets it = target database — SPEC-067.
  **Superseded 2026-09-15: intake orders the starts only, and the runs overlap —
  `docs/decisions/control-planes.md`, *A group id orders the STARTS, not the runs*.**)
- [ ] The **Step Function** (Standard) is created with explicit states wiring the five Lambda Tasks **in order**
  (`validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl`) plus `Retry`/`Catch`
  scaffolding and terminal **succeed** / **recorded-failure** states; here every Task invokes a **stub** Lambda
  (per-step bodies are SPEC-067→070).

### FR-002: Five single-task Lambdas + per-verb roles

#### Acceptance Criteria:

- [ ] Five function sources exist at `lambdas/table-builder-validate-authorize/validate_authorize.py`,
  `…-check-table-absent/check_table_absent.py`, `…-inspect-source/inspect_source.py`,
  `…-infer-schema/infer_schema.py`, `…-execute-ddl/execute_ddl.py` (Python 3.12; echo/dispatch stubs); Terraform
  owns each as placeholder-zip + `ignore_changes`; `deploy-lambdas.yml` gains a matrix row per function.
- [ ] Each Lambda has its **own** execution role with a `.tftpl` permission policy scoped to that verb's needs
  (`lambdas.md` §7) — **no shared broad role**; non-scopable actions isolated to their own `"*"` statements
  (architecture.md trap list), verified with `aws iam simulate-custom-policy`.
- [ ] Per-function **timeout/memory** are set to the task's real need (a small validator ≠ the polars infer step)
  rather than one inherited default (`lambdas.md` §4).

### FR-003: polars Lambda layer

#### Acceptance Criteria:

- [ ] A Lambda **layer** containing **polars** (Python 3.12, native readers, **no pyarrow**) is built reproducibly
  with a pinned version (`requirements`) and minimal contents (`lambdas.md` §12); the layer is **built + published
  in CI** (`deploy-lambdas.yml`) with linux/cp312 manylinux wheels for ABI compatibility (not a hand-vendored
  artifact). **Decided (SPEC-066, 2026-06-30):** the layer is **CI-owned, not a Terraform `aws_lambda_layer_version`
  resource** — mirroring `shared-space-common`. The 100 MB+ polars artifact can't be vendored into the repo for a
  TF-built zip, and the repo's code/infra split has **CI own code + layers** while TF owns function infra +
  `ignore_changes=[layers]`. The function attaches the published version via `update-function-configuration`;
  Terraform constructs only the layer **name** (a module local/output), consistent with architecture.md §4's
  "consistent with the repo's existing packaging."
- [ ] The layer is attached **only** to the `infer-schema` function; the other four functions do not carry it
  (lean cold starts).
- [ ] The packaged layer is within the Lambda **250 MB unzipped** limit together with the function code (verified
  at build); document the measured size in `docs/testing/e2e.md`.

### FR-004: Log groups + deploy-role IAM + standalone module

#### Acceptance Criteria:

- [ ] CloudWatch log groups (14-day retention) exist for each of the five Lambdas and the state machine.
- [ ] `infra/modules/base/policies/` is extended for every new resource type: FIFO SQS (queue + DLQ), Pipes, Step
  Functions (machine + execution), the five Lambdas + their roles (incl. scoped `iam:PassRole` for exactly those
  roles the SFN/pipe pass), the **Lambda layer** (`lambda:PublishLayerVersion` etc.), the log groups. Given the
  deploy policy's inline-size limit (SPEC-050 note), add these in a **dedicated inline policy**
  (`deploy-policy-table-builder`).
- [ ] Non-scopable actions isolated to `"*"` statements; document the expected first-apply
  self-grant-propagation failure → clean re-run (architecture.md `time_sleep` caveat).
- [ ] The module is **standalone-deployable** (`compact()`-safe constructed-string locals for cross-module ARNs —
  the data + shared buckets, admin bucket, Athena workgroup, catalog); `tofu -chdir=infra validate` + `plan`
  succeed.

### FR-005: Control-plane smoke test

#### Acceptance Criteria:

- [ ] `docs/testing/e2e.md` documents: a message placed on the FIFO queue (with a `MessageGroupId`)
  drives the Pipe → Step Function and runs the five stub Lambdas in order, observable in CloudWatch (each echoes);
  no table is created. The measured polars-layer size is recorded (FR-003).

---

## Data Model

No app types. Infra-level vars (the request-message schema is defined in SPEC-067):

```hcl
# infra/modules/table-builder/variables.tf
variable "user_space_bucket_arn"   {}                 # constructed-string local from root
variable "shared_space_bucket_arn" {}                 # constructed-string local from root
variable "admin_bucket_arn"        {}                 # registry reads (SPEC-067) + Athena results
variable "athena_workgroup"        {}                 # SPEC-032 workgroup for execute-ddl (SPEC-070)
variable "dlq_max_receive_count"   { default = 3 }
# FIFO queue (.fifo); MessageGroupId = target database (set by the producer, SPEC-067).
```

## API / Interface Contract

```hcl
# infra/modules/table-builder/outputs.tf
output "table_build_queue_url"  { value = aws_sqs_queue.requests.url }   # → VITE_TABLE_BUILD_QUEUE_URL (SPEC-067); ends in .fifo
output "table_build_queue_arn"  { value = aws_sqs_queue.requests.arn }   # → portal-role SendMessage (SPEC-067)
output "state_machine_arn"      { value = aws_sfn_state_machine.table_builder.arn }
output "polars_layer_name"      { value = local.polars_layer_name }   # CI publishes the version ARN (not a TF resource)
# + the five Lambda function names/ARNs for the deploy matrix
```

## Environment Variables

No new `VITE_*` here — the queue URL is **exported** and consumed (`VITE_TABLE_BUILD_QUEUE_URL`) in SPEC-067.

## File & Folder Structure

```
infra/modules/table-builder/
├── sqs.tf                # FIFO request queue (.fifo) + FIFO DLQ (+ redrive)
├── pipe.tf               # EventBridge Pipe (SQS → Step Function) + pipe role
├── stepfunction.tf       # linear state-machine (5 Tasks in sequence + Retry/Catch + terminal states) + SFN role + log group
├── state-machine.asl.json.tftpl
├── lambda.tf             # 5 function infra stubs (placeholder + ignore_changes=[…,layers]) + log groups
├── iam.tf                # per-verb roles + sfn role + pipe role wiring
├── locals.tf             # constructed names + ARNs (incl. polars layer NAME; CI publishes the version)
├── policies/             # .tftpl: one permission policy per verb role + pipe role + sfn role + trust policies
├── variables.tf          # names + cross-module ARNs (constructed-string locals)
└── outputs.tf            # queue URL/ARN, state-machine ARN, polars layer name, function names
# NOTE: no layer.tf — the polars layer is CI-built/published (deploy-lambdas.yml), not a TF aws_lambda_layer_version.

lambdas/table-builder-validate-authorize/validate_authorize.py   # stub (SPEC-067)
lambdas/table-builder-check-table-absent/check_table_absent.py   # stub (SPEC-068)
lambdas/table-builder-inspect-source/inspect_source.py           # stub (SPEC-068)
lambdas/table-builder-infer-schema/infer_schema.py               # stub (SPEC-069; uses polars layer)
lambdas/table-builder-execute-ddl/execute_ddl.py                 # stub (SPEC-070)
lambdas/table-builder-common/                                    # shared module/layer for auth/clients/notify (filled by SPEC-067+)

infra/modules/base/policies/          # deploy-role expansion (FR-004) — deploy-policy-table-builder
.github/workflows/deploy-lambdas.yml  # + 5 matrix rows + polars layer build step
docs/testing/e2e.md     # control-plane smoke test (FR-005)
```

## Implementation Phases

### Phase 1: Module + queue + state-machine skeleton + stubs

- Module scaffold; FIFO queue + DLQ; Pipe + role; Step Function skeleton (5 Tasks + Retry/Catch + terminal
  states) + SFN role; five Lambda infra stubs + roles + log groups + `deploy-lambdas.yml` rows; deploy-role IAM
  for these types (FR-001, FR-002, FR-004 partial).

### Phase 2: polars layer + smoke test

- Build + publish the polars layer; attach to `infer-schema`; add the layer build to the deploy flow; finish
  deploy-role IAM (layer); document the smoke test + measured layer size (FR-003, FR-004, FR-005).
