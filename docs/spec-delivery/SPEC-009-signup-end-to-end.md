# Completed Spec - Sign-Up End to End — Account Creation to Authenticated Session

## What was completed from this spec?

The full journey from "I don't have an account" to "I'm signed in looking at the
files page," delivered across two phases and verified end-to-end against the
deployed CloudFront environment.

**Phase 1 — signup entry point + verification email (merged in [#11](https://github.com/agriffi10/data-analysis-prototype/pull/11)):**

- **IaC (FR-002)** — `infra/modules/auth/cognito.tf` gained a
  `verification_message_template` (`CONFIRM_WITH_CODE`, subject "Your S3 Portal
  verification code", body containing `{####}`). Self-signup and email
  auto-verify were re-asserted unchanged (no SPEC-006 regression).
- **`startSignUp()` (FR-001)** — `apps/portal/src/features/auth/auth.service.ts`
  builds the Hosted UI `/signup?client_id=…&response_type=code&scope=openid+email+profile&redirect_uri=…`
  URL from the same env vars Amplify uses, then `window.location.assign`. It
  returns `ServiceResult` and guards missing config (no navigation to a broken
  URL), matching `startSignIn`/`startSignOut` and the project no-throw
  convention. `signUp` is exposed through the auth context like `signIn`, so
  config errors surface in the SPEC-007 error banner.
- **Landing page (FR-001)** — `routes/LandingPage.tsx` shows a "Create account"
  CTA beside "Sign in", plus username guidance matching the SPEC-012 rule exactly
  (*3–64 chars, letters/numbers and `. _ @ -` only*).
- **Tests** — 4 new (`startSignUp` URL construction + missing-config; `signUp`
  delegation + error), layout fixtures updated for the new context field.

**Phase 2 — journey hardening + E2E acceptance (FR-003, FR-004, FR-005):**

- **`docs/testing/auth-e2e.md`** — the numbered end-to-end acceptance script
  (signup → verify → first login → `/files` → refresh → logout → re-login →
  gated access while signed out → forgot-password smoke test), with cleanup steps
  and an execution log.
- **Executed 2026-06-11 against deployed CloudFront.** The core flow passed:
  signup, custom-subject verification email, code confirmation, first login
  landing authenticated on `/files` with the correct username, refresh
  persistence, and gated access with the return-path preserved across the OAuth
  round-trip.

### FR-003 open question — resolved

The Hosted UI does **not** auto-sign-in after code confirmation: the user must
complete **one explicit login** before reaching `/files`. FR-003 and the E2E
script both reflect this; step 7 ("Complete sign-in if prompted") is the
expected behavior, not a defect.

### Verification

- Phase 1: `tsc -b`, `npm run lint`, `npm run build` clean; `npm run test` →
  56 passed (4 new); `tofu validate` clean.
- Phase 2: E2E acceptance script executed against the deployed CloudFront
  environment; core signup-to-gated-access flow passed and is recorded in the
  execution log.

## What has changed?

- **`apps/portal/src/features/auth/`** — `auth.service.ts` gained `startSignUp()`;
  `auth.types.ts` added `signUp: () => void` to `AuthContextValue`;
  `AuthProvider.tsx` wired a `signUp` callback (mirrors `signIn`, sets the error
  banner on failure). These extend the SPEC-007 auth surface without changing
  existing behavior.
- **`apps/portal/src/routes/LandingPage.tsx`** — added the "Create account" CTA
  and username guidance alongside the existing "Sign in" action (SPEC-008).
- **`infra/modules/auth/cognito.tf`** — added the verification email template;
  no other pool settings changed.
- **`docs/specs/SPEC-009-*.md`** — API contract synced to the implemented
  `ServiceResult` + context design during Phase 1; Status set to Completed and
  the FR-003 open question resolved during Phase 2.

### Follow-ups / notes

- **Not run in the acceptance pass** (optional smoke checks; re-run as regression
  later): re-login after logout (step 10), wrong-code/resend (14), duplicate
  username/email signup (15), and the forgot-password smoke test (16). The
  test-user cleanup (`admin-delete-user`) is still pending.
- No new `VITE_*` variables were introduced by this spec.
- `auth-e2e.md` doubles as the regression checklist for any future auth change.
