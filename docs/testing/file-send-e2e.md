# Send Files — control-plane e2e / smoke test

Manual verification for the file-send control plane (`infra/modules/file-send/`). Grows with the
arc; **SPEC-164** covers the plane and its front door — a request is validated or refused, and
nothing is listed or copied. SPEC-165/166 add source resolution, the transfer and the terminals.

The pipeline as it stands:

```
Browser → SQS (FIFO requests.fifo) → EventBridge Pipe (batch 1) → Step Function (Standard)
   ValidateAuthorize → Validated → Succeeded
        (failure → ValidateFailureSeed → RecordFailure → NotifyFailure → Failed)
```

Resource names (defaults; `dat`/`prod`):

| Resource | Name |
|---|---|
| Request queue | `dat-prod-file-send-requests.fifo` |
| DLQ | `dat-prod-file-send-requests-dlq.fifo` (swept by the SPEC-126 drain) |
| Pipe | `dat-prod-file-send-pipe` |
| State machine | `dat-prod-file-send-orchestrator` |
| Verb Lambdas | `dat-prod-file-send-{validate-authorize,notify-failure}` |
| fscommon layer | `dat-prod-file-send-common` (attached to both, beside `cpcommon`) |
| Execution role | `dat-prod-file-send-execution-role` (ONE shared role) |

---

## SPEC-164 — the front door

**Goal:** prove that a legitimate request reaches the placeholder terminal, that an unauthorized
one is refused *and the sender is told*, and that both appear in `logs/service=file-send/`.

**Why it cannot be a unit test.** A shared layer's import-time failure surfaces at **cold start**
— `conftest.py` puts the layer on `sys.path`, and `update-function-code` succeeds against a
function that cannot import (PR #196, and SPEC-137's nine-day sign-up break). Only a real
invocation proves the layer is attached.

### Before you start

You need a valid ID token for a real user. Sign in to the portal, open the browser console and
read it from the Amplify session, or use `aws cognito-idp initiate-auth`. Everything below assumes
the token is in `$TOKEN` and the user is `alice` — substitute your own username **everywhere**,
including the keys, or check 1 will legitimately fail as `forbidden`.

```bash
QUEUE=$(aws sqs get-queue-url --queue-name dat-prod-file-send-requests.fifo --query QueueUrl --output text)
```

### Check 1 — a valid request reaches the placeholder terminal

The key must name an object that really exists in your own space (validate-authorize does not
check existence, but SPEC-165 will, and using a real key makes this fixture reusable).

```bash
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$(printf 'dat-prod-user-space/alice/' | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "fs-live-1" \
  --message-body "$(cat <<JSON
{"requestId":"fs-live-1","actor":"$TOKEN",
 "source":{"space":{"kind":"personal","name":"alice"},
           "items":[{"kind":"file","key":"alice/reports/q1.csv"}]},
 "recipients":[{"kind":"user","name":"bob"},{"kind":"space","name":"nosuchspace"}]}
JSON
)"
```

**Expect, in the execution history:**

- Status **Succeeded**, ending at `Validated` → `Succeeded`.
- `Validated`'s output carries `actor: {"username": "alice"}` — **from the token, never the body**
  (the body has no username field at all).
- `recipients` carries `bob` unannotated and `nosuchspace` with `"invalid": "unknown_space"` —
  **an unreachable recipient annotates rather than failing the request**.
- `source` resolved to `{"bucket": "dat-prod-user-space", "root": "alice/"}`.
- **No notification** is sent. Nothing failed.

### Check 2 — an unauthorized source is refused, and the sender hears about it

Same shape, but the key names someone else's space. `bob` here is any username that is not yours.

```bash
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$(printf 'dat-prod-user-space/alice/' | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "fs-live-2" \
  --message-body "$(cat <<JSON
{"requestId":"fs-live-2","actor":"$TOKEN",
 "source":{"space":{"kind":"personal","name":"alice"},
           "items":[{"kind":"file","key":"bob/secrets.csv"}]},
 "recipients":[{"kind":"user","name":"bob"}]}
JSON
)"
```

**Expect:**

- Status **Failed**, through `ValidateFailureSeed → RecordFailure → NotifyFailure → Failed`.
- **A notification in alice's inbox** reading *"Couldn't send: You don't have access to send those
  files."* — check it in the portal's notification bell, not only in the queue.
- **The notification names no key.** `bob/secrets.csv` must appear nowhere in the message text
  (it is on the exception, for the logs and the execution record).
- `RecordFailure`'s output carries `error` as the raw `{Error, Cause}` pair — **not** a decoded
  reason. An ASL decode is the uncatchable `States.Runtime` of #252.

### Check 3 — the two spans are in the log lake

Both runs write to `logs/service=file-send/year=…/month=…/day=…/data.jsonl` in the admin bucket,
swept every 10 minutes — **wait for the sweep before concluding anything is missing**.

```bash
aws s3 cp "s3://dat-prod-athena-admin/logs/service=file-send/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/data.jsonl" - | tail -20
```

**Expect:** a `send validated` event for run 1 carrying `recipients_requested`,
`recipients_reachable` and `unreachable_recipients`; and for run 2 a failed span plus
`notified the sender of a failure`. **No token, and no file contents, in any field.**

### What this discharges, and what it does not

Passing all three discharges SPEC-164's Phase 4. It does **not** touch:

- The **DLQ drain path** — nothing here dead-letters. A malformed body fails *inside* the machine
  and notifies from `NotifyFailure`; reaching the DLQ needs the target to fail repeatedly.
- **`NotifyFailure`'s own reason for existing** — a failure where *no verb ran at all* (a cold-start
  import error). Check 2 exercises the state, but the sentence comes from the verb's own decorator
  and `fs_notify_failure` suppresses its duplicate. To exercise the real path you would have to
  break a layer attachment deliberately; not worth doing on a live plane, and the import-safety
  probe covers the packaging.
- Anything about **copying**. Nothing is copied until SPEC-166.
