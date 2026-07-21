# UI primitive utility (`apps/portal/src/lib/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `cx(...args)` | `lib/cx.ts` | Class-name join helper (filters falsy); used by all SPEC-028 primitives. No external dep. |
| `formatPageTitle(page?)` | `lib/formatPageTitle.ts` | Pure title formatter → `"{page} — S3 File Portal"` or the app name alone (SPEC-031). |
| `usePageTitle(page?)` | `hooks/usePageTitle.ts` | Sets `document.title` via `formatPageTitle`; call at the top of a page (SPEC-031). |

