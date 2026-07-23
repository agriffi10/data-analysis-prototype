# Completed Spec — SPEC-127: Structured Logging Foundation

## What shipped

- **`cpcommon/observability.py`** — `init()` / `flush()` / `traced(verb)`. `LOGS_QUEUE_URL` is read
  with `os.environ.get`, never `_require`; unset means stdout, not a cold-start crash.
- **`{project}-{env}-logs`** — a **standard** (non-FIFO) SQS queue. `SQSSink` sends no
  `MessageGroupId` and FIFO rejects batches without one. Visibility 360s > the 300s function
  timeout; no DLQ (every message is routable, so none is poison).
- **`log-sweep`** — EventBridge `rate(5 minutes)` → short-poll drain → group by
  `(service, dt, hh)` from the **event's own** timestamp → NDJSON under
  `logs/{service}/dt=…/hh=…/` → delete **only after** a successful put. Self-instrumented
  (`service="observability"`).
- **`infra/modules/observability/`** + the deploy-role `.tftpl` (shipped and applied on its own
  first, per deploy-perms-before-resources).
- `log-foundry==0.4.0` pinned exactly into the cpcommon layer (core, not the `[aws]` extra).

## Deviations from the spec as drafted

1. **The pin is 0.4.0, not 0.3.0.** A third upstream blocker surfaced during the build:
   `start_event`/`end_event` passed `baggage={}` hardcoded, so `request_id` never reached the
   records carrying `duration_ms`/`status` — SPEC-128 FR-002 would have been unachievable. Fixed
   upstream as **log-forge SPEC-015**.
2. **FR-008's "no workflow change is needed" held for packaging, not testing.** `ci.yml` never
   installed the cpcommon layer requirements, so `import log_foundry` failed under pytest. One
   install line added.
3. **`ENV_NAME` is a second new Lambda env var.** FR-003 asks `init()` to stamp `env`; nothing
   carried the environment name.
4. **FR-009's assertion is an OpenTofu `check` block — it warns, it does not fail.** The repo has
   no infra test harness, and a hard gate would mean re-rendering the lifecycle rules via
   `dynamic`. Recorded as a warning-not-gate rather than left to look like a hard check.
5. **`traced()` resets baggage per invocation** (not in the spec). Baggage is a contextvar and a
   warm container reuses it, so a run that set `request_id` leaked it into the next.

## What changed from earlier specs

- `infra/modules/analytics/s3.tf` — a comment recording that `logs/` gets **no** lifecycle rule
  (FR-009) plus the `check` block pinning the prefix-scoped invariant. No rule changed.
- `.github/workflows/ci.yml` — one `pip install` line. `deploy-lambdas.yml` — one matrix row.
- Nothing in any control plane. No verb was touched by this spec.

## Verification

Local: `pytest lambdas/` 1088 passed, `ruff` clean, `tofu validate`/`fmt` clean. Four mutations
(service-pattern check, put-then-delete gating, `flush` in `finally`, `init` idempotence) each
failed exactly the right tests.

**Live, against real SQS/S3/Lambda (2026-07-23):**

| Check | Result |
|---|---|
| Cold start (the cpcommon `_require` union — PR #196's failure mode) | **pass**, no `FunctionError` |
| Empty-queue sweep | `{"swept": 0, "written": 0}`, **205 ms** — no 20s long poll |
| Well-formed event | → `logs/observability/dt=2026-07-01/hh=03/` — the **event's** timestamp, not the sweep clock (which was 07-23 00:03) |
| Non-JSON body | → `logs/_unrouted/…`, preserved **verbatim**, deleted |
| `"service": "../../fallback-results"` | → `logs/_unrouted/…`; admin bucket still holds only `logs/` and `shared-spaces/` — nothing escaped |
| Self-instrumentation | `service=observability`, `env=prod`, `verb=sweep`, `duration_ms`, `status=ok` — swept on the *next* run, not recursively |

**SPEC-074 help sweep: no-op.** Nothing here is user-facing — no UI, no permission, no copy. Stated
explicitly rather than skipped silently.

## Known leftovers

The live-verification artifacts are still in `logs/` (an `_unrouted/` object and a fabricated
`dt=2026-07-01` event). They are tiny but they are synthetic records in a store retained forever —
delete them if that matters.
