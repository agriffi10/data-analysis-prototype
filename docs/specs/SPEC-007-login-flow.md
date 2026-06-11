# Spec: User Login Flow — Cognito Hosted UI + Amplify

**ID:** SPEC-007
**Status:** Draft
**Last Updated:** 2026-06-10
**Depends On:** SPEC-006 (Cognito User Pool must exist and be applied)

## Overview

Give users the ability to sign in to and out of the portal. The app redirects to the Cognito Hosted UI for credential entry; on return, Amplify v6 establishes and persists the session, and the app exposes the authenticated user's identity to the rest of the UI. This spec delivers session management as a capability — it does **not** yet restrict access to any page (SPEC-008) or connect authentication to S3 access (future spec: the shared IAM role and STS integration are not yet provisioned).

## Scope

### In Scope

- Add `aws-amplify` v6 dependency (already approved in CLAUDE.md tech stack)
- Amplify configuration module (`src/lib/amplify.ts`) initialized before the React tree mounts
- `auth` feature: auth context/provider, `useAuth` hook, auth service wrapping Amplify calls
- Sign-in via redirect to the Cognito Hosted UI (`signInWithRedirect`)
- OAuth redirect callback handling on return from Cognito
- Sign-out (clears local session and signs out of the Hosted UI session)
- Header UI: "Sign in" button when signed out; username + "Sign out" button when signed in
- Session restoration on page load/refresh
- New env vars documented in `.env.example` usage (vars already exist from SPEC-003/006)

### Out of Scope

- Blocking unauthenticated access to any page (SPEC-008)
- Signup / account creation flows (SPEC-009 — though the Hosted UI's built-in link may be visible, its end-to-end behavior is specced there)
- STS `AssumeRoleWithWebIdentity`, session tags, per-user S3 credentials — requires the IAM portal role, not yet provisioned
- Any change to the file browser or S3 client (continues using the SPEC-002 anonymous/static-credential test bucket path)
- Password reset / forgot-password flows (Hosted UI provides them natively; verifying them is deferred to SPEC-009 testing)
- Token-expiry-driven S3 retry logic (belongs with the STS integration spec)

---

## Functional Requirements

### FR-001: Amplify Initialization

#### Description:

Amplify is configured once from env vars before any component renders, per the configuration documented in `docs/architecture.md`.

#### Acceptance Criteria:

- [ ] `src/lib/amplify.ts` calls `Amplify.configure` with user pool ID, client ID, Hosted UI domain, scopes (`openid`, `email`, `profile`), `redirectSignIn`/`redirectSignOut` set to `VITE_APP_URL`, and `responseType: 'code'`
- [ ] `src/main.tsx` imports `./lib/amplify` as its first import
- [ ] If any required Cognito env var is missing, the app still renders (auth features show a configuration error state; the file browser is unaffected)

### FR-002: Auth Provider and `useAuth` Hook

#### Description:

A React context exposes auth state to the whole app. State is derived from Amplify and restored on load.

#### Acceptance Criteria:

- [ ] `AuthProvider` wraps the entire app in `main.tsx`, **outside** any router added later (SPEC-008 nests the router inside `AuthProvider` so route guards can call `useAuth`); composition order: amplify import → `AuthProvider` → app/router
- [ ] `useAuth()` returns `{ status, user, signIn, signOut }` per the Data Model below
- [ ] On mount, the provider checks for an existing session (`getCurrentUser`/`fetchAuthSession`); status moves `loading → authenticated | unauthenticated`
- [ ] A page refresh while signed in restores the session without re-prompting for credentials
- [ ] Calling `useAuth` outside the provider throws a descriptive error
- [ ] Amplify `Hub` auth events (`signedIn`, `signedOut`, `signInWithRedirect_failure`) update the context state

### FR-003: Sign-In via Hosted UI Redirect

#### Description:

Clicking "Sign in" redirects to the Cognito Hosted UI; after successful credential entry, Cognito redirects back and the session is established.

#### Acceptance Criteria:

- [ ] `signIn()` invokes Amplify `signInWithRedirect()` (full-page redirect to the Hosted UI)
- [ ] On return with a valid auth code, the provider transitions to `authenticated` and exposes the Cognito username
- [ ] If the redirect callback contains an OAuth error (e.g. user backs out), the app lands in `unauthenticated` state with a surfaced, non-blocking error message — never a blank page or unhandled exception
- [ ] The URL is cleaned of OAuth query params after the callback is processed (Amplify default behavior verified)

### FR-004: Sign-Out

#### Description:

Signing out clears the local session and the Cognito Hosted UI cookie session.

#### Acceptance Criteria:

- [ ] `signOut()` calls Amplify `signOut()`; the Hosted UI session is also invalidated (user is redirected through the Cognito logout endpoint and back to `VITE_APP_URL`)
- [ ] After sign-out, `useAuth()` reports `unauthenticated` and no tokens remain in storage
- [ ] Signing in again after sign-out prompts for credentials (session truly ended)

### FR-005: Header Auth UI

#### Description:

A minimal, persistent header shows auth state and actions.

#### Acceptance Criteria:

- [ ] When `unauthenticated`: header shows a "Sign in" button
- [ ] When `authenticated`: header shows the username and a "Sign out" button
- [ ] When `loading`: header shows a neutral placeholder (no flash of "Sign in" before session restore completes)
- [ ] The file browser remains fully usable in all three states (gating is SPEC-008)

---

## Data Model

```ts
// src/features/auth/auth.types.ts

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export type AuthUser = {
  username: string;       // Cognito username — future S3 prefix + session tag
  email?: string;         // from the id token, if present
};

export type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  error: string | null;     // last auth error, surfaced non-blockingly
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
};
```

---

## API / Interface Contract

```ts
// src/features/auth/auth.service.ts — wraps Amplify; never throws
getCurrentAuthUser(): Promise<ServiceResult<AuthUser>>;
startSignIn(): Promise<ServiceResult<void>>;     // signInWithRedirect
startSignOut(): Promise<ServiceResult<void>>;

// src/features/auth/useAuth.ts
const { status, user, error, signIn, signOut } = useAuth();
```

## Environment Variables

No new variables. This spec begins consuming (all already in `.env.example`):
`VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_APP_URL`.

GitHub Actions: the four variables above must be added to the repo's Actions variables so `deploy-app.yml` injects them at build time (extend `.github/workflows/README.md` accordingly).

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   └── amplify.ts                 ← NEW: Amplify.configure
├── features/
│   └── auth/                      ← NEW
│       ├── index.ts               ← barrel: AuthProvider, useAuth
│       ├── AuthProvider.tsx
│       ├── AuthProvider.test.tsx
│       ├── useAuth.ts
│       ├── auth.service.ts
│       ├── auth.service.test.ts
│       └── auth.types.ts
├── components/
│   └── Header.tsx                 ← NEW: auth-aware header
└── main.tsx                       ← amplify import first; AuthProvider wrap
```

## Implementation Phases

### Phase 1: Dependency, config, service layer

- Add `aws-amplify@^6` to `apps/portal/package.json` (note in CLAUDE.md tech stack: already listed)
- Create `src/lib/amplify.ts` and wire into `main.tsx` (FR-001)
- Create `auth.service.ts` + types with unit tests (Amplify mocked)

#### Checkpoint

`npm run test` passes with new `auth.service.test.ts`. `npm run dev` starts with no console errors when Cognito env vars are present in `.env.local` (values from SPEC-006 `tofu output`).

### Phase 2: Provider, hook, header UI

- Implement `AuthProvider`, `useAuth`, Hub event wiring (FR-002)
- Implement sign-in/sign-out behaviors (FR-003, FR-004)
- Add `Header` to the app shell (FR-005)

#### Checkpoint

Manual end-to-end against the real SPEC-006 pool with a console-created test user: click "Sign in" → Hosted UI → enter credentials → land back signed in with username in header → refresh page (still signed in) → "Sign out" → signed out, and signing in again prompts for credentials. `npm run test` and `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-10):** first test user is created via AWS console/CLI for Phase 2 verification (signup UX is owned by SPEC-009).
- [x] **Resolved (2026-06-10):** `localhost:5173` callback URL is guaranteed by SPEC-006 FR-003 — no action here beyond the Phase 2 sanity check.
- [x] **Resolved (2026-06-10):** auth errors surface as a simple inline banner under the header.
- [ ] Verify during Phase 2 that Amplify v6 `signOut()` with an OAuth (Hosted UI) config actually redirects through the Cognito `/logout` endpoint and invalidates the Hosted UI cookie session. If it does not, call the logout endpoint explicitly in `startSignOut()` and document it.
