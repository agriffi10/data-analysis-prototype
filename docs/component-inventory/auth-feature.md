# Auth feature (`apps/portal/src/features/auth/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `useAuth()` | `features/auth/useAuth.ts` | Access auth status + user + sign-in/out actions. |
| `AuthProvider` | `features/auth/AuthProvider.tsx` | Context provider wiring Amplify auth state. |
| `getCurrentAuthUser()` | `features/auth/auth.service.ts` | Current user as `ServiceResult<AuthUser>`. |
| `startSignIn()` / `startSignUp()` / `startSignOut()` | `features/auth/auth.service.ts` | Hosted-UI auth flows (`ServiceResult`). |
| `AuthStatus`, `AuthUser`, `AuthContextValue` | `features/auth/auth.types.ts` | Auth types. |

