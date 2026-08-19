# The owed ledger

Every check that [`e2e.md`](e2e.md) cannot settle from one signed-in browser session, why, and what
it would take. **This file is the record — a check is owed until someone runs it and moves it out.**

**Settling a premise is not running the check.** A proxied assertion, an offline test that pins the
same property, and a Chromium run standing in for Safari are all recorded here, not discharged.

---

## 1. What is owed

### Needs a second (or third) account

| Check | Why one account cannot do it |
|---|---|
| **Receiving a send** (SPEC-167) — bob's link lands in `shared_files/alice/` with the files there; the space recipient's link carries `?space=` and lands in the space, not the sender's own files | The prefix is minted in Python and honoured by a TypeScript route rule; the failure mode is a link that *looks* like it worked. Needs `alice`, `bob`, `carol` and a shared space alice does **not** own (an owner who is also the sender gets two messages for one outcome, which changes every count). |
| **Membership as a non-owner member** — the Data Explorer against a shared space, archive/restore in one, the roster | Runs against real Cognito tags and real Lake Formation. The one-sided version passes trivially. |
| **Add → acknowledge → read roster** (SPEC-125, after SPEC-186 FR-008) | The acknowledge fan-out is what closed a roster saying `Pending` for a member the same page showed `Active`. Only a second account can flip it. |
| **Cross-user prefix isolation** (SPEC-013 FR-004) | As `alice`, every S3 verb against `bob/` is denied and a root listing leaks nothing, while the same calls against `alice/` succeed. The app never issues the cross-prefix call, so it needs two users' portal credentials or a policy simulation. The **paired success is what makes the denial mean anything**, and it must be driven from `npm run dev` — the production bundle's console cannot `import()` a bare specifier. |
| **A share's recipient queries the result** (SPEC-161) | `SELECT count(*)` from the recipient's own database must return the source's row count, not zero. |

### Needs the CLI

| Check | Why | Recipe |
|---|---|---|
| **The `DO_NOT_DELETE.txt` Deny on the portal role**, personal and shared (SPEC-173) | The portal issues **zero** `DeleteObject` against the marker — it is hidden by basename and the folder delete is refused client-side first. The Deny is the layer that matters if the SPA is ever wrong. | §2.1 |
| **Refresh-lock contention** (SPEC-157) | Two UI submits 2 s apart both return independently — a small table's refresh finishes inside that window, so the lock is never contended. Nothing that runs today proves two real executions serialize. | §2.2 |
| **A malformed message on a request DLQ** (SPEC-133 Phase 5; also discharges SPEC-126's) | The user is notified, the message is gone, and the redacted body is in `logs/service=dlq-drain/`. Nothing in the app can send a malformed request. | §2.2 |
| **The archive/restore negative assertion** — for a refused restore, **no** `RestoreObject` for that archive id | A refusal that had already begun retrieval is invisible from the UI and costs 3–5 billed hours. Read the audit trail, never `head-object`. | §2.4 |
| **The vault prefix is swept after a restore** (SPEC-171 FR-005) | Nothing human can read `dat-prod-archive`, and the browser sees only the receipt folder, which survives by design. `aws s3api list-objects-v2 --bucket dat-prod-archive --prefix "personal/$USERNAME/archive/$ARCHIVE_ID/" --max-keys 5` → **`KeyCount: 0`**, `_manifest.json` included. Needs a principal on that bucket's allowlist, which no human identity is. | — |
| **`head-object` on user-space or archive** — restored objects back at `STANDARD`, content type survived, byte-identical | The laptop identity is explicitly denied on both buckets, and the UI cannot show a storage class. | — |
| **The `>5 GiB` metadata round trip** (SPEC-171, and all three transfer planes) | `CreateMultipartUpload` carries no `MetadataDirective`, so before the fix every object over 5 GiB lost its content type on every copy this repo makes. Only an object over the threshold exercises it; a fixture below it passes forever. Confirm `ContentType` survives by `head-object`. |
| **The restore plan agrees with the receipt** (SPEC-170) | `s3://dat-prod-athena-admin/archive/{requestId}/restore-plan.json` exists, its entry count equals the receipt's `Files archived`, and two `destKey`s match the original paths by eye. |
| **The archive plane's log events** (SPEC-169/170/171) | `logs/service=archive/` carries `restore plan built` and `destinations clear` for the request, with **`manifest_present: true`**; then `batch retrieval requested` per Map child, `retrieval polled` **hours apart** with `poll_count` climbing, and a `cleanup` block after the sweep. |
| **The fan-out is visible exactly once per child** (SPEC-166/167) | `logs/service=file-send/` carries one `batch copied` event per child execution. It is the only place the Distributed Map's fan-out can be seen. |
| **Table share at scale** (SPEC-160/161) — a several-hundred-object, >20 GiB table shared to two recipients where one conflicts; the 100-column clone read back with all 100 comments through `GetTable`; and the over-cap refusal — with ~500 objects, **41 recipients** exceeds it — whose operator detail reads `N recipients x M objects is <product> transfer items (cap 20000)` while the notification says only *"that's too many files to copy to that many recipients at once."* | The counts and the clone are only readable through Glue and the structured log. | §2.5 |
| **The `TIMED_OUT` door** (table-share, file-send, archive) | Waiting out a real 3-hour timeout is not a test anyone will run. Confirm the rule matches `TIMED_OUT` **and not** `FAILED`, that it targets the notifier, and drive the handler with a synthetic event. | §2.5 |

### Control-plane bring-up, only reachable through a hand-crafted request

These prove the plane itself, not the feature, and the UI cannot stage them. The first four are
driven by a hand-crafted request (§2.2); SPEC-108's has its own recipe in §2.3; SPEC-058's is a
policy simulation (§2.8). **SPEC-169's Deny-on-one-key needs a temporary policy edit and has no
recipe anywhere** — write one when you run it.

| Check | Why it matters |
|---|---|
| **The `cpcommon` layer attaches at cold start** (SPEC-168, and every plane) | SPEC-137 shipped instrumented code whose layer attachment was missing and **every offline gate passed** — `conftest.py` puts the layer on `sys.path`, and `update-function-code` succeeds against a function that cannot import. A hand-crafted request through the queue is the only thing that runs the real cold start. |
| **A `PutObject` into your own `archive/` prefix is refused**, personal and shared (SPEC-168) | The browser Deny that stops a receipt being forged. The app never issues the call. |
| **A Deny on ONE key mid-archive** (SPEC-169 step 3) | The whole point of the commit gate: the run fails, **every source object is still there**, the archive prefix is empty, and the notification is honest. Nothing else exercises the rollback arm against real S3. |
| **The pagination boundary** (SPEC-165) | Over a **1,200-object** folder, `InspectSource`'s `objectCount` equals the `list-objects-v2` count exactly — **not 1,000**, and not one more than it — the `DO_NOT_DELETE.txt` marker is excluded, but it lives at the **space root**, not in this folder. The only live proof the lister paginates. |
| **The state order, including the poll loop** (SPEC-108, data quality) | **`WaitForQuery`/`CheckQuery` must appear TWICE** — one pass through is a poll that never polled. Recipe in §2.3. |
| **The portal role can enqueue a user action and NOT a `create`** (SPEC-058) | The anti-spoof boundary: a browser that could enqueue `create` could write any user's inbox. Simulate `sqs:SendMessage` against the notifications queue and read the rendered policy. |
| **The seven shared-space producer events** (SPEC-061), especially **delete fanning out to every member** | One notification per member per event, from the verified actor. A missed fan-out is silent. |
| **A shared space whose NAME is not catalog-safe** (2026-08-19) | The premise behind `sqlIdentifier`/`sqlDdlIdentifier` on `CREATE VIEW` and `DROP`: `shared-space-validate` applies **no format check** to `space` on the create path, so the browser dialog is the only thing holding the rule. Enqueue a create for a name containing a backtick, a double quote or a space (§2.2), then confirm from the member's browser that dropping a table in it and creating a view from it both run — and that the rendered statement quotes the name rather than breaking on it. **If Glue itself refuses the name, say so and close this** — that would mean the quoting is belt to a braces that already holds, which is worth knowing either way. |

### Needs a second account for the REFUSAL half

| Check | Note |
|---|---|
| **Shared-space authorization negatives** (SPEC-053/054) | A **non-owner** `add_members` and `remove_members`; an **owner** trying to `leave`; a **non-owner** trying to `delete`. Each must fail in `Validate` with no side effect. The positive half is in `e2e.md` §4.8 and passes trivially. |
| **A forged or expired `idToken`** | Fails in `Validate` (Catch → `Failed`) with no side effect — auth is server-side, and this is the only check that says so live. |
| **A stale membership tag reads as `AccessDenied`** | Sign the member out and in again before concluding anything about a membership check. Without the token refresh a correct system looks broken. |

### Needs infrastructure that is deliberately not created

| Check | Blocker |
|---|---|
| **`Description` and column-comment preservation across a refresh** (SPEC-149) — both survive, the columns changed, `get-table-versions` shows a previous version | Needs the `dat-prod-verification` role. From any other principal Glue returns *Insufficient Lake Formation permission(s): Required Describe*. See §2.5. |
| **The foreign projection fixture** (SPEC-153 FR-006 AC2) | The same `GetTable` response. Paste it **verbatim** when you have it — the shipped fixture is docs-transcribed. |

### Needs Safari, or 400px

| Check | Note |
|---|---|
| **The whole CSS list** (`e2e.md` §4.15) | A Chromium run **corroborates and cannot discharge** rendering. Andrew browses in Safari. |
| **The 400px pass** | Not reachable by window resize on macOS — Chrome's floor is 606px, and `resize_window` reports success while changing nothing the page sees. Use DevTools device toolbar (⌘⇧M) and assert on `matchMedia`. |

### Not observable at all

| Check | Why |
|---|---|
| The restore's **`Restore` header format**, and `GLACIER`-stays-`GLACIER` on the archived object | The audit trail does not report either. The plane's own `complete: false → true` polling corroborates it; that is not the same thing. |
| **`SaveQueryDialog`'s "nowhere to save" state** (SPEC-186's ninth dialog) | Needs the personal space unavailable, which cannot be staged from the UI. |
| **SPEC-151 FR-006's escaping over a real partition segment containing `'`** | Asserted at render time only. If such a folder ever fails, suspect the engine before the renderer. |
| **SPEC-151 FR-003's failure direction** | A denied key cannot be staged from the UI; unit-tested only. |
| **A partial restore, and `restore_timed_out`** | Forcing one item to fail mid-copy means denying a destination the guard would have refused up front. Seven hours of waiting to observe a counter. |
| **Stale root-level static assets** (SPEC-141) | An accepted orphan class, not a check. Removals are by hand, and **not verifiable by status code** — the distribution maps `403/404 → /index.html` with a **200**, so check `content-type` and `x-cache: Error from cloudfront`. |

---

## 2. Recipes

### 2.1 Credentials as the portal role

Needed for anything refused by an **IAM layer the app never reaches**. The `DO_NOT_DELETE.txt` Deny
is in the **portal role's own identity policy** — `data/policies/portal-role-permissions.json.tftpl`
and `shared-spaces/policies/portal-role-shared-space.json.tftpl` — not in a bucket policy, and
**there is no shared-space bucket policy at all** (only user-space, archive, static assets and the
audit trail have one). So the check must run *as the portal role*: the laptop IAM user is not on the
user-space allowlist and would be refused by that allowlist instead, which is a different refusal
wearing the same name. On the shared-space bucket a laptop identity is not blocked by a bucket
policy — but it does not hold the Deny either, so it proves nothing.

**Never paste the token into a shell command** — it is a live credential and it lands in history.

```bash
umask 077 && cat > /tmp/idtoken     # paste the idToken from devtools → Local Storage, then Ctrl-D

IDENTITY_ID=$(aws cognito-identity get-id \
  --identity-pool-id "$IDENTITY_POOL_ID" \
  --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
  --query IdentityId --output text)

aws cognito-identity get-credentials-for-identity \
  --identity-id "$IDENTITY_ID" \
  --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
  --query Credentials
```

Export the three values in a shell you will close afterwards, then `rm -f /tmp/idtoken`.

**The marker check, and the control that makes it mean anything:**

```bash
# Expect AccessDenied on BOTH.
aws s3api delete-object --bucket dat-prod-user-space   --key "$USERNAME/saved_queries/DO_NOT_DELETE.txt"
aws s3api delete-object --bucket dat-prod-shared-space --key "$SPACE/saved_queries/DO_NOT_DELETE.txt"

# Expect BOTH to succeed — this is what proves the refusals above came from the marker Deny
# and not from the credentials being wrong.
aws s3api put-object    --bucket dat-prod-user-space --key "$USERNAME/saved_queries/marker_control.txt" --body /dev/null
aws s3api delete-object --bucket dat-prod-user-space --key "$USERNAME/saved_queries/marker_control.txt"
```

Afterwards, both markers are still present (they are hidden in the portal, so confirm with
`head-object`, not by eye).

### 2.2 Hand-crafted control-plane requests

The only way to stage a malformed request, or two executions that genuinely contend. Every plane
takes one FIFO queue — **but the token field is NOT the same on all six**, and the wrong one is
refused at the front door in a way that reads exactly like the check failing.

| Plane | Queue | Token field |
|---|---|---|
| Table builder | `dat-prod-table-builder-requests.fifo` | `idToken` |
| Data quality | `dat-prod-data-quality-requests.fifo` | `idToken` |
| Shared spaces | `dat-prod-shared-space-requests.fifo` | `idToken` |
| Table share | `dat-prod-table-share-requests.fifo` | `actor` (flat, raw) |
| File send | `dat-prod-file-send-requests.fifo` | `actor` (flat, raw) |
| Archive / restore | `dat-prod-archive-requests.fifo` | `actor` (flat, raw) |

On the three `actor` planes the value is the **raw** token at the top level — never
`{"idToken": …}`, which the front door refuses, and which SPEC-126's drain would write to
CloudWatch while notifying nobody. Verified against the six `validate-authorize` handlers.

```bash
QUEUE=$(aws sqs get-queue-url --queue-name dat-prod-table-builder-requests.fifo --query QueueUrl --output text)
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$USERNAME" --message-deduplication-id "$REQUEST_ID" \
  --message-body "$(jq -nc --arg t "$(cat /tmp/idtoken)" --arg u "$USERNAME" --arg r "$REQUEST_ID" \
      '{idToken:$t, mode:"refresh", requestId:$r, tableName:"partfix",
        space:{kind:"personal", bucket:"dat-prod-user-space", prefix:($u+"/partfix/"), database:$u}}')"
```

**Two things about that body are load-bearing, and both fail quietly.** The verb is **`mode`**, not
`action` — this plane has no unknown-field check, so an `action` key is silently ignored and
`_validate_mode(None)` returns **`"create"`**: a contention run built that way starts two *creates*
and never claims the refresh lock at all. And `space` needs all four of
`{kind, bucket, prefix, database}` — `{kind, name}` is refused as `forbidden` before the mode is
ever read, because `_authorize_space` compares `database` against the actor.

**Refresh-lock contention (SPEC-157).** The lock is claimed by the *execution*, so two messages are
two executions. Send both at once — same group is enough (the Pipe starts the second while the
first still holds the lock); different groups removes even that serialization.
**Pass:** one succeeds, the other ends `refresh_already_running`, the loser is **notified rather
than queued**, and `logs/service=table-builder/` shows one lock claim and one refusal. *(The
no-token alternative: point a table at a folder with several hundred objects so the first refresh's
listing takes tens of seconds, then two UI tabs really do overlap.)*

**A malformed body (SPEC-133/126).** Send a body that is not the envelope at all. Expect: the
message dead-letters, the drain sweeps it within 10 minutes, **the actor is notified from the
verified token and nothing from the untrusted body reaches the message**, the message is gone
(nothing redelivers), and the redacted body is in `logs/service=dlq-drain/`.

**Archive and restore.** Two UUIDs per run, and they must **differ** — the plane refuses a restore
whose `requestId` equals its `archiveId`. The group id is the digest of the **archive root alone**,
which is the contract the browser reproduces:

```bash
--message-group-id "$(printf 'personal/%s/archive/%s/' "$USERNAME" "$ARCHIVE_ID" | shasum -a 256 | cut -d' ' -f1)"
--message-body "$(jq -nc --arg r "$REQUEST_ID" --arg t "$(cat /tmp/idtoken)" --arg u "$USERNAME" --arg a "$ARCHIVE_ID" \
    '{requestId:$r, mode:"restore", actor:$t, space:{kind:"personal", name:$u}, archiveId:$a}')"
```

Worth staging by hand, because the UI cannot: an `archiveId` with a trailing space and one
containing `/` are refused as **malformed before any bucket is touched** (no listing in
`logs/service=archive/` for that request); the id in **UPPER CASE** resolves normally, because it is
lowercased. A nonexistent id and a real id in a space you are a member of both return the *same*
`archive_not_found` — the second must not hint that the archive exists elsewhere.

### 2.3 The data-quality state order, including the poll

The one recipe that proves the `WaitForQuery → CheckQuery → Choice` loop iterates. Drive a check
from the UI, take its execution ARN, then:

```bash
aws stepfunctions get-execution-history --execution-arn "$EXEC_ARN" \
  --query "events[?type=='TaskStateEntered' || type=='WaitStateEntered'].stateEnteredEventDetails.name" \
  --output text
```

Expect, in order: `ValidateAuthorize InspectSource CreateTempTables StartProfileQuery WaitForQuery
CheckQuery WaitForQuery CheckQuery ByteScan AssembleReport DropTempTables`. **`WaitForQuery` and
`CheckQuery` must each appear twice** — a single pass is a poll that never polled, and it reads as a
pass.

### 2.4 Reading the archive audit trail

`RestoreObject` is a **data** event, invisible in CloudTrail Event history — SPEC-186 FR-004 added a
dedicated trail. **Prove the trail is logging first.** A trail that is off returns an empty result,
which reads exactly like a `RestoreObject` that never happened:

```bash
aws cloudtrail get-trail-status --name dat-prod-archive-audit --query 'IsLogging'   # expect true
```

Data events arrive in batches — **wait ~10 minutes** before concluding anything.

```bash
aws s3 ls "s3://dat-prod-archive-audit/AWSLogs/" --recursive \
  | awk '{print $4}' | while read -r key; do
      aws s3 cp "s3://dat-prod-archive-audit/$key" - | gunzip
    done \
  | jq -r --arg id "$ARCHIVE_ID" '
      .Records[]
      | select(.eventName == "RestoreObject")
      | select(.requestParameters.key // "" | contains($id))
      | "\(.eventTime)  \(.requestParameters.key)"'
```

The archive key layout is `{personal|shared}/{space}/{archiveId}/…`, so the id is in every key a run
would touch.

- **After a refused restore: expect NO OUTPUT.** That is the assertion.
- **During a real retrieval: expect exactly the archive's object count** (`| sort -u | wc -l`).

### 2.5 EventBridge timeout doors, and share-at-scale reads

```bash
# The rule matches TIMED_OUT only — a FAILED in the pattern double-notifies every caught failure.
aws events describe-rule --name dat-prod-table-share-orchestrator-timed-out --query 'EventPattern' --output text
aws events list-targets-by-rule --rule dat-prod-table-share-orchestrator-timed-out --query 'Targets[].Arn'
```

Then drive the handler with a synthetic event on the default bus. **The escaping is the hard part
and is not reconstructible by eye** — the SQS-shaped `input` is a string inside a string inside a
string. Substitute the ARNs and a real (expired is fine) token:

```bash
aws events put-events --entries '[{
  "Source": "aws.states",
  "DetailType": "Step Functions Execution Status Change",
  "Detail": "{\"executionArn\":\"arn:aws:states:us-east-1:ACCT:execution:M:probe\",\"stateMachineArn\":\"<state-machine-arn>\",\"status\":\"TIMED_OUT\",\"inputDetails\":{\"included\":true},\"input\":\"[{\\\"body\\\":\\\"{\\\\\\\"actor\\\\\\\":\\\\\\\"<AN ID TOKEN>\\\\\\\",\\\\\\\"source\\\\\\\":{\\\\\\\"database\\\\\\\":\\\\\\\"<you>\\\\\\\",\\\\\\\"table\\\\\\\":\\\\\\\"sales\\\\\\\"},\\\\\\\"tableName\\\\\\\":\\\\\\\"probe\\\\\\\"}\\\"}]\"}"
}]'
```
 Expect the
notification in **your own** inbox; repeat with a `username` in the body naming someone else and
confirm it **still** arrives in yours — the actor comes from the token. Send it once with a wrong
`stateMachineArn` and expect **no** notification, which is what proves the rule matched.

The scale reads:

```bash
# The fixture really is over the old caps.
aws s3 ls --recursive --summarize "s3://dat-prod-user-space/$USERNAME/<source-prefix>/" | tail -3

# One event per run carries the recipient and item counts.
aws s3 cp "s3://dat-prod-athena-admin/logs/service=table-share/year=<Y>/month=<M>/day=<D>/data.jsonl" - \
  | grep 'transfer manifest built'

# The 100-column clone survived the pointer, comments and all.
aws glue get-table --database-name "<recipient-db>" --name "<result-name>" \
  --query 'Table.{cols: length(StorageDescriptor.Columns), props: Parameters}'
aws glue get-table --database-name "<recipient-db>" --name "<result-name>" \
  --query 'length(StorageDescriptor.Columns[?Comment!=`null`])'      # expect 100
```

### 2.6 The verification role

**Do not apply it locally.** No human identity here can `tofu apply` from a laptop: the IAM user is
not on the data buckets' policy allowlists, so tofu reads them as **absent** and plans to destroy
and recreate them (measured: `25 to add, 3 to change, 13 to destroy`, both data buckets in the
replace set). The value is a **repo variable** applied by CI:

```bash
gh variable set TF_VAR_verification_principal_arns --body '["arn:aws:iam::<account>:user/<you>"]'
```

Then run **Deploy Infrastructure**. Expect a red first apply — IAM is eventually consistent — and
re-run. Once green:

```bash
aws sts assume-role --role-arn "arn:aws:iam::<account>:role/dat-prod-verification" --role-session-name livecheck
```

The role is audit-shaped, not a data grant: no `SELECT`, no `DATA_LOCATION_ACCESS`, no
`lakeformation:GetDataAccess`, no `Resource: "*"`, no `iam:PassRole`. It exists only once
`verification_principal_arns` names a principal, because delegating to the account root was
rejected by the plan scan (`CKV_AWS_61`) for the right reason.

### 2.7 The `username` principal tag, from the audit record

The tag is stamped **server-side** from the verified claim, which is the whole isolation model —
and it is unobservable from the app. Sign in on a **fresh** session (credentials are issued at token
exchange, so a cached one never fires the event), then read the record.

**Look for `AssumeRoleWithWebIdentity` from `sts.amazonaws.com`** — not the `CognitoAuthentication`
event, which is the Hosted UI login on `cognito-idp` and **never carries the principal tag**. Mixing
them up reads as a missing tag on a correct system. CloudTrail lags a few minutes.

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 5 --query 'Events[].CloudTrailEvent' --output text \
  | grep -o '"principalTags":{[^}]*}'
```

Expect `"username":"<the signed-in username>"`. In the browser, `GetId` and
`GetCredentialsForIdentity` both return **200** on the `cognito-identity` host — that is the
User-Pool-token → AWS-credentials exchange, and without it there is no STS event to find.

### 2.8 IAM policy simulation

The pattern, whenever a grant is tightened or widened. **Every denial needs an `allowed` control on
the same bucket** — an `implicitDeny` alone cannot tell an ungranted action from a wrong resource
ARN, which is how a mistyped bucket name once read as a pass.

```bash
ROLE=arn:aws:iam::<account>:role/dat-prod-<plane>-execution-role
run() { printf '%-24s %-64s ' "$1" "$2"; aws iam simulate-principal-policy \
  --policy-source-arn "$ROLE" --action-names "$1" --resource-arns "$2" \
  --query 'EvaluationResults[0].EvalDecision' --output text; }
```

**Three ways this returns a confident wrong answer.**

- **Everything comes back `explicitDeny`.** The user-space bucket policy denies on
  `StringNotLike aws:PrincipalArn`, and a **missing** context key makes that condition **true** — so
  a simulator that never populated the principal ARN denies everything, uniformly and plausibly. Add
  `--context-entries ContextKeyName=aws:PrincipalArn,ContextKeyValues=$ROLE,ContextKeyType=string`.
- **`simulate-principal-policy` does not consult a bucket policy on its own.** Pass
  `--resource-policy`, or the run is silently only testing the identity half. Add
  `--resource-owner <account-id>` if the call errors on the resource policy (same-account should not
  need it).
- **`simulate-custom-policy` caps each `--policy-input-list` member at 2,000 characters, and the
  `file://` form is rejected as "invalid content".** Pass it inline
  (`--policy-input-list "$(cat policy.json)"`) over a minimal extract that reuses the same condition
  pattern.

Run it **after** the apply, against the deployed role. A row that moves `implicitDeny` →
**`explicitDeny`** across a widening is the strongest evidence there is: once the widening grants
the action broadly, the only thing still refusing it is the Deny you are testing, and a mis-scoped
one would read `allowed`.

---

## 3. Discharged, and worth not re-litigating

Kept short on purpose — the reasoning lives in `docs/decisions.md` and the delivery docs. These are
here so a reader does not re-open them as gaps.

| Settled | When |
|---|---|
| The `sqlLiteral` path (`O''Brien`) against the real engine; the disclosed SQL is byte-identical to Athena's `QueryString`; a filter apply is a new execution while a cache hit issues zero | 2026-08-15 |
| Data Explorer paging (0 executions), copy/export (the export held 150 rows to the page's 100), the `.sql` round trip in both directions | 2026-08-16 |
| The refresh arc's add / refuse-naming-the-column / link / opt-in sequence, flat **and** partitioned, and the casing control | 2026-08-14, 2026-08-16 |
| `saved_queries/` client-side refusal, personal and shared, byte-exact with no confirm reachable | 2026-08-15, 2026-08-16 |
| `env` and a real build sha on 809 post-deploy log records across four services | 2026-08-15 |
| The archive execution role's 13-row policy simulation, four rows moving to `explicitDeny` | 2026-08-12 |
| The username directory read; the cross-bucket saved-query `PutObject`; the disagreeing-files data-quality finding | 2026-08-14 |
