# Spec: Table Share — Foundation Infrastructure + Common Layer

**ID:** SPEC-088
**Status:** Draft
**Last Updated:** 2026-07-04
**Depends On:** SPEC-050 (control-plane pattern), SPEC-066 (table-builder foundation — the mirrored precedent), SPEC-032 (analytics buckets/workgroup/LF)

> **Read `docs/table-share-architecture.md` first.** This spec builds the plumbing for the table-share arc (SPEC-088→094); it is deliberately behavior-free.

## Overview

Stand up the **dedicated async control plane** for sharing a table across databases — a FIFO SQS request queue (+ DLQ), an EventBridge Pipe, and a Standard Step Function that will orchestrate five single-task Lambdas over a recipient `Map`, plus a shared `table-share-common` Lambda layer. This spec delivers the **skeleton only**: infrastructure, one shared execution role, placeholder Lambdas, log groups, deploy-role IAM, and a smoke test proving a message flows queue → pipe → state machine. No validation, copy, or table-creation logic — those land in SPEC-089→092.

## Scope

### In Scope

- A new bounded-context module `infra/modules/table-share/`.
- **FIFO SQS** request queue + **FIFO DLQ** (redrive policy), content-based dedup off (explicit `MessageDeduplicationId`), `MessageGroupId` = source `database.table` (SPEC-089 sets it; queue just supports FIFO).
- An **EventBridge Pipe** (SQS source → Step Function target) + its role.
- A **Standard Step Function** skeleton: an entry state → a `Map` state over `recipients` with placeholder task states → `Succeed`/`Fail`, with `Retry`/`Catch` scaffolding.
- **Five placeholder Lambda functions** (`validate-authorize`, `inspect-source`, `check-target-absent`, `copy-objects`, `create-table`), Python 3.12, placeholder-zip + `ignore_changes=[filename,...]`, sharing **one execution role** (`table-share-orchestrator`).
- The **`table-share-common` (`tscommon`) Lambda layer** — CI-built + published, attached to all five functions; ships with the shared helper *namespaces* stubbed (config/clients/auth/registry/copy/notify) so later specs fill them in.
- CloudWatch **log groups** (14-day retention) for each function + the state machine.
- **Deploy-role IAM** expanded for every new resource type (FIFO SQS + DLQ, Pipes, Step Functions, the five Lambdas + shared role incl. scoped `iam:PassRole`, the Lambda layer, log groups).
- A **control-plane smoke test**: enqueue a minimal message → assert one Step Function execution starts and reaches a terminal state through the placeholder path.

### Out of Scope

- Any real action logic (token verify, authorization, source inspection, copy, DDL) — SPEC-089→092.
- The portal-role `sqs:SendMessage` grant + `VITE_TABLE_SHARE_QUEUE_URL` + browser enqueue — SPEC-089.
- The execution role's **LF admin / Glue / Athena / S3 / Cognito** grants — added by the spec that first needs each (SPEC-089/090/092); this spec gives the role only what the placeholder path + logging need.
- Notifications wiring — SPEC-094.
- UI — SPEC-093.

---

## Functional Requirements

### FR-001: The dedicated queue → pipe → state machine

#### Acceptance Criteria:

- [ ] A FIFO request queue + FIFO DLQ exist with a redrive policy (maxReceiveCount small, e.g. 3); the queue accepts messages with an explicit `MessageGroupId` and `MessageDeduplicationId`.
- [ ] An EventBridge Pipe reads the queue and starts a Step Function execution per message; its role can `states:StartExecution` on exactly this machine and read the queue.
- [ ] The Standard Step Function has an entry state, a `Map` over an input `recipients` array with placeholder task states, and terminal `Succeed`/`Fail`; `Retry`/`Catch` scaffolding is present (no real error taxonomy yet).

### FR-002: Five placeholder Lambdas on one shared role + the common layer

#### Acceptance Criteria:

- [ ] Five Python 3.12 functions exist (`validate-authorize`, `inspect-source`, `check-target-absent`, `copy-objects`, `create-table`), each deployed from a placeholder zip with `ignore_changes` so CI owns the code artifact.
- [ ] All five share **one** execution role (`table-share-orchestrator`); no per-verb roles.
- [ ] The `table-share-common` layer is built + published in CI (mirroring `shared-space-common` / `tbcommon`) and attached to all five functions; TF `ignore_changes=[layers]`.
- [ ] Each function + the state machine has a 14-day CloudWatch log group.

### FR-003: Deploy-role IAM + smoke test

#### Acceptance Criteria:

- [ ] The deploy role can create/update/destroy every new resource type here (FIFO SQS + DLQ, Pipe + role, Step Function, the five Lambdas + shared role + scoped `iam:PassRole`, the layer, the log groups).
- [ ] A smoke test enqueues a minimal well-formed message and asserts exactly one execution starts and reaches a terminal state via the placeholder path.
- [ ] `tofu -chdir=infra validate` + `plan` succeed; the module is standalone-deployable with `compact()`-safe cross-module locals.

---

## Data Model

```hcl
# infra/modules/table-share/  (skeleton)
#   sqs.tf         request queue (FIFO) + DLQ (FIFO) + redrive
#   pipe.tf        EventBridge Pipe (SQS → SFN) + role
#   sfn.tf         Standard state machine (entry → Map(placeholder) → Succeed/Fail)
#   lambdas.tf     5 placeholder functions + shared execution role + log groups
#   layer.tf       table-share-common layer (published artifact, ignore_changes)
#   policies/execution.json.tftpl   shared-role policy (logs only at this stage)
#   outputs.tf     queue URL/ARN, state machine ARN, role ARN (compact()-safe)
```

## File & Folder Structure

```
infra/modules/table-share/…                     # the module above
infra/modules/base/policies/*.tftpl             # deploy-role expansion (new resource types)
lambdas/table-share/
├── common/                                       # tscommon package → the layer (stubbed namespaces)
├── validate_authorize/handler.py                 # placeholder
├── inspect_source/handler.py                     # placeholder
├── check_target_absent/handler.py                # placeholder
├── copy_objects/handler.py                        # placeholder
└── create_table/handler.py                        # placeholder
.github/workflows/deploy-lambdas.yml             # build/publish the tscommon layer + zips
```

## Implementation Phases

### Phase 1: Module skeleton (queue/pipe/SFN/lambdas/layer/logs)

- Author `infra/modules/table-share/` with the FIFO queue+DLQ, Pipe, Standard SFN skeleton (`Map` placeholder), five placeholder Lambdas on one role, the common layer, and log groups.

### Phase 2: Deploy-role IAM + CI

- Expand the deploy role for the new resource types; wire the `tscommon` layer + function zips into `deploy-lambdas.yml`.

### Phase 3: Smoke test + completion ritual

- Control-plane smoke test (message → one execution → terminal). Delivery doc, INDEX status, component-inventory rows (the module + `tscommon` layer).
