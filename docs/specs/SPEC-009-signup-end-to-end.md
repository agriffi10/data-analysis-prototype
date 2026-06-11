# Spec: Sign-Up End to End — Account Creation to Authenticated Session

**ID:** SPEC-009
**Status:** Completed
**Last Updated:** 2026-06-11
**Depends On:** SPEC-006 (self-signup enabled on the pool), SPEC-007 (login flow), SPEC-008 (gated layout)

## Overview

Deliver the complete journey from "I don't have an account" to "I'm signed in looking at the files page." Signup itself happens on the Cognito Hosted UI (per the architecture decision — no custom forms): the user creates a username/password, verifies their email with a code, and returns to the portal authenticated. This spec makes that journey first-class: an explicit "Create account" entry point in the app, a verified Hosted UI signup configuration, sensible verification emails, handled failure paths, and a documented end-to-end acceptance test that exercises SPEC-006 through SPEC-009 together.

## Scope

### In Scope

- "Create account" call-to-action on the landing page that deep-links to the Hosted UI sign-up page (not just login)
- Cognito signup configuration verification/tuning in `infra/modules/auth/` (verification email subject/message, code-based confirmation)
- First-login experience: a newly confirmed user lands authenticated on `/files`
- Handled failure paths: abandoned signup, expired/wrong verification code, duplicate username/email — app never breaks on return
- Username guidance: surface the constraint that usernames become S3 prefixes/session tags (≤64 chars, `a-z A-Z 0-9 = , . @ - _`)
- A written end-to-end test script (`docs/testing/auth-e2e.md`) covering signup → verify → login → gated access → logout → re-login

### Out of Scope

- Custom in-app signup forms (Hosted UI only)
- Email-domain restrictions or invite codes (pre-signup Lambda — future spec if needed)
- SES integration (default Cognito email sender, ~50 emails/day, acceptable for MVP)
- Profile management, password change UI (Hosted UI native flows exist; not verified here except forgot-password smoke test)
- MFA
- Automated browser E2E tooling (Playwright/Cypress) — manual script only; automation is a future quality spec

---

## Functional Requirements

### FR-001: Signup Entry Point

#### Description:

The landing page offers account creation directly, taking the user to the Hosted UI sign-up screen rather than the login screen.

#### Acceptance Criteria:

- [ ] Landing page (`/`) shows a "Create account" action alongside "Sign in"
- [ ] "Create account" navigates to the Hosted UI `/signup` endpoint with correct `client_id`, `response_type=code`, `redirect_uri`, and scopes (constructed from the same env vars as Amplify config; document the URL construction in `auth.service.ts`)
- [ ] Brief username guidance is shown near the CTA, matching the SPEC-012-enforced rule exactly: 3–64 characters, letters/numbers and `. _ @ -` only (the username becomes the user's S3 prefix and audit identity)
- [ ] "Sign in" continues to go to the Hosted UI login screen (SPEC-007 behavior unchanged)

### FR-002: Cognito Signup Configuration

#### Description:

The User Pool's signup/verification behavior is explicit in IaC, not left to defaults.

#### Acceptance Criteria:

- [ ] `verification_message_template` is configured: code-based email confirmation (`CONFIRM_WITH_CODE`), custom subject (e.g. "Your S3 Portal verification code") and message including `{####}`
- [ ] Self-signup remains enabled; email remains auto-verified attribute (re-assert SPEC-006 FR-002 — no regression)
- [ ] `tofu plan` against the SPEC-006 state shows only the intended template changes
- [ ] Signup on the Hosted UI requires email and rejects passwords violating the SPEC-006 policy (verified manually)

### FR-003: Confirmation and First Login

#### Description:

After entering the emailed code on the Hosted UI, the user completes authentication and enters the portal without extra steps.

#### Acceptance Criteria:

- [ ] Completing code verification on the Hosted UI leads (directly, or via one sign-in prompt — document actual Hosted UI behavior) to a redirect back to the app with a valid auth code
- [ ] The new user arrives `authenticated`, with their username in the header, on `/files`
- [ ] A page refresh keeps the new user signed in (session persistence, SPEC-007 FR-002)
- [ ] The new user's username appears correctly — matches what they typed at signup

### FR-004: Failure Paths

#### Description:

Every way the signup journey can go sideways leaves the app in a usable state.

#### Acceptance Criteria:

- [ ] Abandoning the Hosted UI (browser back to the app mid-signup) leaves the app `unauthenticated` on the landing page with no console errors
- [ ] Wrong/expired verification code: Hosted UI handles retry natively; "Resend code" works (manual verification)
- [ ] Attempting signup with an existing username or already-used email shows the Hosted UI's error — and returning to the app afterward works normally
- [ ] An unconfirmed user attempting to sign in is prompted by the Hosted UI to complete verification (resume path works)
- [ ] OAuth error callbacks to the app (denied, expired code) surface the SPEC-007 non-blocking error banner

### FR-005: End-to-End Acceptance Script

#### Description:

A repeatable manual test script proves the whole auth stack (SPEC-006→009) works against deployed infrastructure, and serves as the regression checklist for future auth changes.

#### Acceptance Criteria:

- [ ] `docs/testing/auth-e2e.md` exists with numbered steps and expected results for: fresh signup with a real email → receive code → confirm → land on `/files` → refresh → logout → login → access `/files` directly while signed out (redirected) → forgot-password smoke test
- [ ] The script includes cleanup steps (delete test user via `aws cognito-idp admin-delete-user`)
- [ ] The script has been executed once against the deployed CloudFront environment with all steps passing, and the execution date is recorded in the doc

---

## Data Model

No new types. Reuses `AuthUser`/`AuthContextValue` from SPEC-007.

---

## API / Interface Contract

```ts
// src/features/auth/auth.service.ts — addition
// Builds the Hosted UI signup URL from env config and navigates (full page).
// Returns ServiceResult (never throws) to match startSignIn/startSignOut and the
// project no-throw convention: a missing-config case returns an error instead of
// navigating to a broken URL. Synchronous — on success the browser leaves the page.
startSignUp(): ServiceResult<void>;
// → window.location.assign(
//     `https://${domain}/signup?client_id=${clientId}&response_type=code` +
//     `&scope=openid+email+profile&redirect_uri=${encodeURIComponent(appUrl)}`
//   )

// Exposed through the auth context like signIn/signOut, so the landing page calls
// useAuth().signUp() and config errors surface via the SPEC-007 error banner:
// AuthContextValue gains `signUp: () => void`.
```

## Environment Variables

None new. Note for testing: signup requires receiving real email — default Cognito sender is limited to ~50/day, sufficient for acceptance testing.

## File & Folder Structure

```
apps/portal/src/
├── features/auth/
│   └── auth.service.ts            ← + startSignUp()
└── routes/
    └── LandingPage.tsx            ← + Create account CTA + username guidance

infra/modules/auth/
└── cognito.tf                     ← + verification_message_template

docs/testing/
└── auth-e2e.md                    ← NEW: end-to-end acceptance script
```

## Implementation Phases

### Phase 1: IaC verification template + signup entry point

- Add `verification_message_template` to the auth module (FR-002); apply via `deploy-infra.yml`
- Add `startSignUp()` and the landing page CTA + username guidance (FR-001)

#### Checkpoint

"Create account" lands on the Hosted UI sign-up screen for the correct pool/client. A test signup receives the custom-subject verification email. `npm run test` and `tofu validate` pass.

### Phase 2: Journey hardening + E2E script

- Walk and fix all failure paths (FR-004); confirm first-login behavior (FR-003)
- Write `docs/testing/auth-e2e.md` and execute it fully against the deployed environment (FR-005)

#### Checkpoint

The full E2E script passes against CloudFront with a real email address, every step checked off, execution date recorded. This checkpoint is the acceptance gate for the whole SPEC-006→009 arc.

## Open Questions

- [x] **Resolved (2026-06-10):** username constraints are enforced server-side by a pre-signup trigger Lambda — SPEC-012. Guidance here (FR-001) mirrors that rule.
- [x] **Resolved (2026-06-11):** the Hosted UI does **not** auto-sign-in after code confirmation — one explicit login is required before reaching `/files`. Verified in the SPEC-009 E2E run against deployed CloudFront; reflected in FR-003 and `docs/testing/auth-e2e.md`.
- [x] **Resolved (2026-06-10):** no signup monitoring for MVP; revisit before any public exposure.
