# Spec: Data Quality — Foundation Infrastructure + `dqcommon` Layer + Athena Workgroup

**ID:** SPEC-108
**Status:** Completed
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon` layer), SPEC-032 (Athena/Glue/Lake Formation foundation), SPEC-088 (the mirrored control-plane precedent)

> **Read `docs/data-quality-architecture.md` §0 and §2 first.** This spec builds the plumbing for the data-quality arc (SPEC-108→114); it is deliberately behavior-free.

## Overview

Stand up the **dedicated async control plane** for checking data quality — a FIFO SQS request queue (+ DLQ), an EventBridge Pipe, and a Standard Step Function that will orchestrate single-task Lambdas around an **Athena query**, plus a `dqcommon` Lambda layer and a dedicated Athena workgroup. This spec delivers the **skeleton only**: infrastructure, one shared execution role, placeholder Lambdas, log groups, deploy-role IAM, and a smoke test.

Two pieces of the skeleton are structural decisions that must not be retrofitted later, and are therefore in the skeleton on purpose:

**The query polling loop lives in the state machine.** Table-builder's `execute-ddl` polls Athena *inside* a 300-second Lambda (`infra/modules/table-builder/locals.tf:37`) — fine for a `CREATE TABLE` that returns in seconds, fatal for a profiling query over 250 GB that runs for minutes to tens of minutes. Here, a short Lambda **starts** the query and the Step Function does the waiting (`Wait → check-query → Choice`). Standard executions run for up to a year, so the time ceiling disappears entirely. This is the whole reason the arc works.

**The `Catch` always reaches cleanup.** The pipeline creates temporary Glue tables. If a failure path can skip `drop-temp-tables`, every failed request leaks a table into the user's database — visible in the Query workspace's schema rail, and eventually colliding with their real table names.

## Scope

### In Scope

- A new bounded-context module `infra/modules/data-quality/`.
- **FIFO SQS** request queue + **FIFO DLQ** (redrive policy), content-based dedup **off** (the producer sends an explicit `MessageDeduplicationId` — SPEC-109 sets it).
- An **EventBridge Pipe** (SQS source → Step Function target, `batch_size = 1`, fire-and-forget) + its role.
- A **Standard Step Function** skeleton containing the **canonical target state list** (Data Model below — success and failure paths in full, including `RecordSuccess`, `RecordFailure` and `NotifyFailure`), with `Retry`/`Catch` scaffolding and a `ParseError` `Pass` state (mirroring `infra/modules/table-builder/state-machine.asl.json.tftpl`). Later specs **wire** these states to real logic; no later spec introduces a new state.
- **A `Catch` on every state that routes to `DropTempTables` before `Fail`** — cleanup runs on the failure path too.
- **Nine placeholder Lambda functions** (`validate-authorize`, `inspect-source`, `create-temp-tables`, `start-profile-query`, `check-query`, `byte-scan`, `assemble-report`, `drop-temp-tables`, and `notify-failure` — the failure-path emitter SPEC-114 wires), Python 3.12, placeholder-zip + `ignore_changes=[filename,...]`, sharing **one execution role** (`data-quality-orchestrator`).
- The **`dqcommon` Lambda layer** — CI-built + published, attached to all nine functions **alongside `cpcommon`**; namespaces stubbed for later specs. `dqcommon` itself declares **no polars and no Excel engine** — every heavy computation is Athena's.
- A **polars layer (no Excel engine) attached to `inspect-source` only** — it must read Parquet footers, because Athena requires an **explicit column list** for a Parquet or JSON external table and does not auto-detect one (`data-quality-architecture.md` §7.3).
- A **dedicated Athena workgroup** with `bytes_scanned_cutoff_per_query` **unset**, `enforce_workgroup_configuration = false` (the result location is set **per query**), and a recorded note that the DML query timeout is an **account Service Quota**, not a workgroup field.
- **The Athena DML query-timeout Service Quota increase** — an account/Region quota request (a **support ticket, not Terraform**), raising the 30-minute default toward the 240-minute maximum. It is a **ship-blocking deployment prerequisite** for the arc and is tracked here, in the foundation spec, so it is not discovered at the end.
- CloudWatch **log groups** (14-day retention) for each function + the state machine.
- **Deploy-role IAM** expanded for every new resource type, as a **separate customer-managed policy**, granted in a **PR that applies before** this module's resources.
- A **control-plane smoke test**: enqueue a minimal message → assert one execution starts, the polling loop iterates at least once, and the machine reaches a terminal state through the placeholder path.

### Out of Scope

- Any real logic (token verify, authorization, listing, DDL, the profile query, the byte scan, report assembly) — SPEC-109→112.
- The portal-role `sqs:SendMessage` grant + `VITE_DATA_QUALITY_QUEUE_URL` + browser enqueue — SPEC-109.
- The execution role's **S3** grants and the **`Deny`** on protected objects — SPEC-109.
- The execution role's **Glue / Athena / Lake Formation admin** grants — SPEC-111, the spec that first needs them. This spec gives the role only what the placeholder path + logging need.
- Notifications — SPEC-114. UI + the report view — SPEC-113.
- A DLQ alarm — a known cross-cutting gap across every control-plane module; inherited, not introduced here.

---

## Functional Requirements

### FR-001: The queue → pipe → state machine, with the polling loop

#### Acceptance Criteria:

- [ ] A FIFO request queue + FIFO DLQ exist with a redrive policy (`maxReceiveCount = 3`); the queue accepts messages carrying an explicit `MessageGroupId` and `MessageDeduplicationId`; content-based dedup is **off**.
- [ ] **Names follow the table-builder convention** (`infra/modules/table-builder/locals.tf` — constructed strings, known at plan time): the queue is **`${project_name}-${environment}-data-quality-requests.fifo`**, the DLQ **`${project_name}-${environment}-data-quality-requests-dlq.fifo`**, the state machine **`${project_name}-${environment}-data-quality-orchestrator`**. SPEC-109's `.env.example` sample quotes the queue name; it must match this.
- [ ] An EventBridge Pipe reads the queue and starts one Step Function execution per message (`batch_size = 1`); its role can `states:StartExecution` on exactly this machine and read exactly this queue.
- [ ] The Standard Step Function contains **every state in the canonical list** (Data Model below), with placeholder tasks — later specs wire them, none adds a state.
- [ ] **The polling loop is in the state machine, not in a Lambda:** `StartProfileQuery` → `WaitForQuery` (`Wait`, 30 s) → `CheckQuery` (Task) → `Choice` on the returned status, looping back to `WaitForQuery` while `RUNNING`/`QUEUED` and proceeding on `SUCCEEDED`. A rationale comment records that a Lambda-internal poll (table-builder's `execute-ddl` pattern) cannot survive a query longer than its 900 s ceiling.
- [ ] `Retry` scaffolding on every Task (`Lambda.ServiceException`, `Lambda.TooManyRequestsException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `TransientError`).
- [ ] A `States.ALL` `Catch` on every state routes to a `ParseError` `Pass` state and then to **`DropTempTables`**, and only then to `Fail`. A comment records the disaster this prevents: a leaked temp table in the user's Glue database, visible in the Query schema rail.
- [ ] `DropTempTables` is idempotent-by-design in the skeleton (it must tolerate being reached before any table was created).

### FR-002: Nine placeholder Lambdas on one shared role

#### Acceptance Criteria:

- [ ] Nine Python 3.12 functions exist (names in Scope), each deployed from a placeholder zip with `ignore_changes` so CI owns the code artifact.
- [ ] All nine share **one** execution role (`data-quality-orchestrator`); no per-verb roles (matching table-builder and table-share).
- [ ] **Both** `timeout` **and** `memory_size` are **explicitly set** for each: `validate-authorize` 15 s / 256 MB; `inspect-source` 120 s / 1024 MB; `create-temp-tables` 60 s / 512 MB; `start-profile-query` 30 s / 512 MB; `check-query` 15 s / 256 MB; `byte-scan` 300 s / 1024 MB; `assemble-report` 120 s / 1024 MB; `drop-temp-tables` 60 s / 512 MB; `notify-failure` 15 s / 256 MB.
- [ ] `notify-failure` is a **placeholder here** — its real handler and the `NotifyFailure` state wiring are SPEC-114 FR-004. Provisioning it in the foundation (function, log group, deploy-lambdas matrix entry) is the notify-failure-Lambda pattern: the foundation spec provisions the placeholder, the producer spec wires it.
- [ ] A comment records the precedent precisely: the shared-space verbs set `timeout = 60` but **never set `memory_size`**, leaving it at the AWS default of **128 MB** (`infra/modules/shared-spaces/lambda.tf:46`). It is the **memory** default that was left implicit there, not the timeout — and an unset memory tier is invisible in the plan and only shows up as an OOM in production.
- [ ] A comment records that **no verb in this arc streams bulk data** — Athena does the heavy work — which is why nothing here needs the maximum timeout or memory tier. `byte-scan` is the only function that touches file bytes, and its budget is bounded **per request** (`DQ_SCAN_TOTAL_BYTES`, default 2 GiB — SPEC-112 FR-001), which is what 300 s / 1024 MB is sized against. A **per-file** budget would need ~920 MB/s of sustained throughput and is impossible; a comment says so.
- [ ] Each function + the state machine has a 14-day CloudWatch log group.

### FR-003: The layers and the Athena workgroup

#### Acceptance Criteria:

- [ ] `dqcommon` is built + published in CI (mirroring `tscommon`) and attached to all nine functions **together with `cpcommon`** in one `update-function-configuration --layers` call per function (the call **replaces** the whole list — see the note in `deploy-lambdas.yml`).
- [ ] Terraform sets `ignore_changes=[layers]` on all nine functions.
- [ ] `dqcommon` itself declares **no polars and no Excel engine**, and does **not** declare PyJWT/`cryptography` (those live once, in `cpcommon`, per SPEC-107 FR-001). Its namespaces (`config`, `sql`, `report`, `messages` — SPEC-114, `index_store` — SPEC-123) are stubbed for the later specs.
- [ ] Config style is settled here for the arc: **per-deployment values** (queue URLs, the workgroup name, the results prefix) are **env vars validated at import** (the SPEC-083 pattern); **`DQ_*` tuning caps are module constants in `dqcommon.config`**.
- [ ] A **dedicated polars layer (polars only — no `fastexcel`, this arc does not support Excel)** is built + published in CI and attached to **`inspect-source`** — and to no other function. A comment records why the layer is unavoidable: **Athena requires an explicit column list for Parquet and JSON external tables and does not auto-detect a Parquet schema**, so that list must come from `inspect-source`'s per-file probe, and reading a Parquet footer needs a Parquet reader. Claiming "this arc needs no polars" would make its own Parquet support (SPEC-110 FR-002) impossible to build.
- [ ] The SPEC-107 FR-004 **combined per-function size guard** passes for all nine functions — and it is `inspect-source`, the one function carrying `cpcommon` + `dqcommon` + polars, that the guard actually has to work for. A comment says so, so the guard is not dismissed as ceremony.
- [ ] A dedicated Athena **workgroup** exists for this pipeline, named **`${project_name}-${environment}-data-quality-wg`** (the same constructed-name convention as every other resource here; cf. the portal's `${project_name}-prod-portal-wg`), with **`bytes_scanned_cutoff_per_query` unset (null)**. A comment records the disaster this prevents: the existing portal workgroup carries a **10 GiB** scan cutoff as a cost guardrail (`infra/modules/analytics/athena.tf:36`), and a 250 GB check is **25× that** — copying the existing module's shape would make **every real check fail** with "bytes scanned limit exceeded." The comment also records that this removes the project's only cost guardrail, deliberately.
- [ ] The workgroup sets **`enforce_workgroup_configuration = false`**, and the result location is supplied **per query** via `ResultConfiguration.OutputLocation` on each `StartQueryExecution` — mirroring the existing portal workgroup (`infra/modules/analytics/athena.tf:24-27`). A comment records why: a workgroup has exactly **one static** result location, so routing results into the *requesting space's* `athenaresults/` prefix is impossible any other way.
- [ ] A comment on the workgroup records that **there is no workgroup query-timeout setting** — the DML query timeout is an **account/Region Service Quota** (**30 minutes default, 240 minutes maximum, raisable only by a quota-increase request**). Nobody should go looking for the field.
- [ ] The quota increase is **requested, confirmed, and the granted value recorded in the delivery doc** before the arc ships. It is a **ship-blocking prerequisite**, not a config value, and it — not Athena's throughput — is the real ceiling on the feature.

### FR-004: Deploy-role IAM + smoke test

#### Acceptance Criteria:

- [ ] The deploy role can create/update/destroy every new resource type here (FIFO SQS + DLQ, Pipe + role, Step Function, the nine Lambdas + shared role + scoped `iam:PassRole`, **both** layers (`dqcommon` + polars), the Athena workgroup, the log groups).
- [ ] The grant is a **separate customer-managed policy** (`aws_iam_policy` + attachment), not an inline addition — the deploy role's inline-policy 6,144-char budget is exhausted (`infra/modules/base/iam.tf:134-136`).
- [ ] `states:ValidateStateMachineDefinition` is isolated in its own statement on `"*"` (it is not resource-scopable).
- [ ] Log-group ARNs are granted in **both** bare and `:*` forms, for both `/aws/lambda/…` and `/aws/vendedlogs/states/…`.
- [ ] The IAM grant **lands and applies in a PR before** the module's resources (the deploy-perms-before-resources rule, `base/iam.tf:145-146`) — **this spec is delivered as TWO PRs, in that order.**
- [ ] A smoke test enqueues a minimal well-formed message and asserts exactly one execution starts, the `Wait`/`CheckQuery`/`Choice` loop iterates at least once against a stubbed status, and the machine reaches a terminal state via the placeholder path. **The test message is sent with the deploy role's credentials** — the portal-role `sqs:SendMessage` grant is SPEC-109's, not this spec's.
- [ ] `tofu -chdir=infra validate` + `plan` succeed; the module is standalone-deployable with `compact()`-safe cross-module locals.
- [ ] The execution role at this stage has **logs only** — no S3, no SQS, no Glue/Athena/LF (those arrive in SPEC-109 and SPEC-111).

---

## Data Model

**The canonical target state list.** This is the machine's full, final shape — the skeleton contains every state below as a placeholder, and later specs **wire** them (annotated per state); no later spec adds or renames a state.

```text
Success path:
  ValidateAuthorize        (Task  — wired real in SPEC-109)
  → InspectSource          (Task  — SPEC-110)
  → CreateTempTables       (Task  — SPEC-111)
  → StartProfileQuery      (Task  — SPEC-111)
  → WaitForQuery           (Wait, 30 s — the polling loop; SPEC-111 drives it against real queries)
  → CheckQuery             (Task  — SPEC-111)
  → Choice(any QUEUED/RUNNING?) → WaitForQuery | ByteScan
  → ByteScan               (Task  — SPEC-112)
  → AssembleReport         (Task  — SPEC-112)
  → DropTempTables         (Task  — SPEC-111; idempotent)
  → RecordSuccess          (Pass  — SPEC-112 shapes it)
  → Succeed

Failure path (every state's Catch):
  Catch → ParseError       (Pass  — skeleton)
  → DropTempTables         (SPEC-111; cleanup runs on failure too — whether this is the shared
                            state or an …OnFailure twin invoking the same Lambda is an ASL detail)
  → RecordFailure          (Pass  — SPEC-112 shapes it)
  → NotifyFailure          (Task  — SPEC-114 wires it to the `notify-failure` Lambda provisioned here)
  → Fail
```

```hcl
# infra/modules/data-quality/  (skeleton)
#   sqs.tf            request queue (FIFO) + DLQ (FIFO) + redrive
#                     names: {project}-{env}-data-quality-requests.fifo / …-requests-dlq.fifo
#   pipe.tf           EventBridge Pipe (SQS → SFN) + role
#   stepfunction.tf   Standard state machine ({project}-{env}-data-quality-orchestrator) + log group
#   state-machine.asl.json.tftpl   the canonical state list above, as placeholders
#   lambda.tf         9 placeholder functions + shared execution role + log groups
#   layer.tf          dqcommon layer + polars layer (inspect-source only); ignore_changes
#   athena.tf         dedicated workgroup {project}-{env}-data-quality-wg:
#                     bytes_scanned_cutoff_per_query UNSET,
#                     enforce_workgroup_configuration = false (result location is per-query).
#                     NOTE: there is no workgroup query-timeout field — it is an account quota.
#   locals.tf         function map { name → {timeout, memory, layers} }
#   iam.tf            role + policy attachments
#   policies/execution.json.tftpl   shared-role policy (logs only at this stage)
#   variables.tf / outputs.tf       queue URL/ARN, state machine ARN, role ARN (compact()-safe)
```

## File & Folder Structure

```
infra/modules/data-quality/…                                                   # the module above
infra/modules/base/policies/github-actions-deploy-data-quality.json.tftpl      # PR 1
infra/modules/base/iam.tf                                                      # aws_iam_policy + attachment (PR 1)
lambdas/data-quality-common/dqcommon/                                          # stubbed namespaces (dqcommon itself declares no polars)
lambdas/data-quality-polars/requirements.txt                                   # polars only (no fastexcel) → inspect-source's layer
lambdas/data-quality-{validate-authorize,inspect-source,create-temp-tables,
                      start-profile-query,check-query,byte-scan,
                      assemble-report,drop-temp-tables,notify-failure}/dq_<verb>.py  # placeholders (notify-failure wired in SPEC-114)
# ^ Each verb's module is named dq_<verb>.py, NOT a uniform handler.py (SPEC-110 reversed
#   that — user decision, 2026-07-16). pytest flattens every verb dir into ONE module
#   namespace, so nine handler.py files mean the first `import handler` wins for the whole
#   session and a verb's tests silently assert against another verb's module. The dq_
#   prefix is needed because table-builder already owns the bare `inspect_source` /
#   `validate_authorize` names (table-share prefixes for the same reason).
.github/workflows/deploy-lambdas.yml                                           # build/publish dqcommon + the polars layer + the nine zips
```

## Implementation Phases

### Phase 1 (PR 1): Deploy-role IAM — must apply first

- New `github-actions-deploy-data-quality.json.tftpl` + `aws_iam_policy` + attachment in `base/iam.tf`, following the table-share shape (`ValidateStateMachineDefinition` isolated; layer ARNs in both forms; `PassRole` scoped; log groups in both forms).
- Apply and confirm green **before** Phase 2 lands.

### Phase 2 (PR 2): Module skeleton

- The FIFO queue+DLQ, Pipe, Standard SFN skeleton **including the polling loop and the always-cleanup `Catch`** (the full canonical state list), nine placeholder Lambdas on one role with explicit sizing (memory **and** timeout), the `dqcommon` layer, the polars layer, the Athena workgroup (**no scan cutoff**), log groups.
- Wire `dqcommon` + the polars layer + the nine zips into `deploy-lambdas.yml`; attach `cpcommon` + `dqcommon` to every function, and `cpcommon` + `dqcommon` + polars to `inspect-source`, in **one** `--layers` call per function.

### Phase 3 (PR 2): Size guard + quota + smoke test + completion ritual

- Confirm the SPEC-107 combined size guard passes — in particular for `inspect-source`, the only function carrying the polars layer.
- **Request the Athena DML query-timeout quota increase and record the granted value in the delivery doc.** The arc does not ship until it is confirmed.
- Control-plane smoke test (message → one execution → the polling loop iterates → terminal, with cleanup reached on both paths).
- Delivery doc, INDEX status, component-inventory rows (the module + the `dqcommon` layer + the polars layer).
