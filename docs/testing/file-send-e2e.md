# Send Files — control-plane e2e / smoke test

Manual verification for the file-send control plane (`infra/modules/file-send/`). Grows with the
arc: **SPEC-164** is the plane and its front door, **SPEC-165** the source resolution, **SPEC-166**
the transfer and the terminals. A send now really copies.

**Run the sections in order, in one session** — checks 1 and 4 leave files in `bob`'s inbox that
check 7 expects to find empty, so if you are running 7–10 on their own, clear it first (the
cleanup at the end of each section says how).

The pipeline as it stands:

```
Browser → SQS (FIFO requests.fifo) → EventBridge Pipe (batch 1) → Step Function (Standard)
   ValidateAuthorize → Validated → InspectSource → GuardRecipients → BuildTransferManifest
        → HasTransferItems → [TransferObjects] → CollectTransferResults → ShapeSummary → Succeeded
        (validate failure     → ValidateFailureSeed ─┐)
        (any later failure    → RequestFailureSeed  ─┴→ RecordFailure → NotifyFailure → Failed)
        (execution timeout    → EventBridge TIMED_OUT rule → notify-failure, second door)
```

## Before anything: the identity you run this as

**A laptop IAM user cannot read or write `dat-prod-user-space`.** Its bucket policy denies every
principal outside a hand-maintained allowlist — the portal role, the deploy role and the control
planes' execution roles — so `aws s3 ls`, `cp`, `sync` and `head-object` on that bucket come back
`AccessDenied` from an ordinary CLI identity. That is the isolation model working, not a fault
(CLAUDE.md records it).

Two ways through, and it matters which you pick:

- **Stage and verify through the portal UI** for anything in a *user's* space — upload the fixture
  files in the file browser, and look at `bob`'s inbox by signing in as `bob`. Slower, and it is
  what actually proves a recipient can see what arrived.
- **Assume a role on the allowlist** for the CLI steps. Every `dat-prod-user-space` command below
  assumes you have done one of these. `dat-prod-shared-space` has no bucket policy, so the
  `finance` half of check 7 works from an ordinary identity.

The admin bucket (`dat-prod-athena-admin`) and the Step Functions / SQS / logs calls need no
special identity.

Resource names (defaults; `dat`/`prod`):

| Resource | Name |
|---|---|
| Request queue | `dat-prod-file-send-requests.fifo` |
| DLQ | `dat-prod-file-send-requests-dlq.fifo` (swept by the SPEC-126 drain) |
| Pipe | `dat-prod-file-send-pipe` |
| State machine | `dat-prod-file-send-orchestrator` |
| Verb Lambdas | `dat-prod-file-send-{validate-authorize,inspect-source,check-target-absent,build-transfer-manifest,copy-objects,collect-transfer-results,notify-failure}` |
| fscommon layer | `dat-prod-file-send-common` (attached to every verb but `copy-objects`, beside `cpcommon`) |
| Timeout rule | `dat-prod-file-send-orchestrator-timed-out` (EventBridge → `notify-failure`) |
| Execution role | `dat-prod-file-send-execution-role` (ONE shared role) |
| Copy plans | `s3://dat-prod-athena-admin/file-send/{requestId}/copy-plan.json` |
| Transfer manifest | `s3://dat-prod-athena-admin/file-send/{requestId}/transfer-manifest.jsonl` |
| Map Run export | `s3://dat-prod-athena-admin/file-send/{requestId}/results/` |

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

The key must name an object that **really exists** in your own space. validate-authorize still
does not check, but since SPEC-165 inspect-source HEADs every `file` item, so a made-up key now
fails the run with `source_missing` — a correct outcome, just not the one this check is about.

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

- Status **Succeeded**, running to `ShapeSummary` → `Succeeded` (SPEC-164 ended at `Validated`; that
  state is still there and still the thing to read for everything below).
- `Validated`'s output carries `actor: {"username": "alice"}` — **from the token, never the body**
  (the body has no username field at all).
- `recipients` carries `bob` unannotated and `nosuchspace` with `"invalid": "unknown_space"` —
  **an unreachable recipient annotates rather than failing the request**.
- `source` resolved to `{"bucket": "dat-prod-user-space", "root": "alice/"}`.
- **Since SPEC-166 this check also COPIES.** `q1.csv` really lands at
  `bob/shared_files/alice/q1.csv`, and `nosuchspace` is refused as `unknown_space` — so the
  summary carries one `ok` and one `failed`. Clear it before check 7, which expects `bob`'s inbox
  to be empty:

  ```bash
  aws s3 rm --recursive "s3://dat-prod-user-space/bob/shared_files/alice/"
  ```
- **No notification** is sent — the plane is silent until SPEC-167 adds the producer.

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

Passing checks 1–3 discharges SPEC-164's Phase 4. They do **not** touch:

- The **DLQ drain path** — nothing here dead-letters. A malformed body fails *inside* the machine
  and notifies from `NotifyFailure`; reaching the DLQ needs the target to fail repeatedly.
- **`NotifyFailure`'s own reason for existing** — a failure where *no verb ran at all* (a cold-start
  import error). Check 2 exercises the state, but the sentence comes from the verb's own decorator
  and `fs_notify_failure` suppresses its duplicate. To exercise the real path you would have to
  break a layer attachment deliberately; not worth doing on a live plane, and the import-safety
  probe covers the packaging.
- The **transfer** itself, beyond the single object check 1 now copies as a side effect. The guard,
  the manifest and the Map Run are checks 7–10.

---

## SPEC-165 — source resolution and the copy plan

**Goal:** prove that a folder is expanded **past the 1,000-key pagination boundary**, that the
plan's `objectCount` matches the bucket exactly, and that the plan reaches the admin bucket
carrying what SPEC-166's manifest builder will read.

**Why the pagination is the thing.** Everything else here has a fixture that proves it, and the
fixture is only ever as honest as the fake that pages for it. A verb that read `Contents` once and
stopped does not error — it reports 1,000 and copies a silently truncated folder. Against real S3
the number is either right or it is not.

Runs on top of check 1's setup: same `$TOKEN`, same `$QUEUE`, same username substitution.

### Before you start — build a folder over the boundary

Any prefix in your own space with **more than 1,000 objects**. Cheapest way, ~2 minutes:

```bash
mkdir -p /tmp/fs-big && for i in $(seq 1 1200); do printf 'row\n' > "/tmp/fs-big/$(printf '%05d' $i).csv"; done
aws s3 sync /tmp/fs-big "s3://dat-prod-user-space/alice/fs-big/"
```

Record the truth to compare against — this is the number the whole check turns on:

```bash
aws s3api list-objects-v2 --bucket dat-prod-user-space --prefix "alice/fs-big/" \
  --query 'length(Contents)' --output text
```

### Check 4 — a folder past the pagination boundary is planned whole

```bash
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$(printf 'dat-prod-user-space/alice/' | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "fs-live-4" \
  --message-body "$(cat <<JSON
{"requestId":"fs-live-4","actor":"$TOKEN",
 "source":{"space":{"kind":"personal","name":"alice"},
           "items":[{"kind":"folder","key":"alice/fs-big/"}]},
 "recipients":[{"kind":"user","name":"bob"}]}
JSON
)"
```

**Expect, in the execution history:**

- Status **Succeeded**, running to `ShapeSummary` → `Succeeded`.
- **`InspectSource`'s output** carries `objectCount` **exactly equal to the `list-objects-v2` count above**
  — not 1,000, and not one more than the count (the `DO_NOT_DELETE.txt` marker is excluded, but
  it lives at the space root, not in this folder).
- `copyPlanKey` is `file-send/fs-live-4/copy-plan.json`, and `totalBytes` is non-zero.
- **No object key anywhere on the state.** Search the execution's `InspectSource` output for
  `00001.csv`: it must not be there. That is the pointer working — at the caps the object list is
  two orders of magnitude over the 256 KB payload limit.

Then read the plan itself:

```bash
aws s3 cp s3://dat-prod-athena-admin/file-send/fs-live-4/copy-plan.json - | python3 -m json.tool | head -20
```

**Expect:** `sender: "alice"`, `source: {bucket, root}`, `objectCount` matching again, and every
entry carrying `item: "fs-big"`, a `relKey` like `00001.csv` (**relative to the selected folder,
not the space**), an absolute `srcKey`, and a `size`.

### Check 5 — an overlapping selection is refused, and the sentence is actionable

```bash
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$(printf 'dat-prod-user-space/alice/' | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "fs-live-5" \
  --message-body "$(cat <<JSON
{"requestId":"fs-live-5","actor":"$TOKEN",
 "source":{"space":{"kind":"personal","name":"alice"},
           "items":[{"kind":"folder","key":"alice/fs-big/"},
                    {"kind":"file","key":"alice/fs-big/00001.csv"}]},
 "recipients":[{"kind":"user","name":"bob"}]}
JSON
)"
```

**Expect:**

- Status **Failed**, through `RequestFailureSeed → RecordFailure → NotifyFailure → Failed` — the
  **new** seed, not `ValidateFailureSeed`. If the execution dies with `States.Runtime` before
  `RecordFailure`, the seed is not supplying `$.raw` and nobody was notified.
- **A notification in alice's inbox**: *"Couldn't send: one of the folders you selected already
  contains another thing you selected. Please send one or the other."*
- **No copy plan written** for `fs-live-5`. `aws s3 ls s3://dat-prod-athena-admin/file-send/fs-live-5/`
  returns nothing — every layout rule fires before the write.
- `RequestFailureSeed`'s output carries `actor: {"username": "alice"}`, taken from the state
  rather than re-derived from the token. That is the difference from the SPEC-164 seed.

### Check 6 — the spans are in the log lake

```bash
aws s3 cp "s3://dat-prod-athena-admin/logs/service=file-send/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/data.jsonl" - | tail -20
```

**Expect:** a `copy plan built` event for run 4 carrying `objects`, `bytes` and `items`, with
`verb: inspect-source`; and for run 5 a failed span. **No object key, no token, no file contents
in any field** — `objects` is a count, and the keys live in the plan the event points at.

### Clean up

```bash
aws s3 rm --recursive "s3://dat-prod-user-space/alice/fs-big/"
```

The copy plans expire on their own (`expire-file-send-copy-plans`, `modules/analytics/s3.tf`) and
the execution role holds an explicit `Deny s3:DeleteObject` on the admin bucket, so there is
nothing to tidy there and nothing that could tidy it.

### What this discharges, and what it does not

Passing 4–6 discharges SPEC-165's Phase 4. It does **not** touch:

- **The caps.** 20,000 objects and 1 TiB are not reachable by hand, and their models are computed
  in `test_config_fscommon.py` against the verb's configured memory and the transfer engine's
  makespan rate. What check 4 does prove is the term those models rest on — that the listing is
  complete.
- **The transfer's own machinery.** Check 4's 1,200 objects *are* now copied to `bob` as a side
  effect of the send completing — clear them before check 7, which expects an empty inbox:

  ```bash
  aws s3 rm --recursive "s3://dat-prod-user-space/bob/shared_files/alice/"
  ```

  What checks 4–6 do not touch is the guard, the manifest, the per-recipient attribution or the
  terminals. Those are checks 7–10.

---

## SPEC-166 — the guard, the transfer and the terminals

**Goal:** prove that a send actually **lands in someone else's space**, that a name already there
refuses that recipient and nobody else, and that the run is recorded.

**Why this one cannot be inferred.** Everything up to here is read-only, and every offline test of
the copy runs against a fake. The `*/shared_files/*` scoping on the execution role, the
cross-bucket write into the shared-space bucket, and the user-space bucket policy's allowlist are
three separate gates that all render, apply and unit-test green while denying the first real copy.
Only a real send exercises them.

Runs on top of check 1's setup: same `$TOKEN`, same `$QUEUE`, same username substitution.

**You need THREE real Cognito users and one shared space** before you start: yourself (`alice`),
`bob` and `carol`, plus a space `finance`. Carol is check 8's control — a recipient who has never
received anything from you — and if she does not exist the guard refuses her `unknown_user`
instead, which is a different outcome from the one check 8 is looking for. The **space need not
have you as a member**, which is itself part of what check 7 shows.

Every check below reads the execution, so set this once — the machine has one execution per
request and the name is the Pipe's, not yours, so look it up by start time:

```bash
MACHINE=arn:aws:states:us-east-1:696000197480:stateMachine:dat-prod-file-send-orchestrator
exec_arn() {  # exec_arn → the most recent execution's ARN
  aws stepfunctions list-executions --state-machine-arn "$MACHINE" --max-items 1 \
    --query 'executions[0].executionArn' --output text
}
wait_done() {  # wait_done → blocks until it leaves RUNNING, then prints the status
  local arn; arn=$(exec_arn)
  while [ "$(aws stepfunctions describe-execution --execution-arn "$arn" --query status --output text)" = RUNNING ]; do
    sleep 20
  done
  aws stepfunctions describe-execution --execution-arn "$arn" --query status --output text
}
```

### Before you start

```bash
# A folder of several hundred objects plus one loose file.
mkdir -p /tmp/fs-send && for i in $(seq 1 300); do printf 'row\n' > "/tmp/fs-send/$(printf '%04d' $i).csv"; done
aws s3 sync /tmp/fs-send "s3://dat-prod-user-space/alice/reports/"
printf 'hello\n' | aws s3 cp - "s3://dat-prod-user-space/alice/notes.txt"

# The truth to compare against.
aws s3api list-objects-v2 --bucket dat-prod-user-space --prefix "alice/reports/" \
  --query 'length(Contents)' --output text
```

Confirm `bob`'s inbox is empty first, so a pass cannot be a leftover:

```bash
aws s3 ls "s3://dat-prod-user-space/bob/shared_files/alice/" --recursive | head
```

### Check 7 — two recipients receive every object, at the right key

```bash
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$(printf 'dat-prod-user-space/alice/' | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "fs-live-7" \
  --message-body "$(cat <<JSON
{"requestId":"fs-live-7","actor":"$TOKEN",
 "source":{"space":{"kind":"personal","name":"alice"},
           "items":[{"kind":"folder","key":"alice/reports/"},{"kind":"file","key":"alice/notes.txt"}]},
 "recipients":[{"kind":"user","name":"bob"},{"kind":"space","name":"finance"}]}
JSON
)"
```

Then, once it finishes (`wait_done` prints `SUCCEEDED` — a 300-object send takes a minute or two):

```bash
EXEC=$(exec_arn); wait_done
```

Confirm **all four** of:

```bash
# 1. Every object arrived, in BOTH spaces. Both numbers must equal the folder's count.
aws s3api list-objects-v2 --bucket dat-prod-user-space \
  --prefix "bob/shared_files/alice/reports/" --query 'length(Contents)' --output text
aws s3api list-objects-v2 --bucket dat-prod-shared-space \
  --prefix "finance/shared_files/alice/reports/" --query 'length(Contents)' --output text

# 2. The loose file is a FILE at the item name, not a folder under it.
aws s3api head-object --bucket dat-prod-user-space --key "bob/shared_files/alice/notes.txt" \
  --query 'ContentLength'

# 3. The structure inside the folder survived: a nested key keeps its relative path.
aws s3 ls "s3://dat-prod-user-space/bob/shared_files/alice/reports/" | head -3

# 4. The terminal names both recipients exactly once, with status ok.
aws stepfunctions describe-execution --execution-arn "$EXEC" --query output --output text | python3 -m json.tool
```

The execution output is `ShapeSummary`: `{requestId, sender, itemNames, objectCount, recipients}`.
`recipients` must hold **two** entries, both `"status": "ok"`, and `objectCount` must equal the
number you recorded before you started **plus one** for `notes.txt`.

> **A `space` recipient you are not a member of is expected to work.** Recipients are a lookup, not
> an authorization question — the execution role does the write. If this fails with `unknown_space`,
> the space's registry status is not `active`, which is a different thing from membership.

### Check 8 — a repeat is a per-recipient conflict that names the item

Send **exactly the same request again** with a new `requestId`/dedup id (`fs-live-8`), but add a
third recipient who has never received anything from you:

```bash
 "recipients":[{"kind":"user","name":"bob"},{"kind":"space","name":"finance"},{"kind":"user","name":"carol"}]
```

Expect, in the execution output:

- `bob` and `finance` — `"status": "failed"`, `"reason": "conflict"`, and **`"detail": "reports"`**
  (the first item name in selection order). The colliding name is the point: SPEC-167 tells the
  sender *which* file was already there.
- `carol` — `"status": "ok"`, having received everything.
- **Nothing under `bob/shared_files/alice/` changed.** Compare an ETag before and after if you want
  it airtight; the count alone would not catch an overwrite in place.

That one run is the whole of FR-001: a conflict refuses **that recipient**, never the request, and
never overwrites.

### Check 9 — the run is in the log lake

```bash
aws s3 cp "s3://dat-prod-athena-admin/logs/service=file-send/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/data.jsonl" - \
  | grep fs-live-7 | python3 -c 'import sys,json; [print(json.loads(l)["message"]) for l in sys]' | sort | uniq -c
```

The sweep runs every 10 minutes, so give it that long before concluding anything is missing.
The output must carry, for check 7's `request_id`: `send validated`, `copy plan built`,
`target absent` (one per recipient), `transfer manifest built`, **one `batch copied` per child
execution**, and `transfer results attributed`. The `batch copied` count is the one worth reading —
it is the only place the fan-out is visible, and a run that copied everything in one batch means
the `ItemBatcher` is not batching.

### Check 10 (IAM) — simulate against the DEPLOYED role, WITH the bucket policy

```bash
ROLE=arn:aws:iam::696000197480:role/dat-prod-file-send-execution-role
POLICY=$(aws s3api get-bucket-policy --bucket dat-prod-user-space --query Policy --output text)

# Allowed: an inbox write.  Denied: anywhere else in the same user's prefix.
aws iam simulate-principal-policy --policy-source-arn "$ROLE" \
  --action-names s3:PutObject \
  --resource-arns arn:aws:s3:::dat-prod-user-space/bob/shared_files/alice/notes.txt \
                  arn:aws:s3:::dat-prod-user-space/bob/reports/notes.txt \
  --resource-policy "$POLICY" \
  --query 'EvaluationResults[].{a:EvalResourceName,d:EvalDecision}' --output table
```

Expect `allowed` for the first and `implicitDeny` for the second.

Two ways this goes wrong that are worth recognising rather than debugging:

- **Both come back `explicitDeny`.** The bucket policy denies on `StringNotLike aws:PrincipalArn`,
  and a *missing* context key makes that condition true — so if the simulator did not populate the
  principal ARN, everything reads as denied. Add
  `--context-entries ContextKeyName=aws:PrincipalArn,ContextKeyValues=$ROLE,ContextKeyType=string`.
- **The call errors on the resource policy.** Same-account should not need it; add
  `--resource-owner 696000197480` if it does.

> **`--resource-policy` is not optional here, and omitting it is worse than skipping the check.**
> `simulate-principal-policy` does not consult a bucket policy on its own, so without it the
> simulation returns `allowed` for a `PutObject` the real call denies — a false green on the one
> gate that is invisible from the identity policy. Pair every expected `implicitDeny` with an
> expected `allowed` beside it, for SPEC-149/157's reason: an `implicitDeny` alone cannot tell an
> ungranted action from a mistyped ARN.

### Clean up

```bash
aws s3 rm --recursive "s3://dat-prod-user-space/bob/shared_files/alice/"
aws s3 rm --recursive "s3://dat-prod-shared-space/finance/shared_files/alice/"
aws s3 rm --recursive "s3://dat-prod-user-space/carol/shared_files/alice/"
aws s3 rm --recursive "s3://dat-prod-user-space/alice/reports/"
aws s3 rm "s3://dat-prod-user-space/alice/notes.txt"
```

The transfer manifest and the Map Run's export expire with the copy plan
(`expire-file-send-copy-plans`), and the execution role cannot delete them — 30 days clears the
3-hour ceiling 240 times over.

### What this discharges, and what it does not

Passing 7–10 discharges SPEC-166's Phase 4. It does **not** touch:

- **The caps.** None of the three is reachable by hand; their models are computed in
  `test_config_fscommon.py` against the verbs' configured memory, the batch verb's timeout and the
  machine's own ceiling.
- **The timeout and its rule.** A three-hour run is not something to stage. What can be checked
  cheaply, and is worth doing once, is that the rule exists and points at the notifier:
  `aws events list-targets-by-rule --rule dat-prod-file-send-orchestrator-timed-out`.
- **Notifications.** Nothing tells the sender or the recipient anything yet — SPEC-167.

---

## SPEC-167 — the UI and the notifications

**Goal:** prove that the two halves nobody can check offline actually meet — the browser really
enqueues what the toolbar selected, and the notification link the Python producer mints really
lands the recipient on what arrived.

**Safari**, because that is the browser this project is used in and the one its tooling is not.

Runs against the deployed app, signed in. You need the same three users and one shared space as
checks 7–10, and `bob`'s inbox clear (`aws s3 rm --recursive
"s3://dat-prod-user-space/bob/shared_files/alice/"`, from an identity on the allowlist).

### Check 11 — the send, at both widths

1. Sign in as `alice`, open **Files**, and tick a **folder** and a **file**.
2. At **desktop**: the toolbar shows **Send to…** beside Copy / Move / Delete. Click it.
3. The dialog names what is being sent by **item name** with a count — not the full key.
4. Type `bo` under **Users**: suggestions appear. Commit `bob`. Switch to **Shared spaces**, type
   `fin`: suggestions appear **under this kind too** (that is SPEC-146's directory read and
   SPEC-158's connections source, both live). Commit `finance`.
5. Several chips must still leave **Send** reachable — scroll the dialog body, not the page.
6. Send. The dialog closes, the selection clears, and the toast says the send was **requested**.
7. Repeat the whole thing at **400px** (Safari's responsive design mode): the control is
   **icon-only** and the dialog is usable — the chip list wraps and the footer stays put.

### Check 12 — what each party is told, and where the link goes

Within a minute or two of check 11:

- **alice** has **two** notifications, one per recipient, each naming the recipient and the count.
- **bob** (sign in as bob) has one naming alice, the items and the count. **Click it.** It must
  land in `shared_files/alice/` **with the files there** — not at his space root. That is the whole
  check: the prefix is minted in Python and honoured by a TypeScript route rule, and the failure
  mode is a link that looks like it worked.
- **finance's owner** has one saying it went to their SPACE. No other member of `finance` has
  anything.

Then **send the same selection again** to `bob` and one new user. alice gets a `conflict`
notification **naming the item** (`reports`), the new user receives everything, and nothing under
`bob/shared_files/alice/` changed.

### What this discharges, and what it does not

Passing 11–12 discharges SPEC-167's Phase 4, and with checks 7–10 the whole arc. It does **not**
touch the flag-off states (the registry test walks all four surfaces in both states offline) or the
timeout door.
