# Completed Spec — SPEC-094: Table Share Notification Producer (sender + recipients)

## What was completed?

- **`tscommon.notify`** (+ `tscommon.messages`, `clients.sqs()`): best-effort `create` emits to the SPEC-058 notifications FIFO queue (grouped by target user; the queue's content-based dedup — no per-message dedup id). Never raises; logged no-op when `NOTIFICATIONS_QUEUE_URL` (optional in config) is unset. `_context` reads both event shapes (whole-request vs Map `{recipient, request}`).
- **Sender (actor) notifications**: one per recipient outcome — success (*"Shared "orders" to user "bob" as "orders_copy"."*) or failure with the mapped reason (conflict names the table; `create_failed`/`create_timeout` carry Athena's reason; access-denied reasons surface no detail) — plus a single whole-request failure message (validate/inspect), emitted at each owning verb's terminal branch (SPEC-072 pattern): validate-authorize (post-token-verification only — pre-auth failures have no trusted recipient), inspect-source, check-target-absent, copy-objects, create-table.
- **Success-target notifications** (create-table success only): a **user** recipient in their own inbox; a **space** recipient via the registry record's **`owner`** — owner only, never members; lookup failures/absent owner skip the owner message without touching the sender's (FR-002). Failures never notify the recipient side.
- **`notifies_on_failure` wrapper** on all five verbs: an unexpected (non-Terminal/non-Transient) exception emits a generic sender notification before propagating — no silent failures (mirrors table-builder SPEC-072).
- **Infra**: execution role + `sqs:SendMessage` scoped to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` in the common Lambda env; root passes the constructed queue ARN/URL locals into `module.table_share`.

## What changed from earlier specs?

- No new notifications infrastructure (SPEC-058 owns the pipeline); no UI change (the SPEC-093 Help guide already tells users outcomes arrive as notifications — sweep satisfied). Table-share is the third trusted `create` producer after shared-spaces (061) and table-builder (072).

## Verification

10 new notify/messages tests (envelope shape, no-op/never-raises guarantees, per-recipient vs whole-request wording, detail interpolation, user vs space-owner fan-out, owner-lookup degradation, wrapper Terminal/Transient/unexpected routing) — full Lambda suite 321 green; `tofu validate` + `fmt` clean. Live proof: covered by the arc's end-to-end share (SPEC-092/093 delivery notes) — the sender + recipient inbox entries are its observable outcome.
