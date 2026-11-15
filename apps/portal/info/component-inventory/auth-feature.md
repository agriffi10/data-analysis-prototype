# Auth feature (`apps/portal/src/features/auth/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `useAuth()` | `features/auth/useAuth.ts` | Access auth status + user + sign-in/out actions. |
| `AuthProvider` | `features/auth/AuthProvider.tsx` | Context provider over the portal server's session: reads `/auth/session` once, tells the API client which user the tab holds, and registers what a 401 does (re-read; signed-out locally, or a reload when another user now holds the session). |
| `getCurrentAuthUser()` | `features/auth/auth.service.ts` | Current user as `ServiceResult<AuthUser>`. |
| `startSignIn()` / `startSignUp()` / `startSignOut()` | `features/auth/auth.service.ts` | Hosted-UI auth flows (`ServiceResult`). |
| `AuthStatus`, `AuthUser`, `AuthContextValue` | `features/auth/auth.types.ts` | Auth types. |

