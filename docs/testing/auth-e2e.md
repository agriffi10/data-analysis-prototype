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

Pick a test username that satisfies the SPEC-012 rule (`^[a-zA-Z0-9._@-]{3,64}$`),
e.g. `e2e.tester`. The username becomes the user's S3 prefix and audit identity.

---

## Test Steps

### 1. Fresh signup

1. Open `$APP_URL` in a clean browser profile (or incognito). **Expected:** the landing page renders with **"Sign in"** and **"Create account"**, plus the username guidance line (*3–64 chars, letters/numbers and `. _ @ -` only*). No console errors.
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
