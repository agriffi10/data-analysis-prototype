# Spec: Structured Logging — Instrument the Shared-Space Control Plane

**ID:** SPEC-134
**Status:** Draft
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-133 (the infra pattern), SPEC-125 (`cpcommon` on this plane)

## Overview

The first of four rollout specs taking the SPEC-130 narrative to every remaining Lambda. Shared
spaces go first because the plane has the most state to be wrong about: a single request touches
an S3 control-object registry, a per-user cache in each member's own space, a Glue database, a
Lake Formation grant, and up to ten Cognito attribute slots — five places that can disagree, none
of which the user can see.

That disagreement is not hypothetical; it is this plane's history. A cache CAS race needed an
auto-reconcile (#153–155), a durable pending/deleting write had to move into the validator
(#163/#164), a `forget` verb exists because a space could get stuck in a user's list (#165), and a
collision phantom had to be chased out. Every one of those was diagnosed by reading CloudWatch
across several functions and inferring what the registry must have looked like. The events this
spec adds are the record that would have made each of them a query.

The plane also carries the arc's only eight-verb chain and, unusually, **no `notifies_on_failure`
decorator anywhere** — its verbs notify explicitly from inside the handler — so the decorator
ordering rule that governs data-quality, table-builder and table-share does not apply here, and
that difference is asserted rather than assumed.

## Scope

### In Scope

- `observability.init(service="shared-space")` and `@observability.traced(<verb>)` on all eight
  verbs: validate, create, add-members, remove-members, leave, delete, forget,
  acknowledge-membership.
- Named `step` child spans on each verb's bounded internal phases.
- Narrative for the five stores a request touches, and for the CAS paths that reconcile them.
- The infra pair: `LOGS_QUEUE_URL` on the functions, `sqs:SendMessage` on the logs queue.
- **The shared coverage-guard harness** the other three rollout specs reuse.

### Out of Scope

- **Any behavior change.** No change to the registry, the cache, CAS, slot allocation, LF grants,
  teardown, the roster fan-out, or what any verb notifies. Observation only.
- **Removing existing `logging.getLogger()` calls.** They stay.
- **table-builder, table-share and the singletons** — SPEC-135, 136, 137.
- **Retrofitting `notifies_on_failure` onto this plane** to match the others. Out of scope and not
  a goal; FR-002 records the difference instead.

---

## Functional Requirements

### FR-001: The plane joins the pipe

#### Description

`service="shared-space"`, one queryable set for all eight verbs, with the per-verb identity
riding as `verb` — the same shape SPEC-128 established for data-quality.

`shared-space-common` was folded onto `cpcommon` in SPEC-125, so these functions already attach
the layer that carries `observability`; nothing new is added to their import graph.

#### Acceptance Criteria:

- [ ] `observability.init(service="shared-space")` at module scope in all eight verb modules, and
      `@observability.traced(<verb>)` on each `handler`.
- [ ] A test asserts `"shared-space"` matches `log_sweep.SERVICE_RE` — a name failing the pattern
      files every event under `logs/_unrouted/` rather than failing loudly (SPEC-129).
- [ ] The verb names stamped are the request `action` values the plane already uses, so an event's
      `verb` and a request's `action` are the same string and join without translation.

### FR-002: The decorator difference is asserted, not assumed

#### Description

Every data-quality, table-builder and table-share handler carries `@notify.notifies_on_failure`,
and `@traced` must sit **above** it or a failed-and-notified invocation closes its span `status:
"ok"`. Shared-space handlers carry no such decorator — they notify explicitly, from inside the
verb — so `@traced` is simply the only decorator.

Writing that down matters because the next person to read three instrumented planes will see the
ordering rule stated three times and reasonably assume it was forgotten here.

#### Acceptance Criteria:

- [ ] A test asserts each of the eight handlers has **exactly one** decorator and that it is
      `observability.traced(...)`. It fails if someone later adds `notifies_on_failure` without
      also establishing the ordering.
- [ ] A comment in the coverage harness records why this plane's expectation differs.
- [ ] Because failure notification happens *inside* the handler, a verb that notifies a failure
      and then re-raises must still close `status: "error"` — a test asserts the span status on a
      verb that notifies and raises.

### FR-003: Every store a request touches is named

#### Description

The plane's characteristic bug is two stores disagreeing, and the characteristic debugging session
is reconstructing which writes landed. So each verb narrates the stores it wrote, in order.

The five: the **registry** control object (source of truth, in the admin bucket), the per-user
**cache** in each member's own space, the **Glue database**, the **Lake Formation** grant, and the
**Cognito membership slots**.

#### Acceptance Criteria:

- [ ] Per-verb minimum content:
      - **validate** — the parsed action, space, actor, `schemaVersion`, and the durable
        pending/deleting intent write (the write that exists because a request could otherwise
        vanish between validation and execution, #163/#164).
      - **create** — each of the four provisioning steps and its outcome: the registry marker, the
        Glue database, the `portal-managed` tag, the portal-role grant.
      - **add-members / remove-members** — members requested, members applied, members ignored as
        unknown, and the resulting slot count against the cap.
      - **leave / delete / forget** — what was torn down and what was deliberately left.
      - **acknowledge-membership** — the pending→active flip, and whether the membership was
        already active.
- [ ] Every event names the **space** and the **actor**; both are permitted metadata under
      SPEC-130 FR-005 and both are the first things asked about a shared-space incident.
- [ ] A verb that writes a store it did not have to write, or skips one it usually writes, says so
      — the "nothing to do" outcome is a distinct, logged state, not an absent event.

### FR-004: CAS contention and reconciliation are visible

#### Description

The cache is written under compare-and-swap, and a lost race is the failure that produced
#153–155. A retry that eventually succeeds is invisible today; a systematic contention problem
therefore looks like nothing until it looks like corruption.

#### Acceptance Criteria:

- [ ] Each CAS retry emits `warning` with the attempt number, the cap, and the object being
      contended.
- [ ] Exhausting the attempt cap emits `error` naming the store left unwritten.
- [ ] An auto-reconcile that repairs a divergence emits `warning` naming what it found and what it
      changed — a silent self-heal is the thing that hides a recurring bug.
- [ ] `step` spans wrap the registry read-modify-write and the cache read-modify-write separately,
      so contention on one is not attributed to the other.

### FR-005: The roster fan-out reports per member

#### Description

`cache.write_roster_to_all` fans a roster write out to every member on add, remove and leave
(SPEC-075). One member's cache write failing while the others succeed is precisely the state that
leaves a roster looking correct to some members and stale to others.

Per-member events are permitted here — and this is a deliberate exception to the per-item caution
in SPEC-131 and SPEC-132 — because membership is **capped at ten** by the Cognito attribute slot
model. The bound is structural, not a hope.

#### Acceptance Criteria:

- [ ] One event per member whose cache was written, naming the member and the outcome.
- [ ] A failed per-member write emits `warning` and does not abort the fan-out; a summary event
      carries written and failed counts.
- [ ] A comment records why per-member is acceptable here and cites the ten-slot cap, so the
      exception does not read as inconsistency with SPEC-131 FR-005.
- [ ] A test with a fan-out where the third of five members fails asserts the other four are still
      written and that both the per-member `warning` and the summary counts are emitted.

### FR-006: Slot allocation and tag propagation

#### Description

Access is gated by a membership principal tag built from ten bounded Cognito attribute slots, and
a newly granted tag **does not take effect until the user's token is re-minted** — a lag that has
repeatedly presented as "the grant didn't work".

#### Acceptance Criteria:

- [ ] Slot allocation emits the slot index used, the resulting occupied count, and the cap.
- [ ] Exhausting the slots emits `error` with a stable reason token, not only a user notification.
- [ ] The event that records a granted membership states that access is live at grant time and
      that the *principal tag* requires a token re-mint — so the log answers the question the lag
      provokes instead of prompting it.

### FR-007: The shared coverage harness

#### Description

`data-quality-common/test_instrumentation_coverage.py` enumerates its plane's verb directories so
a tenth verb cannot be added without instrumenting it. Four planes need that guard, and four
copies of an enumeration test is how three of them drift.

This spec promotes it to a parameterized harness in `control-plane-common`, with one entry per
plane declaring its directory glob, its expected verb count, and its decorator expectation.
SPEC-135, 136 and 137 add a row each.

#### Acceptance Criteria:

- [ ] The harness lives in `control-plane-common`, is parameterized over plane descriptors, and
      asserts per plane: every handler is `@traced`, every module `init`s with the plane's service
      name, the enumeration found the expected count, and the decorator expectation holds.
- [ ] The data-quality entry reproduces every assertion the existing module makes, including
      `@traced` outermost above `@notifies_on_failure`, and the existing module is removed only
      once the harness demonstrably covers it.
- [ ] Each plane declares its **expected verb count** as a literal, so the enumeration finding
      too few fails rather than passing vacuously.
- [ ] The narrative-presence and contents-denylist checks (SPEC-132 FR-004/FR-006) move into the
      harness and apply to every registered plane.
- [ ] Adding a plane to the harness requires exactly one descriptor entry.

### FR-008: The infrastructure the events need

#### Description

Mirrors SPEC-133 FR-007. The shared-spaces module has neither `LOGS_QUEUE_URL` nor permission to
send to the logs queue; without the IAM the functions start fine and every event dies in
`SQSSink`'s stderr write.

#### Acceptance Criteria:

- [ ] `logs_queue_url` variable on `modules/shared-spaces`, wired in `main.tf` from the
      observability module's output, set as `LOGS_QUEUE_URL` on all eight functions.
- [ ] An `EmitStructuredLogEvents` statement granting `sqs:SendMessage` on the logs queue ARN, the
      same Sid and shape as `modules/data-quality/policies/execution.json.tftpl`.
- [ ] `LOGS_QUEUE_URL` stays optional by construction — `environ.get`, never `_require`.
- [ ] The deploy role is checked against the adding-a-resource-type rule and the finding recorded
      either way; no new resource type is expected here, but expected is not verified.
- [ ] The IAM and environment variable apply **before** the instrumented code deploys.

---

## Data Model

Events follow SPEC-127's schema, landing at `logs/service=shared-space/…`. Field vocabulary:

```
space: str          actor: str          action: str         member: str
members_requested: int   members_applied: int   members_ignored: int
slot: int           slots_used: int     slots_cap: int
store: "registry" | "cache" | "glue" | "lakeformation" | "cognito"
attempt: int        written: int        failed: int         already: bool
reason: str         status: "pending" | "active" | "deleting" | "failed"
```

## File & Folder Structure

```
lambdas/shared-space-{validate,create,add-members,remove-members,leave,delete,forget,acknowledge-membership}/
lambdas/shared-space-common/{cache,registry,membership}.py
lambdas/control-plane-common/test_instrumentation_coverage.py      # the shared harness (FR-007)
infra/modules/shared-spaces/{variables,lambda}.tf
infra/modules/shared-spaces/policies/*.json.tftpl
infra/main.tf
```

## Implementation Phases

### Phase 1: Infrastructure, applied first

- `logs_queue_url` variable, `main.tf` wiring, `LOGS_QUEUE_URL`, the `EmitStructuredLogEvents`
  statement, and the recorded deploy-role finding.

### Phase 2: The harness

- The parameterized coverage harness with the data-quality entry proven equivalent, plus the
  shared-space entry — failing, since the plane is not yet instrumented.

### Phase 3: Into the pipe

- `init` + `@traced` on all eight verbs; the decorator-shape assertions; `SERVICE_RE`.

### Phase 4: The narrative

- Per-verb store narrative, the CAS and reconcile events, the roster fan-out, slot allocation.

### Phase 5: Live verification

- The shared-space smoke run **SPEC-125 still owes**: create → add-member → leave → delete,
  confirming no cold-start failure from a shared layer's import-time `_require` (PR #196) and that
  one request's events across the verbs join on `request_id`.
