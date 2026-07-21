# Completed Spec — SPEC-114: Data Quality — Notification Producer

## What was completed?

The data-quality arc's completion channel. Before this, a finished check surfaced **nowhere**:
`dq_notify_failure` was a SPEC-108 pass-through stub, nothing emitted on success, and the runs
dashboard is SPEC-123 — so the only route to a report was typing its URL.

- **Success** — `dq_assemble_report.handler` emits one notification to the actor *after* the report
  object is written, so a link can never point at a report that doesn't exist. Carries the verdict,
  the top issues, and the `/data-quality/{space}/{requestId}` link.
- **`dqcommon/notify.py`** (new) — `emit_completed`, `emit_failure`, `emit_unexpected`,
  `notifies_on_failure(step)`, and **`report_link`**, which mirrors the report view's resolution
  precedence from the producer side and returns `None` rather than mint a link the view would
  resolve to the wrong space (both kinds are checked, not just shared — see the module comment).
- **`dqcommon/messages.py`** — `success_message` + `NOTIFY_ISSUES` (names 2 issues, always states
  the total). Every FR-002 reason code was already registered by SPEC-109→111; nothing was added.
- **`dq_notify_failure.py`** — the real handler for the failures no verb can catch (import errors,
  SFN-level errors), decoding the raw `$.error` with `cpcommon.errors.failure_reason`.
- `@notifies_on_failure` on all eight verb handlers.
- **Infra:** one statement — `sqs:SendMessage` scoped to the notifications queue ARN.

**Deviation from the spec, both agreed in-session:**

- **FR-005 (CloudWatch DLQ + `ExecutionsFailed` alarms) was removed, not implemented.** Two alarms
  with no notification target, on one arc of five, told the *user* nothing. Replaced wholesale by
  **SPEC-126** (drain every control plane's request DLQ into the notification pipeline), which is
  what SPEC-123's completed-checks-only dashboard now depends on.
- **The spec was widened to make one ASL change**, having originally forbidden any (below).

## What changed from earlier specs?

- **`cpcommon.errors.TerminalError` gains an optional `tokens` mapping** (default `None`;
  table-builder and table-share untouched). It is the inverse of `detail` — `detail` is raw service
  text for operators and never reaches a user, `tokens` fills the `{object}`/`{count}` markers that
  SPEC-110/111 had already written into `dqcommon/messages.py` and which would otherwise render
  literally. Deliberately **not** part of the exception message: `failure_reason` splits that on its
  first colon, and an S3 key containing one would corrupt the split.
- **`cpcommon.notify.emit_notification` gains an optional `link`** (SPEC-113 FR-008's wire field,
  first producer here). Omitted from the body when falsy rather than sent as null.
- **`dq_validate_authorize` now binds the actor BEFORE its shape checks.** It ran them first, so
  every `invalid_request` terminal raised with no actor bound — and this is the one verb that cannot
  fall back to `NotifyFailure`, because `ValidateFailureSeed` seeds `actor: null`. Those failures
  notified nobody. `unauthorized` still doesn't, correctly: no proven identity, no inbox to write to.
- **The state machine gains `reportKey`** on `ValidateFailureSeed` (seeded null) and `RecordFailure`
  (read). A non-null value there can only mean the report was written and the success notification
  already went out, so `notify-failure` stays silent instead of contradicting it — closing the case
  where a post-report **cleanup Lambda** failure sent both a success and a failure message. (The
  ordinary Glue cleanup error never reaches a terminal: `_drop` has swallowed those since SPEC-111.)
  No state added, removed, or re-pointed; nothing decodes an error Cause.
- **SPEC-113's guard test is inverted, not deleted** — it asserted the dialog promised no
  notification; it now asserts it promises one. Dialog, toast, and `helpContent.ts` copy restored.

## Verification

`pytest lambdas/` 971 passed · `vitest` 1129 passed · `npm run build`/`lint`/`format` · `tofu
validate` · CI plan confirmed exactly 2 in-place resources and no catalog permission added.

**16 mutations, 16 guard failures** — every new assertion was verified to fail when the thing it
guards is broken. One found a real defect: the pre-identity test was passing on `cpcommon`'s
empty-username no-op rather than this handler's own guard, i.e. it would have stayed green with that
guard deleted; rewritten to assert no recipient is ever derived from a body-supplied username.

A new **general ASL invariant** (`test_state_machines_cpcommon.py`) asserts every Pass state
reachable from a failure seed reads only keys that seed supplies — the trap that has now caught this
arc twice (`location` in SPEC-112, `reportKey` here). Verified to fire for the SPEC-112 case too.

**Deferred:** the live end-to-end (user decision, 2026-07-21) — no further smoke tests until 114,
123 and 124 are all built, then one pass over the arc. The scenarios this spec needs that pass to
cover are listed in its Phase 2, and the arc-level note in `CLAUDE.md` points at them. **So the
producer is unproven against real SQS/SFN/Cognito**, and the `reportKey` seeding in particular is the
kind of change the SPEC-108 live smoke test has caught before.
