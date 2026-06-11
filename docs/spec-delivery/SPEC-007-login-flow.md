# Completed Spec - User Login Flow — Cognito Hosted UI + Amplify

## What was completed from this spec?

Session management as a capability: users can sign in to and out of the portal via the Cognito Hosted UI, with Amplify v6 establishing and persisting the session and exposing the authenticated identity to the app. No route is gated yet (SPEC-008) and no S3 access is connected (SPEC-011).

- `aws-amplify@^6.18.0` added to `apps/portal` (pre-approved in the tech stack).
- `src/lib/amplify.ts` — `Amplify.configure` with user pool ID, client ID, Hosted UI domain, scopes (`openid`/`email`/`profile`), `redirectSignIn`/`redirectSignOut` = `VITE_APP_URL`, `responseType: 'code'`. Guarded by an exported `isAmplifyConfigured` flag: if any required Cognito var is missing it skips configuration instead of throwing (FR-001). No `identityPoolId` — credential exchange is SPEC-011. Imported first in `src/main.tsx`.
- `src/features/auth/`:
  - `auth.types.ts` — `AuthStatus`, `AuthUser`, `AuthContextValue`.
  - `auth.service.ts` — `getCurrentAuthUser`, `startSignIn` (`signInWithRedirect`), `startSignOut` (`signOut`); all return `ServiceResult` and never throw. Email is best-effort via `fetchUserAttributes`.
  - `authContext.ts` — the React context in its own module (keeps `AuthProvider.tsx` component-only for react-refresh; lets `useAuth` consume it without a cycle).
  - `AuthProvider.tsx` — derives auth state from Amplify, restores the session on mount, and subscribes to `Hub` auth events (`signedIn` → re-derive, `signedOut` → clear, `signInWithRedirect_failure` → non-blocking error). Not-configured state is set via `useState` initializers (avoids the `react-hooks/set-state-in-effect` rule); the mount session-restore runs in an async IIFE so state updates happen post-`await`.
  - `useAuth.ts` — returns `{ status, user, error, signIn, signOut }`; throws a descriptive error when used outside the provider.
  - `index.ts` — barrel (`AuthProvider`, `useAuth`, types).
  - `auth.service.test.ts` (7) + `AuthProvider.test.tsx` (9) — Amplify fully mocked.
- `src/components/Header.tsx` — persistent, auth-aware header: neutral placeholder while `loading`, "Sign in" when `unauthenticated`, username + "Sign out" when `authenticated`, with an inline error banner. The file browser stays usable in all states.
- `src/main.tsx` wraps `<App>` in `<AuthProvider>` **outside** any future router (SPEC-008 nests the router inside it). `src/App.tsx` restructured into a shell that always renders `Header`.

### Verification

- `npm run test` → 47 passed (16 new auth tests). `npm run lint` clean, `tsc -b` clean, production build succeeds.
- Manual E2E against the live SPEC-006 pool with a console-created user (`agriffith`): Sign in → Hosted UI → set permanent password → landed signed in with username in header → page refresh kept the session → Sign out → signing in again re-prompted for credentials.
- **FR-004 open question resolved:** Amplify v6 `signOut()` with the OAuth config redirects through the Cognito `/logout` endpoint and invalidates the Hosted UI cookie session — no explicit logout-endpoint call needed.

## What has changed?

- **`src/types/service.types.ts` (new) + `src/types/s3.types.ts`** — `ServiceResult<T>` moved out of `s3.types.ts` (it is not S3-specific) into a neutral `service.types.ts`; `s3.types.ts` re-exports it for back-compat. `auth.service.ts` and `file-browser/fileBrowser.service.ts` now import `ServiceResult` from the neutral location (`fileBrowser.service.ts` still imports `FileList` from `s3.types.ts`). No behavior change.
- **`src/App.tsx`** — restructured from a single-purpose file-browser page into an app shell with a persistent `Header`; the missing-`VITE_S3_BUCKET_NAME` config-error path is preserved inside the shell.
- **`src/main.tsx`** — added the `./lib/amplify` side-effect import (first) and the `<AuthProvider>` wrapper.
- **`apps/portal/.env.local` (gitignored, not committed)** — populated with the live SPEC-006 Cognito values and `VITE_APP_URL=http://localhost:5173` for local sign-in.

### Follow-ups / notes

- No new `VITE_*` variables. For the deployed build, the four already-documented vars (`VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_APP_URL`) must be added to the repo's GitHub Actions **variables** so `deploy-app.yml` injects them at build time — not yet done (the app is verified locally).
- The test user `agriffith` was created directly via `admin-create-user`, bypassing the SPEC-012 pre-signup validation (not built yet).
