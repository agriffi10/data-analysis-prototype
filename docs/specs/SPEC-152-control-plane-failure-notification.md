# Spec: Control-Plane Failure Notification — Telling the User When No Verb Ran

**ID:** SPEC-152
**Status:** Completed
**Last Updated:** 2026-08-05
**Depends On:** SPEC-114 (the notification **is** the completion channel — the rule this spec extends to a case it never covered), SPEC-126 (the DLQ drain, which covers the adjacent case and shows where its coverage stops), SPEC-129 (`cpcommon.errors.failure_reason`, written for this and currently used once), SPEC-134/135/136 (the `@notifies_on_failure` instrumentation whose limitation this spec addresses), SPEC-107 (`cpcommon`)

> **Reference:** from the 2026-08-05 codebase audit. There is a silent-failure hole that the repo's own design already names but only closed in one of four planes.
>
> **The mechanism, precisely.** `@notifies_on_failure` needs handler code to run. The DLQ drain (SPEC-126) covers messages that never *started* an execution. Neither covers the gap in between: an execution that started and then failed **before or outside** any verb's Python — a `States.Timeout`, a `States.DataLimitExceeded`, a task-level throttle, or a Lambda that fails at **import**. In that window the user is told nothing at all: no notification, no DLQ message, and the request simply never completes.
>
> **This is not theoretical for this fleet.** SPEC-137's post-mortem is exactly it — three singleton Lambdas raised `ModuleNotFoundError` at cold start for nine days, and on `pre-signup` that took down sign-up. A cold-start import failure in a table-builder verb produces precisely the same silence.
>
> **Verified state:** `NotifyFailure` appears **6 times** in `data-quality/state-machine.asl.json.tftpl` and **zero** times in `table-builder`, `table-share` and `shared-spaces`. `cpcommon.errors.failure_reason` — written to decode `{Error, Cause}` safely in Python precisely because no ASL state may decode a `Cause` (#252) — has exactly **one** production consumer, `dq_notify_failure.py:59`. The design is right; it was built once and never propagated.
>
> **This spec provisions new infrastructure**, so CLAUDE.md's infra rule applies in full: expanding the deploy role's IAM is in-scope work, not an afterthought, and `architecture.md` → *Deploy-role IAM — adding a new resource type* + *Lambda code/infra split* must be read before Phase 1. That risk profile is why this is separate from SPEC-151.

## Overview

Every control plane in this system is asynchronous and fire-and-forget: the browser enqueues a request, gets a toast, and the outcome arrives as a notification. SPEC-114 made that explicit — the notification *is* the completion channel, because the user has no other way to learn what happened. The verbs honour it through `@notifies_on_failure`, and the DLQ drain honours it for requests that never started.

The gap is the execution that starts and then dies before any of that code runs. Today, in three of the four planes, such a failure is recorded in the state machine's execution history and nowhere else. The user sees a request they submitted, a toast that said it was accepted, and then permanent silence. They have no admin UI to check and no reason to suspect anything but slowness.

The data-quality plane already solved this: a `NotifyFailure` state before the terminal `Failed`, and a thin verb that decodes the raw error with `cpcommon.errors.failure_reason` and emits a notification through the domain notifier. This spec propagates that pattern to table-builder, table-share and shared-spaces. The user-visible result is that every way a request can fail ends in a message, and the phrase "it just never came back" stops being a reachable state.

---

## Scope

### In Scope

- **A `NotifyFailure` state** in the table-builder, table-share and shared-spaces state machines, reached on the paths that today go straight to `Failed`.
- **A thin failure-notifier verb per plane**, reusing `cpcommon.errors.failure_reason` and the plane's existing domain notifier.
- **Deploy-matrix rows and layer attachments** for the new verbs, including the `test_deploy_matrix.py` join.
- **Deploy-role IAM expansion** for the new function resources, as in-scope work.
- **Tests** covering the shapes that reach this path — a timeout, an import failure, and a raw `Cause` that must not be decoded in ASL.
- **A test asserting every plane has the state**, so a fifth plane cannot ship without it.

### Out of Scope

- **Changing `@notifies_on_failure`, the verb-level instrumentation, or any existing notification message.** This spec adds a path; it does not alter the ones that work.
- **The notifications DLQ.** It stays undrained (circular) per SPEC-126.
- **Alarms, dashboards or any CloudWatch surface.** SPEC-114 FR-005 removed alarms deliberately and SPEC-126 replaced them; do not reintroduce them.
- **Redrive or retry of the failed execution.** This spec reports; it does not recover.
- **Any change to the DLQ drain**, whose coverage is adjacent and complementary.
- **The correctness defects in the verbs themselves** — SPEC-151.
- **Deduplicating the three per-plane notifiers into one.** Build them per plane following the data-quality precedent; if the duplication is judged excessive, consolidation belongs to SPEC-156, not here.

---

## Functional Requirements

### FR-001: Every plane notifies on a failure that precedes its verbs

#### Description

Table-builder (`state-machine.asl.json.tftpl:350`), table-share (`:241`) and shared-spaces route failures straight to a terminal `Failed`. Each gains a `NotifyFailure` state first, mirroring data-quality (`:354`).

#### Acceptance Criteria

- [ ] Each of the three machines has a `NotifyFailure` state entered on the failure paths that currently reach `Failed` directly, with `Failed` remaining the terminal state after it.
- [ ] `NotifyFailure` carries the **raw** `$.error` forward. **No state decodes `$.error.Cause`** — `States.StringToJson` on a `Cause` raises an uncatchable `States.Runtime` (#252, control-plane-wide). A test asserts no new state introduces such a decode.
- [ ] A `Choice` introduced by this spec, if any, guards its variable with `IsPresent` (SPEC-143's rule).
- [ ] `NotifyFailure` cannot itself fail the execution into silence: its own failure path still reaches `Failed`, and a notifier error is logged rather than raised into an unhandled state.
- [ ] A test enumerates every `state-machine.asl.json.tftpl` in `infra/modules/` and asserts each has a `NotifyFailure` state, so a future plane cannot omit it. Any deliberate exemption is a named allowlist entry with a reason.

### FR-002: A thin failure-notifier verb per plane

#### Description

`dq_notify_failure.py` is the model — roughly 140 lines, most of them comments. Each new verb decodes the raw error via `cpcommon.errors.failure_reason` and emits through its plane's existing domain notifier (`tbcommon.notify`, `tscommon.notify`, the shared-space notifier).

#### Acceptance Criteria

- [ ] Each verb resolves the recipient from the **verified token claim** carried in the request context, never from an untrusted body field — the SPEC-126 rule.
- [ ] Each verb uses `cpcommon.errors.failure_reason` to decode `{Error, Cause}`; none parses a `Cause` by hand.
- [ ] The message names the operation in the plane's own vocabulary ("Couldn't create table", "Couldn't share table", "Couldn't update shared space") and **never** contains a stack, an ARN, a token, an email or a raw AWS string.
- [ ] The message set goes through the plane's existing `failure_message` resolver rather than a new literal table.
- [ ] Each verb is **total**: a malformed or absent error payload still produces a notification rather than raising. Asserted per shape (`None`, `{}`, a string, a dict with no `Error`).
- [ ] Each verb is instrumented per the observability rules — `@traced` outermost, message literals, no `echo=`, and the field rule observed.
- [ ] A duplicate notification is preferable to none: if the verb cannot determine the outcome precisely, it says the request failed rather than staying silent.

### FR-003: The new functions are deployed, layered and pinned

#### Description

CLAUDE.md's Lambda code/infra split is where SPEC-137 failed: instrumented code shipped whose layer attachment did not, and every gate was blind. The new verbs must not repeat it.

#### Acceptance Criteria

- [ ] Each new function has a `deploy-lambdas.yml` matrix row with the correct layer flags for what it imports (`cpcommon` plus its domain layer).
- [ ] `lambdas/test_deploy_matrix.py` joins each new function's imports against its matrix row and passes — the check that SPEC-137 needed and had nowhere else.
- [ ] Each new function's IAM is scoped: the state machine may invoke it, and it may send to the notifications queue. No `Resource: "*"`.
- [ ] The **deploy role's** IAM is expanded to create and manage the new function resources, as in-scope work. `architecture.md` → *Deploy-role IAM — adding a new resource type* is read first, and the recurring traps it names (self-grant timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) are checked against.
- [ ] `deploy-infra.yml`'s Checkov-over-the-rendered-plan job (SPEC-139) stays green, or any new finding is dispositioned in `security-baseline.md` rather than waived silently.
- [ ] A cold-start import of each new verb succeeds in a scrubbed environment, in the style of `test_layer_import_safety.py`. This is the direct SPEC-137 regression guard and is not optional.

### FR-004: The failure paths are tested by shape, not by count

#### Acceptance Criteria

- [ ] A test per plane drives a `States.Timeout`-shaped error to `NotifyFailure` and asserts a notification is emitted naming that plane's operation.
- [ ] A test drives an import-failure-shaped error (the SPEC-137 shape) and asserts the same.
- [ ] A test asserts the raw `Cause` survives to the verb undecoded, and that the verb — not the ASL — decodes it.
- [ ] Tests assert on the **notification body** the user would receive, not on `mock.call_args`.
- [ ] No test asserts a count of states or notifications where naming the state or the message would do.

---

## Implementation Phases

### Phase 1: Read the infra rules, then the deploy role

- Read `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split*, and the `decisions/` entry for the refresh-deadlock lever, **before** writing Terraform.
- Expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) for the new function resources.
- Land and apply this before the functions exist — the self-grant timing trap is the reason it goes first.

### Phase 2: The data-quality pattern, extracted and understood

- Read `dq_notify_failure.py` and the data-quality machine's `NotifyFailure` wiring in full.
- Decide per plane what the message set needs and confirm the domain notifier can carry it.

### Phase 3: Table-builder

- The state (FR-001), the verb (FR-002), the matrix row and IAM (FR-003), the tests (FR-004).
- This plane goes first because it is the one SPEC-137's failure mode actually hit.

### Phase 4: Table-share and shared-spaces

- The same four FRs per plane (FR-001 → FR-004). Table-share's `Map` fan-out needs care: a per-recipient failure already has a per-item `Catch`, so `NotifyFailure` must cover the **execution-level** failure without duplicating the per-recipient path.

### Phase 5: The fleet assertion

- FR-001's enumerate-every-machine test.
- FR-003's scrubbed-environment import probe for each new verb.

### Phase 6: Completion

- Completion ritual per `CLAUDE.md`.
- This is a new architectural decision — "every plane notifies on a pre-verb failure; `failure_reason` is the only decoder" — so it earns a full `decisions/` entry and **one line** in Key Decisions.
- Add a `component-inventory` row for each new verb.
