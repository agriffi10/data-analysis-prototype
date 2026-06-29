# Completed Spec — SPEC-061: Shared-Workspace Notification Producer

## What was completed?

The **first trusted `create` producer** of the notifications inbox (SPEC-058). The
shared-space control plane now emits a `create` notification at each lifecycle terminal
outcome — **producer-side only**: no UI, no new notifications infra. The `notify.py` emit
helper itself shipped as a no-op seam in SPEC-062; this spec wired it (grant + env) and
added the inline call sites.

- **Wiring (IaC):**
  - Root `infra/main.tf`: constructed-string locals `notifications_queue_arn` / `_url`
    (cycle-free, known at plan — no `shared_spaces→notifications` dependency), passed into
    `module.shared_spaces`.
  - `infra/modules/shared-spaces/variables.tf`: new `notifications_queue_arn` /
    `notifications_queue_url` (default `""`, so the module still validates standalone).
  - `policies/orchestrator-permissions.json.tftpl`: one `EmitNotifications` statement —
    `sqs:SendMessage` on the **notifications queue ARN only** (no other pipeline action).
    The single shared orchestrator role is the exec role for every verb, so this one grant
    covers all emitting verbs (SPEC-062 FR-005).
  - `lambda.tf`: `NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url` on every verb env.
- **Emit calls (Python, in the SPEC-062 verb Lambdas, via `from notify import emit_notification`):**
  - `shared-space-create/create_space.py` — event 1 (`active` → creator) + event 2
    (`failed` → creator, with the recorded reason). Replay of an already-active create
    emits nothing.
  - `shared-space-add-members/add_members.py` — events 3/4/5 (added user / at-limit→owner /
    unknown→owner), **collected during the loop and flushed only after the registry write**
    (FR-007); bulk emits per affected user; already-members emit nothing.
  - `shared-space-leave/leave.py` — event 6 (member left → owner); no-op leave emits nothing.
  - `shared-space-delete/delete_space.py` — event 7: fan-out to **every member** (captured
    before the cascade clears the registry; owner ∈ members), deduped, deleter gets the
    distinct "You deleted…" message.
  - `shared-space-remove-members` emits nothing (not one of the seven events).
  - Each send sets `MessageGroupId = recipient` (FIFO per-user order) and a
    `MessageDeduplicationId = {requestId}:{event}:{recipient}`. `emit_notification` is
    best-effort (catches + logs, never raises) and a no-op when `NOTIFICATIONS_QUEUE_URL`
    is unset.
- **Tests:** emit assertions added to all four verb suites (recipient + message + dedup id;
  bulk add per-user; delete fan-out deduped with distinct deleter message; no-op/replay
  silence; a swallowed emit failure doesn't change the delete outcome). `91 passed`.
- **Docs:** producer flow + the seven-event table + `simulate-custom-policy` scopability
  added to `docs/testing/notifications-e2e.md`; the stale "no notifications yet" check in
  `docs/testing/shared-spaces-e2e.md` now points to it.

## What changed from earlier specs?

- **SPEC-062 verbs** gained inline emit calls + the `notify` import; `add_members` was
  restructured to defer notifications until after the registry write. Behavior of the
  workspace operations themselves is unchanged.
- **No deploy-role IAM change:** this only adds a statement to an existing inline policy on
  an existing role (the deploy role already manages it) and creates no new resource type.

## Verification

`tofu validate` clean; orchestrator policy renders valid JSON with the scoped
`sqs:SendMessage`; ruff clean; `91 passed` (pytest `lambdas/`). End-to-end producer flow
(real create/add/leave/delete → `create` on the notifications queue → writer appends →
recipient sees it in the SPEC-060 page) documented in `notifications-e2e.md` for execution
against the deployed environment.
