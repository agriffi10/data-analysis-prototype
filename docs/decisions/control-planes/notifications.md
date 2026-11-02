---
type: Decision
title: "Notifications (SPEC-058→061)"
description: "**A notification's optional `link` is gated by `isSafeInAppPath`**, and a route that renders one must not become an existence oracle: the data-quality report view takes its space **from the route, never derived**, and an unreachable space renders denied while issuing **no S3 request at all**."
---

Per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}` — plus an **optional `link`**, SPEC-113 FR-008: an in-app path the message renders as, gated at render by `isSafeInAppPath` so it can never become an open redirect; absent = plain text, which is every pre-113 producer). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues ~~(`sqs:SendMessage`)~~ **— superseded by SPEC-200:** its two user actions through the API's `notifications.enqueue`, holding no grant on the queue. Anti-spoofing = ~~user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim~~ **— superseded by SPEC-201:** a user action carries the API's `identity` block, read through `cpcommon.actor`, and any body username is ignored (`create` = trusted-producer-only — **enforced since SPEC-206** by the writer refusing a `create` whose SQS-stamped `SenderId` names the portal role; ~~the grant itself is unconditioned and cannot be otherwise, since no SQS condition key reaches a message body~~ **— superseded by SPEC-200:** the portal role holds no grant on the queue at all). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; **059 browser data layer done** — `features/notifications/` read service + `useNotifications` + prefetch; **060 UI done** — header `NotificationsBell` link + `/notifications` page (10/page, mark-read/all, optimistic + Toast); **061 done** — the 062 verb Lambdas emit `create` inline via `notify.emit_notification` (orchestrator role gains `sqs:SendMessage` to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` env), best-effort.)

The data-quality report view takes its space from the route, never derived, and an unreachable space renders denied while issuing no S3 request at all, so a route that renders a notification's link cannot become an existence oracle.

## History

### 2026-06-27

- **Settled:** SPEC-058→061.
