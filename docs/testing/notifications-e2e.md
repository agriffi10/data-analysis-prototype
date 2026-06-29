# Notifications Write-Pipeline — Contract + Smoke Test (SPEC-058)

**Purpose:** Document the SQS message contract every producer builds to, and prove the
**write side** is wired end-to-end against deployed infrastructure: a message on the FIFO
request queue triggers the **notifications-writer Lambda** directly (SQS event-source
mapping — **no Pipe, no Step Function**), which read-modify-writes the target user's
`{username}/user_settings/notifications.json`. SPEC-058 ships **no browser/UI** (the read
service + hook are SPEC-059; the header bell + page are SPEC-060; the first real `create`
producer is SPEC-061).

**Scope covered:** FR-001 (FIFO queue → writer, per-user serialization), FR-002 (writer
role scopability), FR-003 (message contract), FR-004 (read-modify-write + cap),
FR-005 (actor binding), FR-006 (portal-role `sqs:SendMessage`), FR-008 (this test).

> **Status:** ✅ Executed 2026-06-28 against the deployed environment — two `create`
> messages for one user processed strictly in arrival order (writer logged the inbox
> growing `… -> 1` then `… -> 2`, proving FIFO per-user serialization + read-modify-write
> with no lost update); a token-less `markAllRead` was rejected (`AuthorizationError:
> missing idToken` → invocation fails → retry → DLQ). The object content + live
> `markRead`/`markAllRead` need a real Cognito ID token (the writer denies my admin user
> data access on the bucket by design) — covered by the unit tests; re-run as the live
> regression once a token is available. Two IAM gaps were fixed during bring-up: the
> writer's bucket-policy-Deny exclusion (SPEC-051 shape) and its prefix-conditioned
> `s3:ListBucket` (the new-user 404 disambiguation).

---

## Message contract (FR-003)

One envelope per message, `action`-discriminated. **Every** message is sent with
**`MessageGroupId` = the target username** so FIFO serializes a single user's writes
one-at-a-time (the recipient for `create`; the caller's own username for user actions),
plus a `MessageDeduplicationId` — or rely on the queue's content-based dedup — so an
accidental duplicate send is collapsed inside the 5-minute window.

```jsonc
// create — TRUSTED PRODUCER only (e.g. a shared-workspace verb Lambda, SPEC-061).
// Uses the body `username`; the portal role is NOT granted to enqueue this.
// MessageGroupId = "alice"
{ "action": "create", "username": "alice", "message": "Your shared workspace \"salesdata\" is ready." }

// markRead — user-originated (browser). idToken REQUIRED; username is DERIVED from the
// verified cognito:username claim (any body username is ignored). MessageGroupId = caller's username.
{ "action": "markRead", "id": "b3f1…", "idToken": "<cognito id token>" }

// markAllRead — user-originated (browser). idToken REQUIRED. MessageGroupId = caller's username.
{ "action": "markAllRead", "idToken": "<cognito id token>" }

// There is NO delete / deleteAll — notifications are never removed, only marked read.
```

The stored document at `{username}/user_settings/notifications.json` is a plain array,
newest-first, capped to `NOTIFICATIONS_MAX` (default 200) by timestamp:

```jsonc
[
  { "id": "b3f1…", "message": "Your export finished.", "read": false, "timestamp": "2026-06-22T14:03:11.482Z" }
]
```

**Ordering guarantee (FR-004):** the request queue is FIFO and the event-source mapping
uses **batch size 1**, so for a given `MessageGroupId` (= username) the writer processes
messages strictly in arrival order, one at a time — the next isn't released until the
prior is deleted. Two rapid messages for the same user therefore both land with no lost
update, without a Step Function or external lock. Different users are different groups and
may process concurrently (different files, no contention).

---

## Prerequisites

- [ ] `deploy-infra.yml` has applied SPEC-058 (the deploy-role grants in PR 1/2 **and**
  the `module.notifications` resources in PR 2/2).
- [ ] `deploy-lambdas.yml` has deployed the `notifications-writer` code (push touching
  `lambdas/**`, or run the workflow manually) — until then the placeholder raises on invoke.
- [ ] AWS CLI configured against the same account/region.

Capture environment values (from `infra/`):

```bash
QUEUE_URL=$(tofu output -raw notifications_queue_url)   # ends in .fifo
REGION=us-east-1 ; PROJECT=dat ; ENV=prod
FN="${PROJECT}-${ENV}-notifications-writer"
BUCKET="${PROJECT}-${ENV}-user-space"
USER=alice
```

## Step 1 — `create` produces the inbox (FR-001/FR-004/FR-008)

```bash
aws sqs send-message --queue-url "$QUEUE_URL" \
  --message-group-id "$USER" \
  --message-body "{\"action\":\"create\",\"username\":\"$USER\",\"message\":\"Smoke test\"}"
```

- [ ] Within ~1 minute the writer logs the invocation and `notifications.json` exists:

```bash
aws logs tail "/aws/lambda/${FN}" --since 5m            # "notifications create for alice -> 1"
aws s3api get-object --bucket "$BUCKET" --key "$USER/user_settings/notifications.json" /dev/stdout
# -> [{"id":"…","message":"Smoke test","read":false,"timestamp":"…"}]
```

## Step 2 — `markRead` / `markAllRead` flip `read` (FR-004/FR-005)

User actions require a real Cognito **ID token**. Mint one (e.g. via the app, or
`aws cognito-idp initiate-auth`) for `$USER`; the writer derives the username from it and
ignores any body username.

```bash
TOKEN=<cognito id token for alice> ; ID=<an id from step 1>
aws sqs send-message --queue-url "$QUEUE_URL" --message-group-id "$USER" \
  --message-body "{\"action\":\"markRead\",\"id\":\"$ID\",\"idToken\":\"$TOKEN\"}"
# then mark all:
aws sqs send-message --queue-url "$QUEUE_URL" --message-group-id "$USER" \
  --message-body "{\"action\":\"markAllRead\",\"idToken\":\"$TOKEN\"}"
```

- [ ] After `markRead`, the matching id has `read:true`; after `markAllRead`, every entry does.

## Step 3 — Per-user serialization (FR-004)

- [ ] Send two `create` messages quickly with the **same** `--message-group-id "$USER"`;
  both appear in `notifications.json` (newest-first) — no lost update.

## Step 4 — Malformed / forged message → DLQ, no write (FR-003/FR-005)

```bash
# missing token on a user action -> AuthorizationError -> retried -> DLQ:
aws sqs send-message --queue-url "$QUEUE_URL" --message-group-id "$USER" \
  --message-body '{"action":"markAllRead"}'
```

- [ ] No write occurs; after `maxReceiveCount` (3) the message lands on
  `${PROJECT}-${ENV}-notifications-requests-dlq.fifo` (`aws sqs receive-message` on the DLQ URL).

## Step 5 — IAM scopability (FR-002/FR-006) — ✅ verified 2026-06-28 via `simulate-custom-policy`

Verified locally against the rendered **writer** policy (pass the policy **inline** —
`--policy-input-list "$(cat policy.json | tr -d '\n')"`; the `file://` form is rejected as
"invalid content"):

| Action / resource | Decision |
|---|---|
| `s3:PutObject` → `…/alice/user_settings/notifications.json` | `allowed` |
| `s3:PutObject` → `…/alice/user_settings/shared-connections.json` (adjacent key) | `implicitDeny` |
| `s3:DeleteObject` → `…/alice/user_settings/notifications.json` (no delete granted) | `implicitDeny` |
| `sqs:ReceiveMessage` → the request queue | `allowed` |

- [x] Writer role: read/write only the notifications doc, no delete anywhere, queue receive only.
- [ ] Portal role: `sqs:SendMessage` to the request queue only (review the rendered
  `portal-role-notifications` policy / simulate `sqs:SendMessage`); **no** Lambda invoke,
  DLQ, or writer-role access, and it **cannot** enqueue a `create` (reserved for trusted
  producers — SPEC-061).

---

## Producer flow — shared-workspace control plane (SPEC-061)

The **first trusted `create` producer**. Each shared-space verb Lambda (SPEC-062:
create / add-members / leave / delete — run under the single orchestrator role) emits a
`create` notification at its **terminal** outcome via the shared `notify.emit_notification`
helper, scoped to the notifications queue ARN only (`sqs:SendMessage`). `remove_members`
emits nothing. The seven events:

| # | Action / outcome | Recipient | Message |
|---|---|---|---|
| 1 | `create` → active | creator | `Your shared workspace "{name}" is ready.` |
| 2 | `create` → failed | creator | `We couldn't create shared workspace "{name}": {reason}.` |
| 3 | `add_members` → added | the added user | `You've been added to the shared workspace "{name}".` |
| 4 | `add_members` → at-limit | owner | `Couldn't add "{user}" to "{name}": they've reached their workspace limit.` |
| 5 | `add_members` → unknown user | owner | `Couldn't add "{user}" to "{name}": no such user.` |
| 6 | `leave` → member left | owner | `"{user}" left the shared workspace "{name}".` |
| 7 | `delete` → cascade success | **every member** (incl. deleter), deduped | deleter: `You deleted the shared workspace "{name}".`; others: `The shared workspace "{name}" was deleted.` |

**IAM scopability (FR-001)** — verify against the rendered **orchestrator** policy
(`simulate-custom-policy`, inline `--policy-input-list`):

| Action / resource | Decision |
|---|---|
| `sqs:SendMessage` → the notifications queue ARN | `allowed` |
| `sqs:SendMessage` → an unrelated queue ARN | `implicitDeny` |

**End-to-end** (against the deployed environment, after `deploy-infra` + `deploy-lambdas`):

```bash
# Drive a real create through the control plane (browser, or send to the shared-space
# request queue), then watch the create notification land on the notifications queue and
# the writer append the recipient's row:
aws logs tail "/aws/lambda/dat-prod-shared-space-create" --since 5m   # "create salesdata by alice -> active"
aws logs tail "/aws/lambda/dat-prod-notifications-writer" --since 5m  # "notifications create for alice -> N"
aws s3api get-object --bucket dat-prod-user-space \
  --key alice/user_settings/notifications.json /dev/stdout
# -> [{"id":"…","message":"Your shared workspace \"salesdata\" is ready.","read":false,"timestamp":"…"}]
```

- [ ] Create (success + name-collision failure), add-members (added / at-limit / unknown),
  leave, and delete each land the expected row(s); delete fans out to every member with the
  deleter's distinct message. The recipient(s) then see them in the notifications page (SPEC-060).
- [ ] Best-effort: a notify failure (e.g. queue throttled) is logged and the workspace
  action still completes — never rolled back.

---

## Notes

- **Trusted producers.** `create` is enqueued only by identities explicitly granted
  `sqs:SendMessage` on the queue. SPEC-058 exposes the queue ARN as an output and grants
  the portal role (user actions only); the **first** `create` producer — the
  shared-workspace control plane (seven lifecycle events) — is wired in **SPEC-061**
  (see *Producer flow* above).
- **Offline token verification.** The writer verifies ID tokens against the pool JWKS over
  HTTPS (no Cognito IAM), mirroring the shared-space provisioner.
