# Shared hooks (`apps/portal/src/hooks/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `useEscapeKey(onEscape, enabled?)` | `hooks/useEscapeKey.ts` | Calls `onEscape` on Escape while `enabled`; the keydown-listener Effect consolidated from every modal/drawer. (react-best-practices pass) |
| `usePageTitle(page)` | `hooks/usePageTitle.ts` | Syncs `document.title` for the page (SPEC-031). |

