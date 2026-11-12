---
type: Spec
id: SPEC-254
title: "The Standalone Functions Are Building-Block Calls"
description: "Moves the scheduled functions and the two single-writer queues onto the scheduled-function module and a new queue-consumer module, composed from the root, with a CI plan showing nothing deployed changed."
spec_status: Draft
depends_on: [SPEC-252]
arc: infra-building-blocks
arc_order: 3
---

**Dependency notes:** SPEC-252 (introduces `scheduled-function`, with shared spaces' transfer reader
as its first caller, and teaches `fleet.py` to resolve a function declared through a root call).
Arc reasoning: `ARCS.md` → *Infra building-blocks arc*.

## Overview

Outside the control planes, two more shapes are each built more than once. Three functions run on a
schedule — the daily user-directory build, the ten-minute DLQ drain and the ten-minute logs sweep —
and each module builds the same role, function, rule, target and permission. Two functions are the
single writer of a FIFO queue — notifications and feedback — and each builds the same queue, DLQ,
role, function and event-source mapping. This spec makes each shape a call to a building block, so
the last per-feature copies of the same machine are gone and what remains in `infra/modules/` is
either a building block or a concept built once.

## Scope

### In Scope

- `user-directory` and `control-plane-dlq-drain` become root calls to `scheduled-function` at their
  current module addresses; `observability` keeps the logs queue and its alarm, and its sweep
  becomes `module.observability_sweep`, a call to `scheduled-function`.
- A new building block, `infra/modules/queue-consumer/` — a FIFO queue, its DLQ, a role, one
  function and the event-source mapping — and `notifications` and `feedback` become root calls to
  it at their current addresses.
- `moved` blocks for every changed address, the re-pointed tests and docs.

### Out of Scope

- The API's and the Cognito triggers' `keep-warm` rules. Each wakes a function its own module
  owns, and moving the rule out would split the function from the reason it is kept warm.
- Changing any schedule, batch size, queue setting, IAM document, name or function setting.
- An apply. The plan is the proof.

---

## Functional Requirements

### FR-001: The three scheduled functions are calls to `scheduled-function`

#### Description:

The user-directory build, the DLQ drain and the logs sweep are each a root call to
`./modules/scheduled-function`, with the function's own policy templates beside its call. SPEC-252
sized that module's inputs for these three callers (their statement ids, rule names, inline policy
names, the sweep's role name without a `-role` suffix, and observability's two inline policies),
and this spec uses it unchanged; a caller it cannot express is a defect in SPEC-252's contract,
fixed there rather than worked around here.

#### Acceptance Criteria:

- [ ] `infra/modules/user-directory/` and `infra/modules/control-plane-dlq-drain/` are deleted, and
      `infra/modules/observability/` holds no function, role, rule or permission.
- [ ] The PR's CI plan shows every object these three owned as unchanged or moved, with no create,
      update, replace or destroy.
- [ ] Every `aws_lambda_permission` these calls create binds to `function_arn`, which the source
      rule in `lambdas/test_the_cutover.py` asserts (the plan guard only checks the binding looks
      like an ARN, and a constructed ARN passes it).

### FR-002: The two single-writer queues are calls to `queue-consumer`

#### Description:

`infra/modules/queue-consumer/` builds a FIFO queue and its DLQ, a role with the caller's policy,
one function, and an event-source mapping at batch size 1. Notifications and feedback are each a
call to it; feedback's DLQ stays undrained, as today. Its inputs come from an attribute diff of the
two modules, as SPEC-252's do; already known to vary are the queue's and the DLQ's
`content_based_deduplication` separately (feedback's DLQ deduplicates on content, its queue does
not) and the queue's `deduplication_scope` (notifications sets `messageGroup`).

#### Acceptance Criteria:

- [ ] `infra/modules/notifications/` and `infra/modules/feedback/` are deleted, and the PR's CI
      plan shows every object they owned as unchanged or moved, with no create, update, replace or
      destroy.
- [ ] The module contains no `data` block, no `provider` block and no module-level `depends_on`.
- [ ] Every root output and `.github/config-outputs.json` key that names one of these queues
      resolves to the same value, by the plan showing no change to any of those outputs.

### FR-003: The fleet, the tests and the docs follow

#### Description:

`fleet.py` still derives the whole fleet; every test and page reading a deleted path reads its new
home; `infra/info/INDEX.md` lists the two building blocks.

#### Acceptance Criteria:

- [ ] `python3 lambdas/fleet.py` prints the same list as on `main`.
- [ ] Test IDs collected from the runners on `main` and on the branch differ only by file path where
      a test file moved.
- [ ] `git grep` for `infra/modules/` followed by any deleted directory name returns nothing outside
      a dated History entry or a Completed spec's body, and `python3 scripts/validate_docs.py`
      passes.

---

## Implementation Phases

### Phase 1: Scheduled functions

- The three calls, their moves, the observability split.

### Phase 2: Queue consumers

- `queue-consumer`, the two calls, their moves.

### Phase 3: Re-point and document

- Tests, scripts and docs on the deleted paths; `INDEX.md`; the module READMEs.
