# Spec: Structured Logging Foundation (`log-foundry` → logs queue → admin bucket)

**ID:** SPEC-127
**Status:** In Progress
**Last Updated:** 2026-07-22
**Depends On:** SPEC-032 (admin bucket), SPEC-107 (`cpcommon` layer), SPEC-126 (the pull-sweep pattern this reuses)

## Overview

Every Lambda in this repo logs with stdlib `logging` to CloudWatch, as free-form English.
That is fine for reading one invocation and useless for every other question: there is no way
to ask "how long does `inspect-source` take at p95", "which runs failed last week", or "show me
everything that happened in request `abc-123`", because nothing in a log line is a *field*.

This spec introduces **`log-foundry`** — a zero-dependency structured-logging library that emits
one identically-shaped JSON record when a call starts and another when it ends, carrying
duration, status, and W3C-compatible trace/span IDs — and builds the pipe that gets those records
somewhere durable: an SQS queue, swept on a schedule into the admin bucket under `logs/{service}/`
as Hive-partitioned NDJSON.

The spec ships the **pipe and the bootstrap, not the instrumentation**. Exactly one producer
exercises it end-to-end (the sweep Lambda logs its own sweeps), which is enough to prove the path
without touching a control plane. **SPEC-128** instruments the data-quality arc as the pilot;
the remaining four control planes follow in a later spec.

**The delivery model is a pull, not a push.** An SQS event-source mapping or an EventBridge Pipe
holds an always-on managed poll loop against a queue that is empty most of the time, and that
idle long-polling was the bulk of this account's SQS request volume — the problem #270/#271 fixed
by converting the DLQ drain from four event-source mappings to one scheduled sweep. A new
always-on consumer would walk straight back into it. This queue is swept.

## Scope

### In Scope

- A **standard** (non-FIFO) SQS logs queue, written by control-plane execution roles only.
- `log-foundry` pinned into the **`cpcommon` layer**, core-only (no `[aws]` extra).
- `cpcommon/observability.py` — a two-function bootstrap (`init()` / `flush()`) that every
  instrumented handler calls, safe to import when the feature is unconfigured.
- A **scheduled sweep Lambda** (`log-sweep`) that receives from the queue, groups by `service`,
  and writes Hive-partitioned NDJSON to `s3://{admin-bucket}/logs/{service}/dt=…/hh=…/`.
- Execution-role IAM for the sweep, and `sqs:SendMessage` for the roles that will produce.
- Deploy-role expansion for the new module's resource types, **in its own PR, applied first**.
- The **upstream `log-foundry` changes** this design depends on, gated by a version pin.

### Out of Scope

- **Instrumenting any control plane.** No `@lf.trace` lands on a verb here. That is SPEC-128
  (data-quality pilot) and its successor (the remaining four planes).
- **A Glue table / Athena view over `logs/`.** The layout is chosen so one can be added without
  a repartition migration, but nothing queries the logs in this spec. Deferred by decision
  2026-07-22.
- **Migrating the ~20 existing `logging.getLogger()` call sites.** They stay exactly as they are
  and keep writing to CloudWatch. `log-foundry` is *additive*, and rewriting those lines would
  put SPEC-126 FR-004's token-redaction guarantee at risk for no gain here.
- **A `logs/` lifecycle rule.** Logs are retained indefinitely by decision (FR-009).
- **Cross-Lambda trace stitching** (`lf.continue_trace`). Recorded as the follow-up in SPEC-128
  FR-005; this spec ships nothing for it.
- **Any browser-side logging.** `log-foundry` is a Python library; the SPA is untouched. No new
  `VITE_` variable, no `.env.example` change.
- **Alarms.** Consistent with the SPEC-126 decision: failure information goes to a human who
  will read it, not to a console nobody watches. Nothing here alarms.

---

## Functional Requirements

### FR-001: The pinned `log-foundry` release, and the two things it must contain

#### Description

`log-foundry` 0.2.0 (current on PyPI) **cannot be used by this repo as published**. Two properties
block it, and both are one-line upstream changes rather than workarounds here. This FR is the gate:
no other phase starts until the release exists and is pinned.

**1. `requires-python = ">=3.13"`.** Every Lambda in this repo runs `python3.12` (8 infra modules,
10 workflow references, and four layers published with `--compatible-runtimes python3.12`). `pip
install` refuses the package on 3.12 outright. Bumping the fleet to 3.13 would mean republishing
the polars and `cryptography` layers and re-opening the 250 MB per-function guard for a library
that does not need 3.13. **This was verified, not assumed** (2026-07-22): the library's full gate
was run against a real CPython 3.12.12 — `pytest` 274 passed / 1 skipped, `ruff --target-version
py312` clean, `mypy --python-version 3.12` clean. The relaxation is the smaller and more honest
change (user decision, 2026-07-22).

**2. `shutdown()` is terminal, and Lambda needs a repeatable flush.** `decorator._shutdown_worker()`
calls `Worker.shutdown()` but never resets the module-level `_worker`, and `Worker.shutdown()` sets
`_shutdown_done = True` and **joins the thread**. So a handler that calls `lf.shutdown()` before
returning silently logs nothing for the entire remaining life of that warm container — the failure
would look like "logging works locally, and in production only the first invocation appears."
**Reproduced against the shipped 0.2.0** (2026-07-22): with a recording sink, invocation 1 followed
by `shutdown()` delivered its 2 events; invocations 2 and 3 on the same process delivered **zero**,
and a second `shutdown()` changed nothing.
Not flushing is equally wrong: Lambda freezes the execution environment the instant the handler
returns, so the worker's 1-second flush loop stops mid-interval and the queued events are lost
when the container is reaped. A drain that does **not** close the sink or retire the thread is
the missing primitive.

**3. Baggage never reaches the boundary events (found during the build, 2026-07-22).**
`start_event`/`end_event` called `build_event(..., baggage={})` — hardcoded empty — so a
`request_id` set with `set_baggage` reached `info` events and **not** `span.start`/`span.end`.
Those two are the records carrying `duration_ms`, `status` and `error`, so filtering
`fields.request_id == X` returned a run's narration and lost its outcome — i.e. exactly the
questions SPEC-128 FR-002 exists to answer. Fixed upstream as **log-forge SPEC-015** (one
backfill at span close, covering the sync, async and error paths) and released in **v0.4.0**,
which is why the pin below is 0.4.0 rather than 0.3.0.

The first two changes are specified upstream as **log-forge SPEC-013 — AWS Lambda Compatibility**
(`~/Documents/Git/log-forge/docs/specs/SPEC-013-aws-lambda-compatibility.md`), which is where they
are built. This FR is the consuming end: the gate that stops this arc starting before that release
exists.

#### Acceptance Criteria:

- [ ] The upstream release (target: `log-foundry==0.4.0`) declares `requires-python = ">=3.12"`,
      and its CI runs the full gate as a **matrix over 3.12 and 3.13** (log-forge SPEC-013 FR-001).
- [ ] The upstream release adds a public **`lf.flush()`** that drains the worker queue and emits
      the tail through the sink, **without** calling `sink.close()`, without joining the worker
      thread permanently, and without setting the once-only shutdown flag. A second `flush()`
      on the same process must work identically to the first.
- [ ] `lf.shutdown()` keeps its current terminal semantics and stays registered via `atexit` —
      `flush()` is an addition, not a redefinition. A comment in `observability.py` records why
      Lambda calls `flush()` and **never** `shutdown()`.
- [ ] The version is **pinned exactly** (`log-foundry==0.4.0`, not `>=`) in
      `lambdas/control-plane-common/requirements.txt`. A comment records that the pin is exact
      because the layer is attached to every control-plane verb, so an unattended minor bump
      would change the behaviour of all of them at once, at cold start.
- [ ] A repo test asserts both properties of the installed package hold: `lf.flush` exists and is
      callable, and flushing twice in one process still delivers to the sink the second time.
      This is the guard that a future re-pin cannot quietly regress.

### FR-002: The logs queue is standard, not FIFO — and the browser cannot write to it

#### Description

Every other queue in this repo is FIFO. This one cannot be. `SQSSink._send` builds its entries as
`{"Id": ..., "MessageBody": ...}` and nothing else — no `MessageGroupId`, no
`MessageDeduplicationId` — and a FIFO queue rejects a `SendMessageBatch` that omits them. Every
batch would fail, the worker would retry three times, and the events would be abandoned to stderr.

The consequences of standard delivery are real and must be designed around rather than discovered:
**no ordering guarantee** and **at-least-once delivery**. Neither matters here, because every event
already carries `timestamp`, `span_id` and a unique `log_id` — order is reconstructed at read time
and duplicates collapse on `log_id`. Ordering was never a property of the *queue*; it is a property
of the records.

#### Acceptance Criteria:

- [ ] The queue is `aws_sqs_queue` with **`fifo_queue` unset**, named `{project}-{env}-logs`,
      with `sqs_managed_sse_enabled = true` and `message_retention_seconds = 1209600` (14 days).
- [ ] A comment on the resource records the FIFO incompatibility above **with the reason** (the
      sink sends no `MessageGroupId`), so the next person to "fix the inconsistency" with the
      other queues reads why first.
- [ ] `visibility_timeout_seconds` **exceeds the sweep Lambda's timeout** — 360s against a 300s
      function timeout. A comment records the invariant: if visibility is shorter than the
      function timeout, a slow sweep's in-flight messages become visible to the *next* sweep and
      are written to S3 twice.
- [ ] **The portal role is granted nothing on this queue.** A comment records why: the queue's
      contents are the operational record, and a browser that could enqueue could forge log
      events attributing arbitrary activity to arbitrary services. Producers are execution roles
      only. A plan assertion confirms no user-assumable role gains `sqs:SendMessage` on it.
- [ ] **The queue has no DLQ, and no `redrive_policy`.** A comment records why: the only failure
      the sweep can suffer is a failed S3 write, which is not the message's fault — a
      `maxReceiveCount` would move perfectly good events into a second queue nothing reads.
      FR-005's routing makes every message deletable, so there is no poison message to isolate.
- [ ] 14-day retention is documented as **headroom against a broken sweep**, not as the working
      buffer: the sweep runs every 5 minutes, so under normal operation a message lives seconds.

### FR-003: `cpcommon.observability` — the bootstrap, and what it must not do at import

#### Description

Every instrumented handler needs the same three lines: configure the library once, wrap the
handler, flush before returning. That belongs in `cpcommon` so there is one implementation, and it
must be **import-safe**, because the `cpcommon` layer's `config._require` already runs at import
for every attaching function and a single missing variable is a cold-start crash across a whole
control plane (the table-builder production break, PR #196; and the layer-config env-union trap
that a `conftest` env baseline hides from unit tests).

#### Acceptance Criteria:

- [ ] `cpcommon/observability.py` exposes exactly three names: `init(service: str, **defaults)`,
      `flush()`, and the `traced(verb: str)` handler decorator. Nothing else is public.
- [ ] **`traced(verb)` is the only thing a handler is asked to remember.** It applies `@lf.trace`,
      stamps `verb` as a field, and calls `flush()` in a `finally` — so the flush also runs on the
      failure path. A comment records why that matters: the invocation whose trace is most worth
      having is the one that raised, and a flush written at the end of a handler body is exactly
      the line that does not execute when it does.
- [ ] `traced` preserves the wrapped function's name, docstring and signature
      (`functools.wraps`), because Lambda resolves `module.handler` by name.
- [ ] `LOGS_QUEUE_URL` is read with `os.environ.get(...)`, **never `_require`** — it joins
      `NOTIFICATIONS_QUEUE_URL` as an explicitly optional variable. A comment records the rule
      being followed and points at PR #196.
- [ ] With `LOGS_QUEUE_URL` **unset**, `init()` configures the library's zero-dependency
      `StdoutSink` and logs a single line saying structured delivery is disabled. Nothing raises,
      nothing reaches SQS, and local `pytest` gets readable NDJSON on stdout for free.
- [ ] With `LOGS_QUEUE_URL` **set**, the configured sink is **`SQSSink` alone** — not a
      `MultiSink` with `StdoutSink`. A comment records the decision and its cost (user decision,
      2026-07-22): if the queue or the sweep breaks, that window's trace data is gone, and the
      only breadcrumb is `SQSSink`'s own stderr write, which does reach CloudWatch. It also
      records what is **not** affected: the existing stdlib `logging` call sites are untouched
      and CloudWatch still receives every one of them, so SPEC-126 FR-004's forensic log is
      unchanged by this spec.
- [ ] `init()` stamps `service`, `env` (from the environment name), and `version` (a build stamp,
      falling back to `"0.0.0"` when unset). `service` is the **control plane**, not the function
      — `data-quality`, not `data-quality-inspect-source` (user decision, 2026-07-22); the
      per-verb identity rides as a default field instead.
- [ ] `init()` is **idempotent within a process**: calling it twice does not build a second sink
      or a second boto3 client. A test asserts this, because module-level `init()` in a handler
      plus a re-import under test is the ordinary case.
- [ ] `flush()` calls `lf.flush()` and **swallows every exception**, logging at warning. A comment
      records the invariant this protects: *logging must never be the reason a verb fails*. A test
      asserts a sink that raises on emit does not propagate out of `flush()`.
- [ ] A test asserts `import cpcommon.observability` succeeds with `LOGS_QUEUE_URL` absent from
      the environment — written so it cannot be satisfied by the `conftest` env baseline (the
      variable is explicitly deleted, not merely unset by omission).

### FR-004: The sweep pulls; it never long-polls

#### Description

One Lambda, one EventBridge schedule, the same shape as `control-plane-dlq-drain` — for the same
reason. The failure this avoids is subtle: a scheduled consumer that calls `receive_message` with
`WaitTimeSeconds=20` spends 20 billed seconds per empty round doing nothing, which reintroduces
the exact idle-poll cost the pull model exists to eliminate, just from a different direction.

#### Acceptance Criteria:

- [ ] One `aws_cloudwatch_event_rule` with `schedule_expression = "rate(5 minutes)"` targets the
      sweep, plus an `aws_lambda_permission` for `events.amazonaws.com` scoped to that rule's ARN
      (no invoke role needed — the same mechanism as SPEC-126's sweep).
- [ ] A comment records the cadence choice (user decision, 2026-07-22): 5 minutes over the DLQ
      drain's 10, because a log you cannot see for ten minutes is not usable while you are
      debugging the run that produced it; and over 1 minute, because ~43k mostly-empty
      invocations a month would dominate the function's own log group.
- [ ] The sweep calls `receive_message` with **`WaitTimeSeconds=0`** (short poll) and
      `MaxNumberOfMessages=10`, looping until a round returns nothing. A comment records why the
      short poll is mandatory here and not an oversight.
- [ ] A **round cap** bounds one sweep (100 rounds / 1000 messages). When the cap truncates a
      sweep, it is **logged explicitly** with the count — a silent cap reads as "swept everything"
      when it didn't. The next sweep picks up the remainder five minutes later.
- [ ] Terraform owns the function plus a placeholder zip and `ignore_changes = [filename,
      source_code_hash, layers]`; CI deploys the code and attaches `cpcommon`. An explicit
      `aws_cloudwatch_log_group` with 14-day retention, matching every other function here.
- [ ] Function timeout 300s, memory 256 MB. A comment records that the timeout must stay **below**
      the 5-minute schedule interval and **below** the queue's visibility timeout (FR-002).
- [ ] The sweep instruments **itself** through `cpcommon.observability` (`service="observability"`),
      which is what makes this spec end-to-end verifiable without instrumenting a control plane.
      A comment notes the self-reference is safe — its own events go through the same queue and
      are swept on the *next* run, never recursively within one sweep.

### FR-005: Every message is routable, so every message is deletable

#### Description

A sweep that leaves messages on the queue when it cannot make sense of them creates a slow poison
loop: the same body is received, rejected, and redelivered every 5 minutes until retention expires.
`service` also becomes part of an S3 key, and it arrives inside a message body — so it is
**untrusted input on a path**, the same class of surface every validate-authorize verb exists to
police. Both problems have one answer: route everything somewhere, then delete it.

#### Acceptance Criteria:

- [ ] `service` is validated against `^[a-z][a-z0-9-]{2,62}$` before being used in a key. A body
      whose `service` is missing, malformed, or fails the pattern — and a body that is not valid
      JSON at all — is written **verbatim** under `logs/_unrouted/dt=…/hh=…/` and then deleted.
- [ ] A comment records the path-injection reasoning above. A test asserts a body with
      `"service": "../../fallback-results"` lands in `_unrouted/` and that **no object is written
      outside the `logs/` prefix**.
- [ ] Partition values come from the **event's own `timestamp`**, not the sweep's clock. A comment
      records why: a delayed or replayed event stamped with the sweep time lands in the wrong
      hour and is invisible to anyone querying the window it actually belongs to. An event whose
      `timestamp` is missing or unparseable falls back to the sweep clock, and that fallback is
      counted and logged.
- [ ] One sweep therefore writes **one object per `(service, dt, hh)`** it encountered, not one
      object per sweep. The key is
      `logs/{service}/dt=YYYY-MM-DD/hh=HH/{sweep_id}-{seq}.ndjson`, bodies joined with `\n`.
- [ ] `delete_message_batch` runs **only after** the corresponding `put_object` returns
      successfully. A comment records the resulting guarantee and its cost: at-least-once — a
      sweep that writes and then dies before deleting will write those events again next round,
      producing duplicate `log_id`s that a reader collapses. Losing logs is worse than
      duplicating them.
- [ ] A failed `put_object` leaves that group's messages on the queue (they redeliver after the
      visibility timeout) and **does not abort the sweep** — other services' groups still write.
- [ ] The handler is **total**: an unparseable body, a bad `service`, an unparseable timestamp,
      and a failed S3 write are each caught and logged. A test asserts a sweep over a batch
      containing a completely malformed message returns normally rather than raising.

### FR-006: Producers write to the queue and nothing else

#### Acceptance Criteria:

- [ ] The sweep's execution role gains `sqs:ReceiveMessage`, `sqs:DeleteMessage` and
      `sqs:GetQueueAttributes` on the **logs queue ARN only**, and `s3:PutObject` on
      **`{admin-bucket}/logs/*` only** — not the bucket root, which also holds
      `fallback-results/`, `shared-spaces/` and `table-share/`.
- [ ] The sweep role gets **no** `s3:GetObject`, no `s3:DeleteObject`, no Glue, no Athena, and no
      access to the user-space or shared-space buckets. It writes logs; it reads nothing.
- [ ] A **producer policy fragment** grants `sqs:SendMessage` on the logs queue ARN only, ready to
      attach to execution roles. This spec attaches it to the **sweep's own role** (FR-004's
      self-instrumentation) and to nothing else; SPEC-128 attaches it to the data-quality role.
- [ ] The admin bucket is **not** in the user-space bucket-policy allowlist problem space (that
      Deny-all-but-allowlist policy is on the user-space bucket). A comment confirms the sweep
      touches neither user-data bucket, so no allowlist entry is needed — stated explicitly
      because "a new role got a 403 from the user-space bucket policy" has bitten this repo three
      times.

### FR-007: Deploy-role IAM lands first, on its own

#### Acceptance Criteria:

- [ ] A new `infra/modules/base/policies/github-actions-deploy-observability.json.tftpl` grants
      the deploy role what the module needs: the SQS queue, the Lambda + its role and log group,
      and the EventBridge rule + target + Lambda permission.
- [ ] It ships and **applies as its own PR before any resource references it**
      (deploy-perms-before-resources — the standing rule that keeps self-grant propagation races
      and plan-time validation deadlocks out of the resource PR).
- [ ] `s3:PutObject` on `{admin-bucket}/logs/*` is checked against the existing
      `S3AthenaAdminBucketManage` grant in `modules/base` before a duplicate is added.
- [ ] A plan assertion confirms no other module's IAM changed in that PR.
- [ ] Reviewed against architecture.md → *Deploy-role IAM — adding a new resource type* before
      the PR opens (EventBridge rules are a resource type this repo has added exactly once, in
      SPEC-126 — that tftpl is the reference).

### FR-008: Packaging — one line, and the guard that keeps it one line

#### Acceptance Criteria:

- [ ] `log-foundry==0.4.0` is added to `lambdas/control-plane-common/requirements.txt`. The
      cpcommon layer job already `pip install`s that file, so **no workflow change is needed** to
      package it. **Correction found during the build:** that is true of *packaging* and false of
      *testing* — `ci.yml`'s test job installed `lambdas/requirements.txt` and the two polars
      files but never the cpcommon layer's own, so `import log_foundry` failed under `pytest`.
      `ci.yml` gains that one install line.
- [ ] The **core** package is installed, **not** the `[aws]` extra. A comment records why: the
      extra exists only to pull `boto3`, `SQSSink` imports it lazily inside `__init__`, and the
      Lambda runtime already provides `boto3` — installing the extra would put a second copy of
      boto3/botocore on every control-plane verb's 250 MB ceiling to gain nothing.
- [ ] `log-foundry` declares **zero runtime dependencies** for the core install, so the measured
      layer size delta is expected in the tens of KB. The existing combined per-function size
      guard in `deploy-lambdas.yml` (SPEC-107 FR-004) is the check; the layer job's reported
      `unzipped_kb` before and after is recorded in the delivery doc.
- [ ] `deploy-lambdas.yml`'s function matrix gains `log-sweep` with `cpcommon: true`.
- [ ] The three **non-layer** functions (`pre-signup`, `post-confirmation`, `notifications-writer`)
      are **not** given `log-foundry`. A comment in `lambdas/requirements.txt` records that they
      bundle their own dependencies and are out of scope until a spec actually instruments them.

### FR-009: `logs/` is retained forever, and that is a decision with a cost

#### Description

The admin bucket's lifecycle configuration expires `fallback-results/` and `table-share/` at
`admin_results_retention_days`. `logs/` gets no rule (user decision, 2026-07-22): nothing is ever
lost. The cost is unbounded growth with no ceiling and no decision point, and this FR exists so
that is written down where the next person looks rather than discovered on a bill.

#### Acceptance Criteria:

- [ ] **No lifecycle rule is added for `logs/`.** A comment on
      `aws_s3_bucket_lifecycle_configuration.athena_admin` records the decision, the date, and
      the cost in one sentence.
- [ ] The same comment records the **structural invariant** that makes the decision safe: every
      rule in that configuration carries a **prefix filter**, so no rule matches `logs/` by
      accident. S3 lifecycle rules can only include a prefix, never exclude one — a rule added
      later with an empty filter would silently start expiring the logs.
- [ ] A plan/config assertion pins that invariant: every rule in the admin bucket's lifecycle
      configuration has a non-empty `filter.prefix`. **Delivered as an OpenTofu `check` block,
      which WARNS in plan output rather than failing** — the repo has no infra test harness, and
      the hard-failure alternative means re-rendering the lifecycle rules from a local via
      `dynamic`, which is more risk than the guard is worth on a working retention config. The
      warning lands in the PR's own plan comment, which is where the review happens.

---

## Data Model

```jsonc
// One SQS message body = one log-foundry event (the library's schema, unmodified).
{
  "timestamp":      "2026-07-22T14:03:11.482Z",  // UTC ISO-8601 — drives the dt=/hh= partition
  "level":          "INFO",
  "trace_id":       "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id":        "00f067aa0ba902b7",
  "parent_span_id": null,
  "log_id":         "a3f1…",                     // UUID per event — the read-time dedup key
  "function":       "handler",                   // the span name
  "service":        "data-quality",              // CONTROL PLANE, not the function (FR-003)
  "version":        "1.4.2",
  "env":            "prod",
  "fields":         { "verb": "inspect-source", "request_id": "abc-123" },
  "duration_ms":    412,                          // boundary events only
  "status":         "ok",                         // boundary events only
  "error":          null                          // boundary events only
}
```

```
s3://{admin-bucket}/
  logs/
    data-quality/dt=2026-07-22/hh=14/{sweep_id}-0.ndjson
    observability/dt=2026-07-22/hh=14/{sweep_id}-0.ndjson
    _unrouted/dt=2026-07-22/hh=14/{sweep_id}-0.ndjson    # FR-005: unparseable / bad `service`
```

## Environment Variables

No `VITE_` variable — the SPA is untouched.

New **Lambda** environment variable, set by Terraform on every function that logs:

```
LOGS_QUEUE_URL=https://sqs.{region}.amazonaws.com/{account}/{project}-{env}-logs
ENV_NAME={environment}      # stamped as the event's `env` field; added during the build
```

`ENV_NAME` was not in the spec as drafted: FR-003 asks `init()` to stamp `env` "from the
environment name", and no existing variable carried it. It is set from `var.environment`
alongside `LOGS_QUEUE_URL`, in the same env-block edit, and is optional in the same way
(`os.environ.get`, never `_require`).

Optional by construction (FR-003): read with `os.environ.get`, never `_require`. Unset means
stdout, not a crash. Because the `cpcommon` layer's `config` runs `_require` at import for every
attaching function, this variable being optional is what lets SPEC-127 ship without touching the
environment block of all 34 functions at once.

## File & Folder Structure

```
lambdas/log-sweep/log_sweep.py                              (+ test_log_sweep.py)
lambdas/control-plane-common/cpcommon/observability.py      (+ test_observability_cpcommon.py)
lambdas/control-plane-common/requirements.txt               # + log-foundry==0.4.0 (exact pin)
infra/modules/observability/
├── sqs.tf                                                  # the standard logs queue
├── lambda.tf                                               # sweep function, log group, schedule
├── iam.tf                                                  # sweep role + the producer fragment
├── locals.tf  variables.tf  outputs.tf
└── policies/
infra/modules/base/policies/github-actions-deploy-observability.json.tftpl   # PR 1, applies first
infra/modules/analytics/s3.tf                               # + the FR-009 retention comment
infra/main.tf                                               # module wiring
.github/workflows/deploy-lambdas.yml                        # + log-sweep in the matrix
```

## Implementation Phases

### Phase 1: Upstream release + deploy-role IAM

- Cut `log-foundry` 0.3.0: `requires-python >=3.12`, public `flush()` (FR-001).
- The `github-actions-deploy-observability` tftpl, shipped and **applied on its own** before any
  resource references it.

### Phase 2: The bootstrap + the queue

- Pin `log-foundry==0.4.0` into the cpcommon layer requirements; confirm the layer size delta.
- `cpcommon/observability.py` + tests, including the import-safe-without-`LOGS_QUEUE_URL` test
  and the flush-swallows-everything test.
- The standard logs queue and the producer policy fragment.

### Phase 3: The sweep

- `log_sweep.py`: short-poll receive loop, round cap, group by `(service, dt, hh)`, `_unrouted`
  routing, put-then-delete ordering, total per-message paths.
- The module's function, role, log group, EventBridge rule + target + permission; root wiring;
  the `deploy-lambdas.yml` matrix entry; the FR-009 comment and lifecycle assertion.

### Phase 4: Live verification

- Deploy, then confirm on the **first invoke after deploy** that the sweep does not crash at cold
  start — the `cpcommon` layer's import-time `_require` is the one failure mode no unit test can
  reach (PR #196), and this function's environment block is new.
- Trigger a sweep with the queue empty; assert it completes, writes nothing, and costs one short
  poll (no 20-second wait in the duration metric).
- Hand-place a well-formed event and a deliberately malformed one on the queue. Assert the first
  lands at `logs/observability/dt=…/hh=…/`, the second at `logs/_unrouted/…`, that both are
  deleted from the queue, and that the partition matches the **event's** timestamp rather than
  the sweep's.
- Hand-place an event with `"service": "../../fallback-results"`; assert nothing is written
  outside `logs/`.
- Completion ritual. **The SPEC-074 help sweep is expected to be a no-op** — nothing here is
  user-facing — and the delivery doc says so explicitly rather than skipping the step silently.
