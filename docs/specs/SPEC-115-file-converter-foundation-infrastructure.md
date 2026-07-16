# Spec: File Converter — Foundation Infrastructure + Layers + Athena Workgroup

**ID:** SPEC-115
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon` layer + the combined layer-size guard), SPEC-032 (Athena/Glue/Lake Formation foundation), SPEC-088 (the mirrored control-plane precedent), SPEC-066 (the polars-layer packaging approach)

> **Read `docs/file-converter-architecture.md` §0 and §2 first.** This spec builds the plumbing for the file-converter arc (SPEC-115→121); it is deliberately behavior-free.

## Overview

Stand up the **dedicated async control plane** for converting files to Parquet — a FIFO SQS request queue (+ DLQ), an EventBridge Pipe, and a Standard Step Function orchestrating single-task Lambdas around an **Athena `UNLOAD`**, plus an `fccommon` layer, a **polars layer attached to `inspect-source` only**, and a dedicated Athena workgroup. There is a single conversion path — the Athena `UNLOAD` — for every supported format (Excel is deferred entirely; see Out of Scope).

Two pieces of the skeleton are structural decisions that must not be retrofitted, and are therefore in the skeleton on purpose:

**The query polling loop lives in the state machine.** Table-builder's `execute-ddl` polls Athena *inside* a 300-second Lambda (`infra/modules/table-builder/locals.tf:37`) — fine for a `CREATE TABLE`, fatal for an `UNLOAD` of 250 GB. A short Lambda starts the query; the Step Function does the waiting. Standard executions run for up to a year, so the time ceiling disappears.

**The `Catch` always reaches `DropTempTable` — which touches GLUE ONLY, and that is what makes it safe.** The Athena path creates a temporary Glue table. The `Catch` covers **every** state, *including `ValidateAuthorize`* — so whatever that terminal state does, it does on a request whose `destination` may never have been validated and came straight from the message body. An earlier draft had this state **delete "partial output" from that destination**; since every portal user can enqueue, that was an authenticated **cross-user file-delete primitive** (`file-converter-architecture.md` §2.4). The state is now Glue-only and the pipeline holds **no `s3:DeleteObject` anywhere**: the worst a failure path can do is drop a table the pipeline itself created. Partial output after a failed `UNLOAD` is **left in place**; SPEC-118/121 tell the user it may be there and name the path, and SPEC-116's empty-destination rule is the **interlock** that stops them retrying into it.

## Scope

### In Scope

- A new bounded-context module `infra/modules/file-converter/`.
- **FIFO SQS** request queue + **FIFO DLQ** (redrive), content-based dedup **off**.
- An **EventBridge Pipe** (SQS → Step Function, `batch_size = 1`) + its role.
- A **Standard Step Function** skeleton: `ValidateAuthorize → InspectSource → ReconcileSchema → CreateTempTable → StartUnload → [Wait(30s) → CheckQuery → Choice(RUNNING?)] → Finalize → DropTempTable → Succeed`, plus a failure path, with `Retry`/`Catch` scaffolding and a `ParseError` `Pass` state.
- **A `Catch` on every state that routes to `DropTempTable` before `Fail`** — safe on every path precisely **because `DropTempTable` touches Glue only**.
- **Nine placeholder Lambda functions** (`validate-authorize`, `inspect-source`, `reconcile-schema`, `create-temp-table`, `start-unload`, `check-query`, `finalize`, **`drop-temp-table`**, **`notify-failure`**), Python 3.12, placeholder-zip + `ignore_changes`, sharing **one execution role** (`file-converter-orchestrator`). `notify-failure` is provisioned here per the cross-arc convention (mirroring the data-quality foundation) and **wired into the failure path by SPEC-121 FR-003** — a placeholder until then.
- The **`fccommon` layer** (domain helpers, stubbed) and a **dedicated polars layer attached to `inspect-source` only**.
- A **dedicated Athena workgroup** (named per the module convention — FR-003) with `bytes_scanned_cutoff_per_query` **unset**, `enforce_workgroup_configuration = false` (the result location is set **per query**), and a recorded note that the DML query timeout is an **account Service Quota**, not a workgroup field.
- **The Athena DML query-timeout Service Quota increase** — an account/Region quota request (a **support ticket, not Terraform**), raising the 30-minute default toward the 240-minute maximum. It is a **ship-blocking deployment prerequisite** for the arc and is tracked here, in the foundation spec, so it is not discovered at the end.
- CloudWatch **log groups** (14-day).
- **Deploy-role IAM** as a **separate customer-managed policy**, granted in a **PR that applies before** this module's resources.
- A **control-plane smoke test**: message → one execution → the polling loop iterates → terminal, with `DropTempTable` reached on both the success and failure paths.

### Out of Scope

- **Excel (`.xlsx`) conversion — deferred entirely, user decision 2026-07-13.** `.xlsx` is a terminal `unsupported_format` like any other unsupported extension (SPEC-117 FR-001). There is no `convert-excel` Lambda, no `fastexcel` in the polars layer, and no format `Choice` in the state machine.
- Any real logic (token verify, authorization, listing, schema probing, reconciliation, DDL, UNLOAD, finalize) — SPEC-116→119.
- The portal-role `sqs:SendMessage` grant + `VITE_FILE_CONVERTER_QUEUE_URL` — SPEC-116.
- The execution role's **S3** grants and the **`Deny`** — SPEC-116. (There is **no** delete grant to defer: this pipeline holds `s3:DeleteObject` **nowhere**.)
- The execution role's **Glue / Athena / Lake Formation admin** grants — SPEC-118, the spec that first needs them.
- Notifications — SPEC-121. UI — SPEC-120.
- Touching Table Builder's existing polars layer. It stays untouched and lean; this arc gets its own.
- DLQ + `ExecutionsFailed` alarms — delivered by SPEC-121 FR-003.

---

## Functional Requirements

### FR-001: The queue → pipe → state machine, with the polling loop

#### Acceptance Criteria:

- [ ] A FIFO request queue + FIFO DLQ exist with a redrive policy (`maxReceiveCount = 3`); explicit `MessageGroupId` and `MessageDeduplicationId`; content-based dedup **off**.
- [ ] An EventBridge Pipe reads the queue and starts one execution per message (`batch_size = 1`); its role can `states:StartExecution` on exactly this machine and read exactly this queue.
- [ ] The machine contains the states listed in Scope, with placeholder tasks.
- [ ] **`ReconcileSchema` is a separate state BEFORE `CreateTempTable`.** A comment records why: the target schema must be computed **once, globally**, or files would be converted against inconsistent schemas — which is the entire point of the arc.
- [ ] **The success path runs `… → Finalize → DropTempTable → Succeed`, in that order.**
- [ ] **The polling loop is in the state machine, not in a Lambda:** `StartUnload → WaitForQuery (Wait, 30 s) → CheckQuery → Choice`, looping while `QUEUED`/`RUNNING`. A comment records that a Lambda-internal poll cannot survive an `UNLOAD` longer than Lambda's 900 s ceiling, and this arc's will.
- [ ] `Retry` scaffolding on every Task (the four `Lambda.*` errors + `TransientError`).
- [ ] A `States.ALL` `Catch` on every state routes to `ParseError` → **`DropTempTable`** → `Fail`.
- [ ] **`DropTempTable` touches Glue and nothing else.** It does **not** delete S3 objects — not from the destination, not from `_fc-work/`, not anywhere. A comment records the vulnerability this closes: the `Catch` covers **every** state including `ValidateAuthorize`, so a destructive terminal state acts on a `destination` that may **never have been validated** and came straight from the request body — and every portal user holds `sqs:SendMessage` on this queue. Enqueue a garbage token with another user's path as the destination, validation fails, cleanup fires, **their files are gone**: an authenticated cross-user file-delete primitive. Glue-only is what makes the always-reached `Catch` safe (`file-converter-architecture.md` §2.4).
- [ ] A comment records the consequence, so it is not "fixed" back: **partial `UNLOAD` output is NOT removed.** SPEC-121's notification tells the user it may remain and names the path, and SPEC-116's empty-destination rule is the **interlock** that blocks a retry until they clear it — which is what makes it impossible to re-run into a half-populated destination and silently double the data.
- [ ] `DropTempTable` tolerates being reached before any table was created.

### FR-002: Nine placeholder Lambdas on one shared role

#### Acceptance Criteria:

- [ ] Nine Python 3.12 functions exist (names in Scope), each from a placeholder zip with `ignore_changes`.
- [ ] All nine share **one** execution role (`file-converter-orchestrator`); no per-verb roles.
- [ ] **Both** `timeout` **and** `memory_size` are **explicitly set** for each: `validate-authorize` 15 s / 256 MB; `inspect-source` 120 s / 1024 MB; `reconcile-schema` 60 s / 512 MB; `create-temp-table` 60 s / 512 MB; `start-unload` 30 s / 512 MB; `check-query` 15 s / 256 MB; `finalize` 60 s / 512 MB; `drop-temp-table` 60 s / 512 MB; `notify-failure` 15 s / 256 MB.
- [ ] A comment records the precedent precisely: the shared-space verbs set `timeout = 60` but **never set `memory_size`**, leaving it at the AWS default of **128 MB** (`infra/modules/shared-spaces/lambda.tf:46`). It is the **memory** that was left implicit there, not the timeout — and an unset memory tier is invisible in the plan and shows up only as an OOM in production.
- [ ] A comment records that **no function in this arc pulls file bytes through a Lambda** — everything is metadata-weight; Athena does the heavy lifting. (`inspect-source` carries polars, but only to read **headers and footers** — see FR-003.)
- [ ] **`notify-failure` is a placeholder here** — SPEC-121 FR-003 supplies its code and wires it into the failure path. A comment records the cross-arc convention: the function is provisioned in the foundation (as the data-quality arc does) so SPEC-121 is a code + ASL change, not an infra change.
- [ ] Each function + the state machine has a 14-day log group.

### FR-003: The layers and the Athena workgroup

#### Acceptance Criteria:

- [ ] `fccommon` and a **dedicated polars layer** are built + published in CI (mirroring the `tbcommon` / table-builder-polars mechanism at `.github/workflows/deploy-lambdas.yml`).
- [ ] `cpcommon` + `fccommon` attach to all nine functions. The **polars layer attaches to `inspect-source` only** — one function carries three layers, still well within Lambda's limit of five.
- [ ] A comment records why `inspect-source` needs it: it probes **every** file's schema with `polars scan_*().collect_schema()` (SPEC-117 FR-003), and the probe is the source of the target schema — it needs a reader.
- [ ] Layers are attached in a **single** `update-function-configuration --layers` call per function (the call **replaces** the whole list — the existing note in `deploy-lambdas.yml` explains this).
- [ ] Terraform sets `ignore_changes=[layers]` on all nine.
- [ ] The polars layer declares polars **only** — no `fastexcel` (Excel is deferred; see Out of Scope) and no PyJWT/`cryptography` (those live once, in `cpcommon`, per SPEC-107 FR-001).
- [ ] **The SPEC-107 FR-004 combined per-function size guard passes for `inspect-source`** — the one function carrying `cpcommon` + `fccommon` + polars. A comment records that the guard exists precisely so a size breach surfaces in **CI** rather than at deploy.
- [ ] The workgroup is named **`${var.project_name}-${var.environment}-file-converter-wg`** via a `workgroup_name` local, mirroring the module naming convention (`infra/modules/table-builder/locals.tf:9-14`).
- [ ] The workgroup name and the Athena-results prefix are carried to the Lambdas as **`FC_ATHENA_WORKGROUP`** and **`FC_ATHENA_RESULTS_PREFIX`** env vars, **validated at import** in `fccommon.config` (per `lambdas.md` §6); SPEC-118's `lambda.tf` wires them onto the functions that query Athena. See Environment Variables below.
- [ ] A dedicated Athena **workgroup** exists with **`bytes_scanned_cutoff_per_query` unset (null)**. A comment records the disaster this prevents: the existing portal workgroup carries a **10 GiB** scan cutoff as a cost guardrail (`infra/modules/analytics/athena.tf:36`), and a 250 GB conversion is **25× that** — copying the existing module's shape would make **every real conversion fail** with "bytes scanned limit exceeded." The comment also records that this removes the project's only cost guardrail, deliberately.
- [ ] The workgroup sets **`enforce_workgroup_configuration = false`**, and the result location is supplied **per query** via `ResultConfiguration.OutputLocation` on each `StartQueryExecution` — mirroring the existing portal workgroup (`infra/modules/analytics/athena.tf:24-27`). A comment records why: a workgroup has exactly **one static** result location, so routing results into the requesting space's `athenaresults/` prefix is impossible any other way. (It also matters functionally here — SPEC-119's `finalize` reads the `UNLOAD` **data manifest**, which Athena writes to the **query-results** location, not the output location.)
- [ ] A comment on the workgroup records that **there is no workgroup query-timeout setting** — the DML query timeout is an **account/Region Service Quota** (**30 minutes default, 240 minutes maximum, raisable only by a quota-increase request**). Nobody should go looking for the field.
- [ ] The quota increase is **requested, confirmed, and the granted value recorded in the delivery doc** before the arc ships. It is a **ship-blocking prerequisite**, not a config value, and it — not Lambda and not Athena's throughput — is the real ceiling on the feature.

### FR-004: Deploy-role IAM + smoke test

#### Acceptance Criteria:

- [ ] The deploy role can create/update/destroy every new resource type (FIFO SQS + DLQ, Pipe + role, Step Function, the nine Lambdas + shared role + scoped `iam:PassRole`, **both** layers, the Athena workgroup, the log groups).
- [ ] It is a **separate customer-managed policy** (the inline-policy 6,144-char budget is exhausted, `infra/modules/base/iam.tf:134-136`).
- [ ] `states:ValidateStateMachineDefinition` is isolated on `"*"` (not resource-scopable); layer ARNs are granted in both `layer:X` and `layer:X:*` forms; log groups in both bare and `:*` forms for `/aws/lambda/…` and `/aws/vendedlogs/states/…`.
- [ ] The grant **lands and applies in a PR before** the module's resources — **this spec is delivered as TWO PRs, in that order** (`base/iam.tf:145-146`).
- [ ] A smoke test enqueues a minimal message and asserts one execution starts, `ReconcileSchema` runs **before** `CreateTempTable`, the polling loop **provably iterates at least once**, and the machine reaches a terminal state with `DropTempTable` reached on both the success and failure paths.
- [ ] **The placeholder `check-query` returns `RUNNING` on its first invocation and `SUCCEEDED` thereafter** (a counter in the placeholder, or an input flag) — so the smoke test exercises a real loop iteration rather than falling straight through the `Choice`.
- [ ] `tofu -chdir=infra validate` + `plan` succeed; `compact()`-safe cross-module locals.
- [ ] The execution role at this stage has **logs only** — no S3, no SQS, no Glue/Athena/LF. **A plan assertion confirms the rendered policy contains no `s3:DeleteObject` — at this stage or any later one.**

---

## Data Model

```hcl
# infra/modules/file-converter/  (skeleton)
#   sqs.tf            request queue (FIFO) + DLQ + redrive
#   pipe.tf           EventBridge Pipe (SQS → SFN) + role
#   stepfunction.tf   Standard state machine + log group
#   state-machine.asl.json.tftpl
#       validate → inspect → reconcile → CreateTempTable → StartUnload
#                                          → [Wait → CheckQuery → Choice]
#                                          → Finalize → DropTempTable → Succeed / Fail
#       Catch(States.ALL) on EVERY state → ParseError → DropTempTable → Fail.
#       (SPEC-121 FR-003 later inserts NotifyFailure between DropTempTable and Fail.)
#       DropTempTable is GLUE-ONLY: the pipeline holds no s3:DeleteObject anywhere, because
#       the Catch also covers ValidateAuthorize — i.e. an UNvalidated, body-supplied destination.
#   lambda.tf         9 placeholder functions + shared role + log groups + explicit sizing
#                     (memory AND timeout; notify-failure is a placeholder until SPEC-121)
#   layer.tf          fccommon + polars layers (ignore_changes)
#   athena.tf         dedicated workgroup "${var.project_name}-${var.environment}-file-converter-wg":
#                     bytes_scanned_cutoff_per_query UNSET,
#                     enforce_workgroup_configuration = false (result location is per-query).
#                     NOTE: there is no workgroup query-timeout field — it is an account quota.
#   locals.tf         function map { name → {timeout, memory, layers} } + workgroup_name
#                     polars layer → inspect-source ONLY
#   iam.tf / variables.tf / outputs.tf
#   policies/execution.json.tftpl   shared-role policy (logs only at this stage)
```

## Environment Variables

Set on the verb Lambdas (wired by SPEC-118's `lambda.tf`; validated at import in `fccommon.config`):

```
FC_ATHENA_WORKGROUP        # the dedicated workgroup name (FR-003)
FC_ATHENA_RESULTS_PREFIX   # the athenaresults/ prefix used to build each query's
                           # per-space ResultConfiguration.OutputLocation
```

## File & Folder Structure

```
infra/modules/file-converter/…
infra/modules/base/policies/github-actions-deploy-file-converter.json.tftpl   # PR 1
infra/modules/base/iam.tf                                                      # policy + attachment (PR 1)
lambdas/file-converter-common/fccommon/            # stubbed namespaces
lambdas/file-converter-polars/requirements.txt     # polars only → the dedicated layer
lambdas/file-converter-{validate-authorize,inspect-source,reconcile-schema,
                        create-temp-table,start-unload,check-query,
                        finalize,drop-temp-table,notify-failure}/fc_<verb>.py   # placeholders
# ^ Each verb's module is named fc_<verb>.py, NOT a uniform handler.py, and NOT the bare
#   verb name. Two collisions to avoid, both learned the hard way in SPEC-110:
#   (1) pytest flattens every verb dir into ONE module namespace, so nine handler.py files
#       mean the first `import handler` wins for the whole session and a verb's tests
#       silently assert against another verb's module (SPEC-108 shipped that; SPEC-110
#       reversed it — user decision, 2026-07-16);
#   (2) table-builder already owns the bare `inspect_source` / `validate_authorize` module
#       names, so an arc prefix is required (table-share and data-quality both prefix).
#   NOTE: SPEC-116's File & Folder Structure says `validate_authorize.py` — that is the
#   bare name and would collide with table-builder's; it must read `fc_validate_authorize.py`.
.github/workflows/deploy-lambdas.yml                                           # both layers + nine zips
```

## Implementation Phases

### Phase 1 (PR 1): Deploy-role IAM — must apply first

- `github-actions-deploy-file-converter.json.tftpl` + `aws_iam_policy` + attachment, following the table-share shape. Apply and confirm green before Phase 2 lands.

### Phase 2 (PR 2): Module skeleton

- The queue/pipe/SFN skeleton **with `ReconcileSchema` before `CreateTempTable`, the polling loop, and the always-reached `Catch` → `DropTempTable` (Glue-only)**; nine placeholder Lambdas on one role with explicit sizing (memory **and** timeout; `notify-failure` as a placeholder for SPEC-121); both layers (polars on **`inspect-source` only**); the Athena workgroup (**named per FR-003, no scan cutoff**); log groups; the `FC_ATHENA_WORKGROUP` / `FC_ATHENA_RESULTS_PREFIX` outputs.
- Wire both layers + the nine zips into `deploy-lambdas.yml`.

### Phase 3 (PR 2): Size guard + quota + smoke test + completion ritual

- Confirm the SPEC-107 combined size guard passes for `inspect-source`, the one function carrying polars.
- **Request the Athena DML query-timeout quota increase and record the granted value in the delivery doc.** The arc does not ship until it is confirmed.
- Control-plane smoke test: the polling loop iterates (placeholder `check-query` = `RUNNING` first, `SUCCEEDED` thereafter) and `DropTempTable` is reached on both the success and failure paths. Delivery doc, INDEX status, component-inventory rows (the module + both layers).
