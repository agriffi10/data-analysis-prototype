# Spec: Structured Logging — Instrument the Data-Quality Control Plane (pilot)

**ID:** SPEC-128
**Status:** Draft
**Last Updated:** 2026-07-22
**Depends On:** SPEC-127 (the queue, the sweep, `cpcommon.observability`), SPEC-108→114 + 123/124 (the data-quality arc being instrumented)

## Overview

SPEC-127 builds the pipe and proves it with one self-instrumenting producer. This spec puts real
traffic through it: all nine data-quality verbs emit structured spans, so a run that took four
minutes or failed at step six becomes something you can *query* instead of something you
reconstruct by opening nine CloudWatch log groups in nine browser tabs.

Data-quality is the right pilot for three reasons. It is the **longest** control plane (nine
verbs against table-builder's five), so it is where cross-verb correlation actually pays. It is
the **newest**, so it is the arc whose behaviour under real load is least understood — and per the
CLAUDE.md note, three of its recent specs are deployed but unproven against live infrastructure.
And it is **entirely operator-facing**: nothing here changes a pixel or a permission for a user,
so a mistake costs log quality, not access.

The honest limitation, recorded up front: a data-quality run is nine separate Lambda invocations,
and `log-foundry`'s trace context is per-process. **This spec produces nine traces per run, not
one**, joined at query time on a `request_id` field. Real cross-Lambda stitching needs an upstream
`lf.continue_trace()` and is FR-005's deferred follow-up (user decision, 2026-07-22: ship
correlation now, stitching later).

## Scope

### In Scope

- `@traced` on all nine data-quality verb handlers, with `service="data-quality"`.
- `request_id` (and the verified actor, where one exists) as trace baggage, so a whole run is one
  query.
- `LOGS_QUEUE_URL` on the data-quality functions' environment, and `sqs:SendMessage` on the shared
  data-quality execution role.
- A **redaction rule** with a test: no ID token, no credential, and no user data *values* ever
  become a log field.
- Live verification of a real run end to end, since that is the only thing that proves the pipe.

### Out of Scope

- **The other four control planes** (table-builder, table-share, shared-spaces, notifications) and
  the three non-layer functions. A later spec, once this one has run live.
- **`lf.continue_trace` / true distributed tracing.** FR-005 records it as the follow-up; nothing
  is built here and no ASL payload changes.
- **Replacing the existing `logging.getLogger()` calls** in these nine files. They stay. This is
  additive.
- **Any Athena/Glue table over `logs/`.** Still deferred (SPEC-127 out-of-scope).
- **Changing verb behaviour.** No control-plane logic, no state machine, no IAM beyond the one
  `sqs:SendMessage` grant, no notification change. If a verb's output shape changes, this spec has
  gone wrong.
- **Alarms**, consistent with SPEC-126.

---

## Functional Requirements

### FR-001: All nine verbs are traced, and the list cannot silently shrink

#### Description

The nine handlers are `dq_validate_authorize`, `dq_inspect_source`, `dq_create_temp_tables`,
`dq_start_profile_query`, `dq_check_query`, `dq_byte_scan`, `dq_assemble_report`,
`dq_drop_temp_tables`, `dq_notify_failure`. Partial instrumentation is worse than none: a run that
shows eight of nine verbs looks like a run that *stopped* at eight.

#### Acceptance Criteria:

- [ ] Every one of the nine handlers is decorated with `cpcommon.observability.traced("<verb>")`,
      and `init(service="data-quality")` runs once at module import.
- [ ] A test enumerates `lambdas/data-quality-*/` (excluding the `-common` and `-polars` layer
      directories) and asserts **every** module exposing a `handler` is traced — so a tenth verb
      cannot be added without either instrumenting it or failing the test. This mirrors the
      descriptor-coverage test SPEC-126 FR-001 used for the same reason.
- [ ] **Decorator order is `@traced` outermost, above `@notifies_on_failure`.** A comment records
      why: `notifies_on_failure` catches on its way out, so if it were outermost the span would
      close `status="ok"` on an invocation that actually failed and notified. Outermost `traced`
      sees the exception the handler really raised. A test asserts a verb that raises produces a
      span with `status` reflecting the failure **and** still emits its notification.
- [ ] `traced` wrapping a handler does not change its return value, its raised exception type, or
      its `__name__`. A test asserts the wrapped handler is byte-for-byte equivalent in output to
      the unwrapped one for a success and a failure case.

### FR-002: One run is one query

#### Description

Nine invocations, nine `trace_id`s. The join key has to be something every verb already has, and
that is the `requestId` threaded through the state machine from the moment `validate-authorize`
accepts the request.

#### Acceptance Criteria:

- [ ] Each verb calls `lf.set_baggage(request_id=<the run's requestId>)` as early as it can — for
      most verbs that is the first line that has the event in hand.
- [ ] Baggage is set **after** the value is read from the event and **before** any `lf.info`, so
      every event in that invocation carries it. A test asserts an event emitted mid-verb has
      `fields.request_id` populated.
- [ ] `validate-authorize` additionally sets `username` baggage — but **only the verified
      `cognito:username` from the token**, never a body-asserted one. A test asserts a body whose
      `username` disagrees with the token's claim logs the **token's** value. Downstream verbs
      inherit it from the state payload, which by then carries an authorized value.
- [ ] Verbs that run when there is **no** `requestId` (a malformed event reaching
      `notify-failure`) emit their span with `request_id` absent rather than inventing or
      defaulting one. A comment records why: a fabricated correlation key silently merges
      unrelated runs, which is worse than an unjoinable event.
- [ ] The delivery doc records the query that answers "show me run X" against the NDJSON
      (`fields.request_id == "…"`, sorted by `timestamp`), so the capability is written down
      rather than implied.

### FR-003: What must never become a field

#### Description

These logs land in S3 and are retained forever (SPEC-127 FR-009). Everything a verb touches is
either a bearer credential or someone's data. `log-foundry` is safe by default — it captures no
arguments and no return values unless asked — and this FR's job is to keep it that way as call
sites are added.

#### Acceptance Criteria:

- [ ] **No ID token, or any part of one, is ever a log field.** The same posture as SPEC-126
      FR-004, and for the same reason: it is a bearer credential and this store has a wider read
      audience than the queue it came from. A test asserts a token value passed through a verb
      never appears in any emitted event.
- [ ] **No user data values.** Column *names* and row *counts* are structure and may be logged;
      cell values, query result rows, the profile query's min/max/sample values, and file contents
      may not. A comment records the line being drawn and where it comes from — a data-quality
      report is deliberately written to a location only the owner can read, and logging its
      contents into the admin bucket would route around that.
- [ ] `lf.trace` is used **without** any argument- or return-capture option anywhere in this arc,
      and a comment at the `init()` call records that this is deliberate, not an oversight — it
      is the single setting that would turn every traced verb into a data exfiltration path.
- [ ] Raw AWS/Athena/boto error text may appear in log **fields** (this is an operator store, and
      SPEC-106's no-raw-AWS-text rule governs *user-facing* messages only). A comment records that
      distinction explicitly, so nobody "fixes" the logs into uselessness by applying the
      user-facing rule here — and, conversely, so nobody assumes the reverse and pipes a log field
      into a notification.
- [ ] A test asserts S3 object keys and Athena query IDs *are* logged — they are the operator's
      only handle on a run and are deliberately in scope.

### FR-004: Wiring, and the cold-start failure no unit test can reach

#### Acceptance Criteria:

- [ ] All nine data-quality functions gain `LOGS_QUEUE_URL` in their Terraform environment block.
      A comment records the SPEC-127 FR-003 guarantee that makes a partial rollout safe: the
      variable is optional, so a function that somehow misses it logs to stdout instead of
      crashing at import.
- [ ] The shared data-quality execution role gains **`sqs:SendMessage` on the logs queue ARN
      only**, via SPEC-127 FR-006's producer fragment. No other action, no other queue.
- [ ] A plan assertion confirms the data-quality module's IAM changed **only** by that one
      statement.
- [ ] **The first invoke after deploy is checked for all nine functions.** A shared layer's
      import-time work runs at cold start for every attaching function and is the one failure mode
      unit tests cannot reach (PR #196, and the same check SPEC-125 owes). `observability.init()`
      constructs a boto3 SQS client at import; if that or the `log-foundry` import fails, nine
      verbs fail at cold start with an error that names neither.
- [ ] No change to the state machine definition, the report shape, the notification contract, the
      runs index, or any IAM beyond the above. The diff is decorators, baggage lines, one env var
      and one IAM statement.

### FR-005: The stitching limitation is documented, not implied

#### Description

Someone reading nine `trace_id`s for one run will assume the tracing is broken. It is not — it is
doing exactly what a per-process trace context can do across nine processes. Writing that down is
cheaper than the investigation it prevents.

#### Acceptance Criteria:

- [ ] A comment in `observability.py` (or the data-quality delivery doc) states plainly: one run
      produces **nine traces**, correlated on `fields.request_id`; `trace_id` is per-invocation and
      `parent_span_id` never crosses a Lambda boundary.
- [ ] The same note records the shape of the fix so it does not have to be rediscovered: an
      upstream `lf.continue_trace(trace_id, parent_span_id)` plus threading those two values
      through the Step Functions state payload, exactly as `reportKey` is threaded today.
- [ ] It is registered as a follow-up (a spec row or an ARCS.md line), **not** left as a TODO in
      code. The standing preference is to cost a fix and offer it rather than ship a commented
      known-edge; this one is costed (an upstream release plus an ASL payload change on every
      state) and deliberately sequenced after the pipe is proven live.

---

## Data Model

No new persisted shape. The events are SPEC-127's schema; this spec only fills `service` and
`fields`:

```jsonc
{
  "service": "data-quality",              // the control plane (SPEC-127 FR-003)
  "function": "handler",                  // the span name
  "fields": {
    "verb":       "inspect-source",       // stamped by traced()
    "request_id": "0f2a…",                // FR-002 — the cross-Lambda join key
    "username":   "agriffith"             // FR-002 — VERIFIED claim only, never body-asserted
  }
}
```

## File & Folder Structure

```
lambdas/data-quality-validate-authorize/dq_validate_authorize.py
lambdas/data-quality-inspect-source/dq_inspect_source.py
lambdas/data-quality-create-temp-tables/dq_create_temp_tables.py
lambdas/data-quality-start-profile-query/dq_start_profile_query.py
lambdas/data-quality-check-query/dq_check_query.py
lambdas/data-quality-byte-scan/dq_byte_scan.py
lambdas/data-quality-assemble-report/dq_assemble_report.py
lambdas/data-quality-drop-temp-tables/dq_drop_temp_tables.py
lambdas/data-quality-notify-failure/dq_notify_failure.py
lambdas/data-quality-common/test_instrumentation_coverage.py     # the FR-001 enumeration test
infra/modules/data-quality/lambda.tf                             # + LOGS_QUEUE_URL (x9)
infra/modules/data-quality/iam.tf                                # + sqs:SendMessage (one stmt)
```

## Implementation Phases

### Phase 1: Instrument

- `traced` + `init` on all nine handlers; `request_id` / verified-`username` baggage.
- The FR-001 coverage test, the FR-003 redaction tests, the FR-002 verified-identity test, and
  the decorator-order test.

### Phase 2: Wire

- `LOGS_QUEUE_URL` on the nine functions; the single `sqs:SendMessage` statement on the shared
  execution role; the plan assertion that nothing else moved.

### Phase 3: Live verification

- Cold-start check on **all nine** functions' first invoke after deploy (FR-004).
- Run a real data-quality check end to end. Within ~5 minutes assert
  `logs/data-quality/dt=…/hh=…/` contains spans from every verb the run executed, that each
  carries the same `fields.request_id`, and that each start event has a matching end event with
  `duration_ms` and `status`.
- Run a check that **fails** mid-pipeline. Assert the failing verb's span closes with the failure
  status, that `notify-failure`'s own span is present, and that the user notification still
  arrives unchanged.
- Grep the written NDJSON for the ID token used in the run and assert **zero** matches (FR-003).
- Completion ritual. **The SPEC-074 help sweep is a no-op** — nothing user-facing changed — and
  the delivery doc says so explicitly.

### Note on the arc's outstanding live verification

Per CLAUDE.md, SPEC-114/123/124/126 are merged and deployed but **unproven against live
SQS/SFN/Cognito/S3**, and 125 owes a shared-space smoke run. Phase 3 runs a real data-quality
check end to end, which exercises 114's `reportKey` seeding and 123's conditional-put CAS as a
side effect. That is a convenient overlap, **not a substitute**: those specs' own Phase 2
scenarios still have to be run and recorded against their own acceptance criteria.
