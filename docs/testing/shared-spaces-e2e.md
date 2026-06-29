# Shared-Space Control-Plane Smoke Test (SPEC-050)

**Purpose:** Prove the shared-space **control plane** is wired end-to-end against
deployed infrastructure: a message placed on the request queue flows
`SQS → EventBridge Pipe → Step Function → provisioner Lambda` and is observable in
CloudWatch. SPEC-050 is **foundation only** — the Lambda dispatches/echoes and
provisions **nothing**; this test confirms plumbing, not behavior. Per-action
provisioning (create/add/remove/leave/delete) arrives in SPEC-051→055 and gets its
own acceptance steps then.

**Scope covered:** FR-001 (shared bucket hygiene/CORS), FR-002 (registry prefix is
lifecycle-exempt), FR-003 (control plane + orchestrator role), FR-005 (this test).

> **Status:** ✅ Executed 2026-06-26 against the deployed environment — a message on
> the FIFO queue drove the Pipe → Step Function (`SUCCEEDED`) → provisioner Lambda
> (echoed `{"status":"dispatched","count":1,"actions":["smoke-test"]}`); FR-001
> hygiene + FR-002 lifecycle-prefix confirmed live. Bring-up needed a one-time
> break-glass for the SFN plan-time validate/list actions (now permanent in the
> deploy managed policy); see step 0. Re-run the steps as the regression checklist.

---

## Prerequisites

- [ ] `deploy-infra.yml` has applied SPEC-050 (merge to `main`, or `tofu apply` in `infra/`).
- [ ] `deploy-lambdas.yml` has deployed the `shared-space-provisioner` code (push touching `lambdas/**`, or run the workflow manually) — until then the placeholder raises on invoke.
- [ ] AWS CLI configured against the same account/region.

Capture environment values (from `infra/`):

```bash
QUEUE_URL=$(tofu output -raw shared_space_request_queue_url)   # see infra/outputs.tf wiring (SPEC-050)
REGION=us-east-1
PROJECT=dat ; ENV=prod
SM_ARN="arn:aws:states:${REGION}:$(aws sts get-caller-identity --query Account --output text):stateMachine:${PROJECT}-${ENV}-shared-space-orchestrator"
FN="${PROJECT}-${ENV}-shared-space-provisioner"
```

---

## Step 0 — First-apply self-grant propagation (expected one-time failure)

SPEC-050 adds SQS/Pipes/Step-Functions/Lambda/IAM/logs grants to the deploy role in
the **same** apply that then creates those resources (`modules/base` → `module.shared_spaces`).
The deploy role's `time_sleep` guards absorb most of the eventual-consistency window,
but per architecture.md the very first apply that introduces a new resource type can
still race the grant and fail with `AccessDenied`.

- [ ] If the first `deploy-infra.yml` run fails with AccessDenied on an SQS/Pipes/States/Lambda call, **re-run it**. `module.base` attaches the policy first, so the grant has propagated by the re-run. A second consecutive failure is a real problem — investigate, don't loop.

## Step 1 — Shared bucket hygiene + CORS (FR-001)

```bash
B="${PROJECT}-prod-shared-space"
aws s3api get-public-access-block --bucket "$B"          # all four = true
aws s3api get-bucket-encryption --bucket "$B"            # AES256
aws s3api get-bucket-cors --bucket "$B"                  # GET/PUT/POST/DELETE/HEAD; localhost + app origin
aws s3api get-bucket-lifecycle-configuration --bucket "$B"  # abort-incomplete-multipart, 7 days
```

- [ ] All four public-access settings are `true`; SSE = AES256; CORS lists the app origin; the abort-incomplete-multipart rule is present.

## Step 2 — Registry prefix is lifecycle-exempt (FR-002)

The registry lives under `shared-spaces/` in the **admin** bucket; the
`expire-admin-results` rule is scoped to the `fallback-results/` prefix only, so
registry objects must never expire.

```bash
A="${PROJECT}-prod-athena-admin"
aws s3api get-bucket-lifecycle-configuration --bucket "$A"   # rule filter.Prefix == "fallback-results/"
```

- [ ] The `expire-admin-results` rule's `Filter.Prefix` is `fallback-results/` (not empty/whole-bucket). A test object written under `shared-spaces/` is therefore outside the rule and retained.

## Step 3 — Drive the control plane (FR-003)

Send a FIFO message with a constant `MessageGroupId` (the serial-intake convention).
The body is a placeholder — there is no request contract until SPEC-056.

```bash
aws sqs send-message \
  --queue-url "$QUEUE_URL" \
  --message-group-id shared-space \
  --message-body '{"action":"smoke-test","note":"SPEC-050 plumbing check"}'
```

- [ ] Within ~1 minute, a **new Step Function execution** appears and **Succeeds**:

```bash
aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1
# status SUCCEEDED; describe-execution output shows the Lambda echo:
#   {"status":"dispatched","count":1,"actions":["smoke-test"]}
```

- [ ] The provisioner Lambda logged the invocation:

```bash
aws logs tail "/aws/lambda/${FN}" --since 5m   # "shared-space-provisioner skeleton invoked: 1 record(s) ..."
```

## Step 4 — Serial intake (FIFO)

- [ ] Send two messages quickly with the **same** `--message-group-id shared-space`; confirm the executions run/complete in order (FIFO single-group serializes intake). Duplicate-name *correctness* is not exercised here — that is the registry conditional-`PutObject` guard added in SPEC-051.

## Step 5 — Orchestrator role scopability (FR-003)

Local `aws iam simulate-custom-policy` (no AWS creds in the dev sandbox — run in CI or
with an admin profile) confirms each orchestrator action is `allowed` on its intended
ARN and the resource-scoped ones `implicitDeny` on a foreign ARN. Spot-check the
scopable deploy-time actions too (e.g. `states:CreateStateMachine`, `pipes:CreatePipe`,
`sqs:CreateQueue`) against the `*-shared-space-*` patterns.

- [ ] `simulate-custom-policy` shows the orchestrator role allowed on its Glue/LF/S3/Cognito ARNs and the deploy role allowed on the `*-shared-space-*` resource patterns.

---

## SPEC-056 — access model + validate (membership tags, portal slots, actor binding)

### Membership-slot allow/deny (FR-002) — ✅ verified 2026-06-26 via `simulate-custom-policy`

The portal-role membership slots are templated on `${aws:PrincipalTag/shared_space_k}`.
Verified locally against the rendered policy (results: set→`allowed`, other-space→
`implicitDeny`, unset slot→`implicitDeny`, **empty slot value→`implicitDeny` — no
bucket-root leak**, `athenaresults/` delete→`explicitDeny`).

> **Gotcha:** `aws iam simulate-custom-policy` caps each `--policy-input-list` member at
> **2000 chars** and the `file://` form is rejected as "invalid content" — pass the policy
> **inline** (`--policy-input-list "$(cat policy.json)"`) and test a minimal extract that
> reuses the same `${aws:PrincipalTag/shared_space_k}/*` pattern.

```bash
P='{"Version":"2012-10-17","Statement":[{"Sid":"O","Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::dat-prod-shared-space/${aws:PrincipalTag/shared_space_1}/*"]}]}'
B=arn:aws:s3:::dat-prod-shared-space
# set slot1=salesdata, GET salesdata/*  -> allowed
aws iam simulate-custom-policy --policy-input-list "$P" --action-names s3:GetObject \
  --resource-arns "$B/salesdata/d.csv" \
  --context-entries 'ContextKeyName=aws:PrincipalTag/shared_space_1,ContextKeyType=string,ContextKeyValues=salesdata' \
  --query 'EvaluationResults[0].EvalDecision' --output text
# empty slot value, GET bucket-root object -> implicitDeny (no leak)
aws iam simulate-custom-policy --policy-input-list "$P" --action-names s3:GetObject \
  --resource-arns "$B/anything.csv" \
  --context-entries 'ContextKeyName=aws:PrincipalTag/shared_space_1,ContextKeyType=string,ContextKeyValues=' \
  --query 'EvaluationResults[0].EvalDecision' --output text
```

- [x] Set slot allows that space's S3/Glue; unset/empty/other-space deny with no root leak.
- [ ] The portal role can `sqs:SendMessage` to the request queue only (review the rendered policy / simulate `sqs:SendMessage`).

### Trusted-actor binding + validate (FR-005)

The provisioner Lambda verifies the caller's Cognito **ID token** (JWKS) → trusted
`actor`, then authorizes against the registry; forged/unauthorized → `AuthorizationError`
→ Step Function **Fail**, no side effects. The verbs are still stubs.

- [x] **Unit-tested** (`lambdas/shared-space-provisioner/test_shared_space_provisioner.py`,
  13 cases): the pure `authorize()` rules (owner-only, leave, create-any, unknown action)
  and the handler flow (token actor overrides body `actor`; a **forged token is rejected
  before the registry/verb runs**; non-owner owner-action rejected; bad schemaVersion/body
  rejected).
- [ ] **Live authorized-vs-forged** (deferred until SPEC-051+ produces real tokens, or mint
  one manually): send a message with a valid ID token + `action:create` → SFN `SUCCEEDED`
  (`{status:authorized,...}`); send one with a garbage `idToken` → SFN `FAILED` with
  `AuthorizationError` in the execution history, registry untouched.

---

## SPEC-051 — create a shared connection (end to end)

The browser enqueues a `create` request; the provisioner verb provisions the space.

- [x] **App unit/component tests** (`apps/portal/src/features/shared-spaces/`,
  `routes/ConnectionsPage.test.tsx`): dialog validation; one well-formed `create`
  message carrying the `idToken`; no-send on missing queue/token; create → optimistic
  pending + success toast; failure → error toast, no pending.
- [x] **Lambda unit tests** (`lambdas/shared-space-provisioner/`): happy path
  (registry+marker+Glue DB+LF grant+slot+cache, all written); name collision →
  "name already taken"; replay (same requestId) → idempotent, no double-provision;
  slot-full → "membership limit reached" recorded as `failed` in registry+cache;
  replay-safe slot reuse; forged token rejected before any verb.
- [ ] **Live** (deployed): in the app, Connections → New shared connection → a valid
  name → success toast + provisioning entry. Then verify the pipeline:

```bash
NAME=teamspace1 ; ACCT=696000197480
aws s3api get-object --bucket dat-prod-athena-admin --key "shared-spaces/$NAME.json" /dev/stdout   # status: active, owner
aws glue get-database --name "$NAME"                                                                # exists
aws s3api head-object --bucket dat-prod-shared-space --key "$NAME/DO_NOT_DELETE.txt"                # marker
aws s3api get-object --bucket dat-prod-user-space --key "{username}/user_settings/shared-connections.json" /dev/stdout
aws cognito-idp admin-get-user --user-pool-id <pool> --username <creator> \
  --query "UserAttributes[?starts_with(Name,'custom:shared_space')]"                                # a slot == NAME
```

- [ ] **Duplicate name** → the second `create` Step Function execution FAILS
  ("name already taken"); the first space is untouched.
- [ ] After a **token refresh** (forced by SPEC-052's Refresh), the creator can query
  `database/{name}` and read/write `dat-prod-shared-space/{name}/*` (membership slot
  now stamped).

---

## SPEC-053 — owner member management (add / remove)

The owner opens the **Manage** drawer on the Connections tab and adds/removes members
by username. The browser enqueues `add_members` / `remove_members`; the provisioner
authorizes the caller as the owner, validates each username against the User Pool
(unknowns silently dropped), assigns/clears each member's slot, and updates the
registry + each member's cache + the **owner's member projection**.

- [x] **App unit/component tests** (`apps/portal/src/features/shared-spaces/`):
  `parseMemberInput` (split/dedupe/lowercase/drop-malformed); `AddMembersDialog`
  (sends parsed list, excludes existing, disabled-until-valid); `ManageMembersDrawer`
  (owner marked + non-removable, remove→confirm→callback, add→callback, unavailable
  note); `useManageMembers` (one well-formed `add_members`/`remove_members`); Manage
  action owner-only + opens the drawer + add enqueues one request.
- [x] **Lambda unit tests** (`lambdas/shared-space-provisioner/`): add assigns
  slot+registry+member-cache+owner-projection; unknown user silently ignored; at-limit
  target skipped (others still added); idempotent for an existing member; owner never
  added; remove clears slot + registry + member cache + owner projection and leaves the
  Glue DB/marker intact; idempotent for a non-member; owner never removed; handler runs
  the verb for the owner and **fails with no effect for a non-owner**.
- [ ] **Live** (deployed): as the owner, Manage → Add `bob` (a real user) → after **bob's**
  next token refresh (SPEC-052 Refresh) he can query `database/{name}`. Verify:

```bash
NAME=teamspace1 ; OWNER=alice ; MEMBER=bob ; POOL=<pool>
aws s3api get-object --bucket dat-prod-athena-admin --key "shared-spaces/$NAME.json" /dev/stdout   # members includes bob
aws cognito-idp admin-get-user --user-pool-id $POOL --username $MEMBER \
  --query "UserAttributes[?starts_with(Name,'custom:shared_space')]"                                # a slot == NAME
aws s3api get-object --bucket dat-prod-user-space --key "$MEMBER/user_settings/shared-connections.json" /dev/stdout  # role:member, active
aws s3api get-object --bucket dat-prod-user-space --key "$OWNER/user_settings/shared-connections.json" /dev/stdout   # owner entry members:[alice,bob]
```

- [ ] **Remove** `bob` → his slot is cleared (empty), the registry + his cache drop the
  entry, the owner projection updates; the shared Glue DB + objects are untouched.
- [ ] **Unknown user** (`add_members` with a non-existent username) → silently ignored
  (no slot, no cache, not in members); the execution still SUCCEEDS.
- [ ] **Non-owner** `add_members`/`remove_members` (crafted request) → Step Function
  FAILS ("owner-only") with no side effects.

---

## SPEC-054 — leave (member) & delete (owner cascade)

Two terminal lifecycle actions. A **member** clicks **Leave** (simple confirm) → enqueue
`leave`: the provisioner clears only the caller's slot + cache entry and drops them from
the registry — shared objects/tables/DB and every other member are untouched. An
**owner** clicks **Delete** (irreversible, **type-the-name** confirm) → enqueue `delete`:
the provisioner cascades — recursive S3 delete of `dat-prod-shared-space/{name}/`, revoke
the LF grant, drop all tables + the Glue DB, clear **every** member's slot + cache entry,
then delete the registry object **last** (name freed). Both are async (pending →
gone-on-Refresh, SPEC-052) and idempotent. `authorize` (SPEC-056) blocks an owner `leave`
and a non-owner `delete`.

- [x] **App unit/component tests** (`apps/portal/src/features/shared-spaces/`):
  `LeaveSharedSpaceDialog` (danger confirm, busy-locks); `DeleteSharedSpaceDialog`
  (type-the-name gates Delete, Enter-to-confirm only on match, irreversible line);
  `ConfirmDialog` `confirmDisabled` (confirm disabled, Cancel live); Connections screen —
  **Leave** shown only to members (confirm → one `leave`), **Delete** only to owners
  (type-the-name → one `delete`), neither on a non-active row, optimistic
  `leaving`/`deleting` overlay, no direct AWS mutation.
- [x] **Lambda unit tests** (`lambdas/shared-space-provisioner/`): leave clears
  slot+cache+registry+owner-projection and leaves data/DB/other-members intact, no-op
  success for a non-member, defensive owner guard; delete cascades
  files+LF-revoke+tables+DB+all-members+registry and **frees the name**, idempotent /
  tolerant of partial prior progress, records `failed`+reason without deleting the
  registry on a hard error; handler runs leave for a member + delete for the owner, and
  **owner-leave + non-owner-delete both fail with no effect**.
- [ ] **Live** (deployed) — **leave**: as `bob` (a member of `$NAME`), Connections →
  Leave → confirm. After **bob's** next token refresh:

```bash
NAME=teamspace1 ; OWNER=alice ; MEMBER=bob ; POOL=<pool>
aws s3api get-object --bucket dat-prod-athena-admin --key "shared-spaces/$NAME.json" /dev/stdout   # members no longer has bob
aws cognito-idp admin-get-user --user-pool-id $POOL --username $MEMBER \
  --query "UserAttributes[?starts_with(Name,'custom:shared_space')]"                                # the NAME slot is cleared
aws s3api get-object --bucket dat-prod-user-space --key "$MEMBER/user_settings/shared-connections.json" /dev/stdout  # entry gone
aws s3api ls "s3://dat-prod-shared-space/$NAME/"                                                    # objects still present (not deleted)
```

- [ ] **Delete** (owner): as `alice`, Connections → Delete → type `$NAME` → confirm. After it runs:

```bash
aws s3api get-object --bucket dat-prod-athena-admin --key "shared-spaces/$NAME.json" /dev/stdout   # NoSuchKey — registry gone, name free
aws s3api ls "s3://dat-prod-shared-space/$NAME/"                                                    # empty — all objects deleted
aws glue get-database --name "$NAME"                                                                # EntityNotFoundException
# every member's NAME slot cleared + cache entry dropped (check each as above)
```

- [ ] **Owner leave** (crafted `leave` from the owner) and **non-owner delete** (crafted
  `delete` from a member) → Step Function FAILS ("owner cannot leave" / "owner-only")
  with no side effects.
- [ ] **Reuse**: after a successful delete, a fresh `create` of the same `$NAME` succeeds
  (uniqueness check passes).

---

## SPEC-055 — shared-DB query results routing & save

With a shared connection selected as the workspace's active database (SPEC-047/052), query
results route to the shared space so collaborators can see them, and Save-results can read a
shared result and write into the user's own space or a shared space (cross-bucket). Frontend
only — relies on the SPEC-050/056 membership-slot grants (no new IAM). Requires the
`VITE_S3_SHARED_SPACE_BUCKET` GH repo variable (set to `dat-prod-shared-space`).

- [x] **App unit/component tests:** `resultOutputLocation` (personal vs shared path); `runQuery`
  honors an explicit `outputLocation`; `copyObject` cross-bucket (CopySource from source, write +
  collision-HEAD on dest); `SaveResultsDialog` space selector; `QueryWorkspace` routes a shared
  query to `…/{name}/athenaresults/{username}/`, lists personal + shared Save destinations, does
  same- and cross-bucket saves (shared dest omits the Files link), copy error writes nothing.
- [ ] **Live** (deployed): as a member of `$NAME`, select it as the active DB and run
  `SELECT 1`. Verify the result object appears under the shared prefix:

```bash
NAME=teamspace1 ; ME=bob
aws s3 ls "s3://dat-prod-shared-space/$NAME/athenaresults/$ME/"     # the result .csv (+ .metadata) is here
aws s3 ls "s3://dat-prod-user-space/$ME/athenaresults/" | tail      # NOT here (personal prefix unchanged)
```

- [ ] **Read**: the results table renders the rows (Athena GetQueryResults is location-agnostic).
- [ ] **Save → my space**: Save results → "My files" → a folder → the CSV lands in
  `dat-prod-user-space/$ME/...`; the "View in Files" link opens it.
- [ ] **Save → shared space** (cross-bucket): Save results → choose `$NAME` → a folder → the CSV
  lands in `dat-prod-shared-space/$NAME/...` (success toast, **no** Files link until SPEC-057).
- [ ] **Collision**: saving the same name twice prompts Overwrite at the chosen destination.
- [ ] **Personal unchanged**: a personal-DB query still writes to `$ME/athenaresults/` and Save
  behaves exactly as SPEC-049.

---

## SPEC-062 — decomposition parity (validate → Choice → verb Lambdas)

The monolith is replaced by six Lambdas + a shared layer, behind the same SQS front. **Re-run the
SPEC-051/053/054 sections above** — every end state (S3 prefix/marker, Glue DB+tables, registry object,
membership slots, per-user caches) must be identical. Plus the structural checks:

- [ ] **Functions exist + carry the layer:** `aws lambda get-function --function-name
  dat-prod-shared-space-create` (and `-validate/-add-members/-remove-members/-leave/-delete`) returns the
  function with a `Layers` entry for `dat-prod-shared-space-common`. The old
  `dat-prod-shared-space-provisioner` is **gone**.
- [ ] **Routing:** a `create` execution shows the path `Validate → Route → CreateSpace → Succeeded` in
  the Step Function execution history; `add_members`/`leave`/`delete` route to their own branch. An
  unknown action lands on `Failed`.
- [ ] **Auth still server-side:** a forged/expired `idToken` fails in `Validate` (Catch → `Failed`) with
  **no** side effects (no registry/slot/cache write); a non-owner `delete`/`add_members` fails in
  `Validate` (`owner-only`).
- [ ] **No notifications yet:** verbs do **not** emit (the `notify` seam is a no-op until SPEC-061 wires
  `NOTIFICATIONS_QUEUE_URL` + the `sqs:SendMessage` grant).

---

## Notes

- **No provisioning happens yet.** SPEC-050: a SUCCEEDED execution + echo is the pass
  condition. SPEC-056: a SUCCEEDED execution returns `{status:"authorized",...}`. If an
  execution FAILS with the placeholder error, the Lambda **code** hasn't been deployed —
  run `deploy-lambdas.yml`.
- **DLQ:** a message that fails delivery 3× lands on `${PROJECT}-${ENV}-shared-space-requests-dlq.fifo`. During these tests, none should.
