# Auth End-to-End Acceptance Script (SPEC-006 → SPEC-009)

**Purpose:** Prove the whole authentication stack works against deployed
infrastructure, from account creation to gated access. This is the regression
checklist for any future auth change.

**Scope covered:** Cognito User Pool + Hosted UI (SPEC-006), login flow
(SPEC-007), auth-gated layout (SPEC-008), end-to-end signup (SPEC-009).

> **Status:** ✅ Executed 2026-06-11 against the deployed CloudFront environment.
> The core flow — signup → email verification → first login → `/files` → refresh
> persistence → gated access with return-path — passed. A few optional
> failure-path smoke checks (steps 10, 14, 15, 16) and test-user cleanup were not
> run; see the [Execution Log](#execution-log). This script is the acceptance
> gate for the SPEC-006 → SPEC-009 arc (SPEC-009 FR-005) and the regression
> checklist for future auth changes — re-run the unticked steps as needed.

---

## Prerequisites

- [ ] The infra is applied, **including the SPEC-009 `verification_message_template`** (run `tofu apply` in `infra/`, or merge to `main` so `deploy-infra.yml` applies it).
- [ ] The app is deployed to CloudFront via `deploy-app.yml` with the four Cognito build vars set (`VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_APP_URL` = the CloudFront URL).
- [ ] A **real email inbox** you control for the test account (default Cognito sender allows ~50 emails/day — sufficient).
- [ ] AWS CLI configured against the same account/region for the cleanup step.

Capture the environment values (from `tofu output` in `infra/`):

```bash
APP_URL=$(tofu output -raw cloudfront_domain)             # https://xxxx.cloudfront.net
POOL_ID=$(tofu output -raw cognito_user_pool_id)          # us-east-1_XXXXXXXXX
HOSTED_UI=$(tofu output -raw cognito_domain)              # xxxx.auth.us-east-1.amazoncognito.com
```

Pick a test username that satisfies the SPEC-012 rule, tightened by SPEC-033 FR-001
to a catalog-safe identifier (`^[a-z][a-z0-9_]{2,62}$`), e.g. `e2e_tester`. The
username becomes the user's S3 prefix, audit identity, and Glue database name.

---

## Test Steps

### 1. Fresh signup

1. Open `$APP_URL` in a clean browser profile (or incognito). **Expected:** the landing page renders with **"Sign in"** and **"Create account"**, plus the username guidance line (*3–63 chars, starts with a letter, lowercase letters/numbers/underscores only*). No console errors.
   - [x] Pass
2. Click **"Create account"**. **Expected:** full-page redirect to the Hosted UI **sign-up** screen (`$HOSTED_UI/signup?...`) for the correct pool/client.
   - [x] Pass
3. Enter the test username, the test email, and a password that satisfies the SPEC-006 policy (≥12 chars, upper/lower/number/symbol). Submit. **Expected:** the Hosted UI advances to a "enter verification code" prompt.
   - [x] Pass
4. **Password policy negative check:** before step 3 succeeds, try a weak password (e.g. `password`). **Expected:** Hosted UI rejects it inline.
   - [x] Pass

### 2. Receive and enter the code

5. Check the test inbox. **Expected:** an email arrives with subject **"Your S3 Portal verification code"** containing a 6-digit code (FR-002).
   - [x] Pass
6. Enter the code on the Hosted UI. **Expected:** verification succeeds.
   - [x] Pass

> **Resolved (FR-003, 2026-06-11):** the Hosted UI does **not** auto-sign-in after
> code confirmation — the user must complete **one explicit login** before
> reaching `/files`. Step 7 below ("Complete sign-in if prompted") reflects this.

### 3. First login lands on /files

7. Complete sign-in if prompted. **Expected:** redirect back to the app and arrive **authenticated on `/files`**, with the **test username shown in the header** (matching exactly what was typed at signup).
   - [x] Pass
8. **Refresh** the `/files` page. **Expected:** stays signed in on `/files` after a brief loading indicator — no flash of the landing page, session persists (SPEC-007 FR-002).
   - [x] Pass

### 4. Logout → re-login

9. Click **"Sign out"** in the header. **Expected:** redirect to `/` (plain landing page, no confirmation message).
   - [x] Pass
10. Click **"Sign in"**, complete the Hosted UI login with the same credentials. **Expected:** back on `/files`, authenticated, username in header.
    - [ ] Pass

### 5. Gated access while signed out

11. Sign out again. In the address bar, navigate **directly to `$APP_URL/files`**. **Expected:** redirected to `/`; open DevTools → Network and confirm **no S3 request fires** while signed out (SPEC-008 FR-003).
    - [x] Pass
12. Now click **"Sign in"** and complete login. **Expected:** you land back on **`/files`** (the originally requested route was preserved across the OAuth round-trip — SPEC-008 FR-004).
    - [x] Pass

### 6. Failure-path smoke checks (SPEC-009 FR-004)

13. Start **"Create account"** again, then hit the browser **Back** button mid-signup to return to the app. **Expected:** app is `unauthenticated` on the landing page, no console errors.
    - [x] Pass
14. On the Hosted UI verification step, enter a **wrong code**. **Expected:** Hosted UI shows an error and offers retry; **"Resend code"** delivers a new email.
    - [ ] Pass
15. Attempt **"Create account"** with the **already-used username (or email)**. **Expected:** Hosted UI shows a "user already exists" error; returning to the app afterward works normally.
    - [ ] Pass
16. **Forgot-password smoke test:** from the Hosted UI login screen, use "Forgot your password?", receive the reset code by email, set a new password, and sign in with it. **Expected:** reset completes and login succeeds.
    - [ ] Pass

---

## Verifying Scoped Credentials & the `username` Principal Tag (SPEC-011)

> **Verified 2026-06-12:** `AssumeRoleWithWebIdentity` showed `principalTags.username
> == "agriffith"` with the mapping value `cognito:username` (the FR-002 claim key).
> Credentials issued; role `dat-portal-user-role` assumed. S3 still denied (no
> policy until SPEC-013) — as expected.

Run this **before Cleanup** (the test user must still exist), after #17 is deployed
and you've signed in with a **fresh** session. It proves the Identity Pool issues
scoped AWS credentials and stamps the `username` principal tag server-side.

**Prerequisites**
- [ ] #17 deployed; the build has `VITE_COGNITO_IDENTITY_POOL_ID` set (see GitHub Actions variables).
- [ ] Signed in on the new build. If you had a cached pre-identity-pool session, sign out and back in — credentials are issued at token exchange, and a stale session won't have them.

**1. Credentials are issued (browser)**

DevTools → Network, filter `cognito-identity`. After sign-in you should see
`GetId` and `GetCredentialsForIdentity` return **200** — that is the User-Pool-token
→ AWS-credentials exchange. (The Identity Pool's *Identities* list in the console
also shows a new identity after the user's first sign-in.)
   - [ ] Pass

**2. The `username` principal tag (CloudTrail — authoritative, FR-002)**

> The credential exchange (and therefore the taggable event) only fires once the
> app calls `fetchAuthSession()`. If sign-in produces no STS event, confirm the
> app actually requested credentials (step 1's `GetCredentialsForIdentity`).
>
> Look for the **`AssumeRoleWithWebIdentity`** event from **`eventSource:
> sts.amazonaws.com`** — *not* the `CognitoAuthentication` event (that one is just
> the Hosted UI login on `cognito-idp`; it never carries the principal tag).

CloudTrail can lag a few minutes after sign-in. Then:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 5 \
  --query 'Events[].CloudTrailEvent' --output text \
  | grep -o '"principalTags":{[^}]*}'
```

Expect a `principalTags` map containing `"username":"<your-cognito-username>"`.
   - [ ] `principalTags.username` == the signed-in username

> **If `principalTags` is absent or has no `username`:** the claim key is wrong.
> In `infra/modules/auth/identity-pool.tf`, change
> `principal_tags = { username = "username" }` → `{ username = "cognito:username" }`,
> re-apply, sign in again, and re-check. (This is the open FR-002 item.)

**3. S3 is still denied — expected**

The portal role has **no permissions** until SPEC-013, so any S3 call made with
these credentials returns `AccessDenied`. That is correct at this stage; scoped
per-prefix access turns on in SPEC-013. The SPEC-011 checkpoint is "credentials
issued + `username` tag in CloudTrail," not "S3 works."

---

## Verifying Prefix Isolation (SPEC-013 FR-004)

Proves the core security property: a signed-in user reads/writes only their own
`{username}/` prefix in the user-space bucket and is denied everyone else's. The
role + bucket policies (SPEC-013 Phase 1) are already applied; this is the live
end-to-end check with two real users.

> **Pre-apply policy evidence (already captured):** `aws iam
> simulate-principal-policy` against `dat-portal-user-role` shows own-prefix
> Get/Put/Delete **allowed**, cross-prefix **implicitDeny**, root listing
> **denied**, and `*/DO_NOT_DELETE.txt` delete **explicitDeny**. The steps below
> confirm it with real Cognito sessions.

### Setup

1. Sign up two users via the Hosted UI (or reuse existing): **alice** and **bob**
   (any names matching `^[a-z][a-z0-9_]{2,62}$`).
2. Seed one object in each prefix so there is something to read. The bucket policy
   (SPEC-013 FR-002) denies data writes to everyone except the portal role and the
   **account root**, so seed as **root** (a regular IAM admin user gets
   `AccessDenied` — that is the policy working). Alternatively, each user can seed
   their *own* file from the signed-in app (step 4 below) since their session is the
   portal role.

```bash
# As account root (regular IAM admins are denied by the bucket policy):
BUCKET=dat-prod-user-space   # = `tofu output -raw s3_user_space_bucket_name`
echo "alice data" > /tmp/a.txt && aws s3 cp /tmp/a.txt "s3://$BUCKET/alice/hello.txt"
echo "bob data"   > /tmp/b.txt && aws s3 cp /tmp/b.txt "s3://$BUCKET/bob/hello.txt"
```

### Steps (as alice)

1. **Sees own space.** Sign in as alice → `/files` shows `hello.txt` under the
   root crumb **"My Files"**. The username (`alice/`) is **not** shown anywhere in
   the breadcrumb or paths.
   - [ ] alice sees her own file; no `alice/` segment visible in the UI.
2. **Brand-new user empty state.** A user with no objects yet sees the empty
   state ("This folder is empty."), not an error.
   - [ ] empty prefix renders the empty state.
3. **Cross-user denied (hand-crafted SDK calls).** Run scoped-credential calls
   against `bob/` and the bucket root from alice's session — each must fail with
   `AccessDenied`. Run this against a **dev build** (`npm run dev`) pointed at the
   real Cognito + bucket: the production bundle's console can't `import()` bare
   module specifiers (and `import.meta` isn't valid in the console), so the dev
   server is what makes the dynamic imports resolve. Bucket/region are hardcoded
   for the same reason — `import.meta.env` is inlined at build time, not available
   at the console:

```js
// Run in the dev-server (npm run dev) console while signed in as alice:
const { fetchAuthSession } = await import('aws-amplify/auth');
const { S3Client, GetObjectCommand, PutObjectCommand, ListObjectsV2Command } =
  await import('@aws-sdk/client-s3');
const { credentials } = await fetchAuthSession();
const s3 = new S3Client({ region: 'us-east-1', credentials });
const bucket = 'dat-prod-user-space';

// Each of these should throw AccessDenied (AccessDenied is returned whether or
// not bob/ has any objects, so a second user's data isn't even required):
await s3.send(new GetObjectCommand({ Bucket: bucket, Key: 'bob/hello.txt' }));       // GET bob/
await s3.send(new PutObjectCommand({ Bucket: bucket, Key: 'bob/x.txt', Body: 'x' })); // PUT bob/
await s3.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: 'bob/' }));         // LIST bob/
await s3.send(new ListObjectsV2Command({ Bucket: bucket }));                         // LIST root (no prefix)
```

   - [ ] `GetObject bob/hello.txt` → `AccessDenied`
   - [ ] `PutObject bob/x.txt` → `AccessDenied`
   - [ ] `ListObjectsV2 prefix=bob/` → `AccessDenied`
   - [ ] `ListObjectsV2` on the bucket root (no prefix) → `AccessDenied`
4. **Own access still works.** The same calls against `alice/` succeed
   (`GetObject alice/hello.txt`, `ListObjectsV2 prefix=alice/`).
   - [ ] own-prefix Get + List succeed.
5. **Credential-expiry retry (optional).** Leave the tab idle past credential
   expiry (or clear them) and navigate a folder; the browser refreshes
   credentials once transparently and the listing loads without an error banner.
   - [ ] mid-session expiry recovers via one silent refresh.

### Cleanup (isolation test)

```bash
aws s3 rm "s3://$BUCKET/alice/hello.txt"
aws s3 rm "s3://$BUCKET/bob/hello.txt"
```

---

## Verifying Per-User Glue Database Provisioning (SPEC-033)

The post-confirmation Lambda creates a Glue database named exactly as the username and
Lake Formation-grants the shared portal role on it. Run after a fresh confirmation.

```bash
PORTAL_ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/dat-portal-user-role"

# 1. The database exists, named verbatim as the username.
aws glue get-database --name alice            # -> Database.Name == "alice"

# 2. The portal role holds the LF grant on that database (and its tables).
aws lakeformation list-permissions \
  --principal DataLakePrincipalIdentifier="$PORTAL_ROLE_ARN" \
  --resource '{"Database":{"Name":"alice"}}'   # -> DESCRIBE/CREATE_TABLE/ALTER/DROP

# 3. CloudWatch shows the provisioning succeeded.
aws logs tail /aws/lambda/dat-prod-post-confirmation --since 10m
```

- [ ] **(deploy-gated)** `get-database` returns `alice`; `list-permissions` shows the grant; logs show success.
- [ ] **(deploy-gated)** A signup with `alice@corp` or `Alice` is rejected by the tightened pre-signup rule (FR-001); no database is created.
- [ ] **(deploy-gated)** No tables exist in the database (`aws glue get-tables --database-name alice` → empty).

### Backfill for pre-existing users (SPEC-033 FR-004)

Users confirmed before the post-confirmation Lambda existed never got a database. The
backfill script runs the same create-database + grant logic (it imports `provision_user`
from the Lambda handler, so the two never drift). Run with operator credentials that are
a Lake Formation admin:

```bash
cd lambdas/post-confirmation
export PORTAL_ROLE_ARN="arn:aws:iam::<account-id>:role/dat-portal-user-role"

# Enumerate confirmed users that may need a database:
aws cognito-idp list-users --user-pool-id "$POOL_ID" \
  --query "Users[?UserStatus=='CONFIRMED'].Username" --output text

python3 backfill.py <username> [<username> ...]   # idempotent
```

- [ ] **(deploy-gated)** Backfill provisions a database for a manually-created pre-existing user; re-running is a no-op-equivalent (idempotent).

### Analytics isolation proof (SPEC-032 FR-006, deferred here from SPEC-032)

With two confirmed users `alice` and `bob`, signed in as alice using her live session
credentials (dev console / hand-crafted SDK calls):

- [ ] **(deploy-gated)** alice can `GetDatabase`/`GetTables`, run `CREATE EXTERNAL TABLE` + `SELECT` in **her** `alice` database, and write results to `alice/athenaresults/`.
- [ ] **(deploy-gated)** alice gets `AccessDenied` (IAM Glue ARN scoping) for the same calls against `bob`'s database.
- [ ] **(deploy-gated)** alice cannot delete anything under `alice/athenaresults/` (delete-deny).

## Cleanup

Delete the test user so the script is repeatable and the directory stays clean:

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id "$POOL_ID" \
  --username "e2e.tester"
```

- [ ] Test user deleted.

---

## Execution Log

| Date | Executed by | App URL / env | Result | Notes (incl. Hosted UI auto-login behavior) |
|---|---|---|---|---|
| 2026-06-11 | Andrew Griffith | Deployed CloudFront | Core flow PASS | Hosted UI requires **one explicit login** after code confirmation (not auto-sign-in) — FR-003 resolved. Not run this pass: re-login (10), wrong-code/resend (14), duplicate signup (15), forgot-password (16); test-user cleanup pending. Re-run these in a future pass. |
| 2026-06-12 | Andrew Griffith | Deployed CloudFront | SPEC-013 FR-003 PASS | Signed-in test user lists their own seeded object (seeded via root) in the deployed `/files` browser, no errors — authenticated user-space path + prefix scoping + bucket policy all work end to end (the bucket-policy Deny does **not** block own-prefix access). FR-004 cross-user denial proven at the policy layer via `aws iam simulate-principal-policy`; live negative-path run (dev-server console) still to be executed. |
