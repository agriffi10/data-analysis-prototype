# Completed Spec — SPEC-072: Table Builder Notification Producer

## What was completed?

The table-builder pipeline is now a **trusted producer** of the SPEC-058 notifications
inbox: every verb Lambda emits ONE `create` notification to the **actor** at its terminal
branch — a reason-specific failure message, and a success message from `execute-ddl`.
Producer-side only (no UI, no new notifications infra). One PR — statements on existing
verb roles + env + inline calls, no new resource type (the SPEC-061 precedent).

- **Shared helpers (the `tbcommon` layer):**
  - `tbcommon/notify.py` — `emit_notification(username, message, dedup_id)` (best-effort:
    catches+logs, never raises; no-op when `NOTIFICATIONS_QUEUE_URL` unset **or** no
    recipient) + `emit_failure(event, err, step)` / `emit_created(event)` convenience
    wrappers that read actor/table/database/requestId from the validated event and set
    FIFO `MessageGroupId = actor`, `MessageDeduplicationId = {requestId}:{step}`.
  - `tbcommon/messages.py` — the reason→message map (SPEC-072 Data Model), one source of
    truth for the wording; `unauthorized`/`forbidden` share a generic access line (no table
    name), the DDL reasons fold in a short detail, unknown reasons fall back without leaking
    the code.
- **Emit call sites (inline, at the already-defined terminal branches):**
  - `check` / `inspect` / `infer` / `execute` — a `try/except TerminalError` wrapper emits
    then re-raises (transient errors aren't `TerminalError`, so they pass through un-emitted).
  - `validate-authorize` — actor is derived mid-handler, so only the post-actor branch
    (`forbidden` / `invalid_table_name` / `invalid_partition_keys`) is wrapped; `unauthorized`
    raises **before** the actor exists → no recipient → no emit (still recorded by the SFN).
  - `execute-ddl` — `emit_created` on terminal `status:created`; `emit_failure` on a terminal
    DDL error.
- **IaC:**
  - `infra/main.tf`: passes the existing constructed-string `notifications_queue_arn` /
    `_url` locals (SPEC-061) into `module.table_builder`.
  - module `variables.tf`: new `notifications_queue_arn` / `notifications_queue_url`
    (default `""` → standalone-plannable).
  - `lambda.tf`: `NOTIFICATIONS_QUEUE_URL` added to the **common** env block (all five verbs
    emit).
  - `iam.tf` + all five `policies/<verb>.json.tftpl`: one `EmitNotifications` statement —
    `sqs:SendMessage` on the **notifications queue ARN only**.
- **CI fix:** `deploy-lambdas.yml` flips **execute-ddl to `tbcommon: true`**. It already
  imported `from tbcommon import config` (SPEC-070) but was still `tbcommon: false`, so it
  got **no `tbcommon` layer** — a latent import bug. It now imports `tbcommon.notify` too, so
  the layer is required; the flip fixes both. (The layer-build copies the whole `tbcommon`
  package, so the new `notify.py`/`messages.py` ship automatically.)

## What changed from earlier specs?

- The five SPEC-067→070 verbs gained inline emit calls + the `notify` import; behaviour of
  the pipeline steps themselves is unchanged (same terminal reasons, same outcomes).
- **No deploy-role IAM change** — only adds statements to existing verb-role policies (the
  deploy role already `PutRolePolicy`s `*-table-builder-*`) and creates no new resource type.

## Verification

`python3 -m pytest lambdas/` = **194 passed** (minus infer-schema's polars tests, which run
in CI); the new `test_notify.py` (8) + `test_messages.py` (10) cover the helper + full
message map, and each verb suite gained emit assertions (actor recipient + mapped message +
`{requestId}:{step}` dedup; **silence** on transient/non-terminal and on `unauthorized`).
`ruff check lambdas/` clean; `tofu fmt`/`validate` clean; all five verb policy templates
render valid JSON with the scoped `sqs:SendMessage`. End-to-end producer flow (a real create
that succeeds/fails → the actor sees the ready/failure message on the SPEC-060 `/notifications`
page) documented in `docs/testing/table-builder-e2e.md` for execution against the deployed
environment.

**This completes the table-builder arc (SPEC-066→072).**
