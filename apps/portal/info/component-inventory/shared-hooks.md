# Shared hooks (`apps/portal/src/hooks/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `useEscapeKey(onEscape, enabled?)` | `hooks/useEscapeKey.ts` | Calls `onEscape` on Escape while `enabled` — but dispatches by **tree depth**, not per-component opt-out: a module-level registry holds every enabled handler with its `EscapeLayer` depth, and only the innermost one fires. Nested dialogs are correct by construction, so the old `closeOnEscape` opt-outs are gone. A busy `Modal` **swallows** Escape (via `useEscapeBlock`) instead of letting it dismiss the layer beneath (SPEC-155 FR-006). |
| `useEscapeBlock(active)` | `hooks/useEscapeKey.ts` | Registers a layer that consumes Escape without acting on it — for a dialog that is up but must not close (in-flight). |
| `EscapeDepthContext` / `useEscapeDepth()` | `hooks/escapeLayerContext.ts` | The depth an overlay sits at; `EscapeLayer` increments it. Kept out of the component file so that file exports only a component. |
| `useClientPager(items, pageSize)` | `hooks/useClientPager.tsx` | `{pageItems, pagerProps, resetToFirst}` for client-side pagination over an in-memory list. **The clamp is the point**: the page index is held in state but never trusted — every render derives a safe index from the current count, so a list that shrinks under the user can't strand them on a blank page. Builds the `<Pager>` label *and* its `sr-only` page number, which the two pages that hand-rolled this had already written identically (SPEC-155 FR-004). |
| `usePageTitle(page?)` | `hooks/usePageTitle.ts` | Syncs `document.title` via `formatPageTitle`; call at the top of a page (SPEC-031). |

