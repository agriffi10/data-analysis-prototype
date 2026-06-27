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

## Notes

- **No provisioning happens yet.** SPEC-050: a SUCCEEDED execution + echo is the pass
  condition. SPEC-056: a SUCCEEDED execution returns `{status:"authorized",...}`. If an
  execution FAILS with the placeholder error, the Lambda **code** hasn't been deployed —
  run `deploy-lambdas.yml`.
- **DLQ:** a message that fails delivery 3× lands on `${PROJECT}-${ENV}-shared-space-requests-dlq.fifo`. During these tests, none should.
