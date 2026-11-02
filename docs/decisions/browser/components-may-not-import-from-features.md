---
type: Decision
title: "`components/` may not import from `features/` (SPEC-155)"
description: "**`components/` may not import from `features/`** — enforced by lint. A leaf feature that becomes a shared layer gets **extracted before its second consumer**, not after."
---

`features/query/` had become a shared layer nobody declared: `components/ToastProvider` and
`components/Sidebar` imported from it, and five sibling features pulled `CATALOG_IDENTIFIER_RE`,
`Connection`, `isConnectionUsable` and `useConnections` out of it. That direction is backwards —
`components/` is the shared presentation layer that features compose, so it cannot depend on one.

The fix moved each shared thing to where its direction is correct: `Toast` to `components/`, the
identifier rule to `lib/catalogIdentifier.ts`, and the connections domain — `Connection`,
`ConnectionKind`, `isConnectionUsable`, `useConnections`, `connectionStatusLabel`, plus the two nav
surfaces `Sidebar` and `SpacesList` — into a new `features/connections/`.

**The rule is enforced, not documented.** `eslint.config.js` bans `features/**` imports under
`src/components/**`. Two things are exempt, both deliberately:

- **Tests.** Integration-style tests mount real features by design (`react.md` §21), so the rule can
  only produce noise on that glob.
- **`Header.tsx` and `ProtectedLayout.tsx`.** These are app *chrome*: they exist to wire features
  into the shell, so composing features is what they are for. Bringing them under the rule needs a
  separate app-shell layer, which is a re-layering rather than an import fix. They are **named in
  the config** rather than left as a silent violation, so a third such file requires an explicit
  edit to that list. Everything else that was on the list has been moved out of `components/`.

Two residuals, both recorded rather than hidden:

- `features/connections/useConnections.ts` still reads `queryKeys.connections` from
  `features/query/queryKeys.ts`. Feature-to-feature is allowed, and splitting the key factory would
  change key *values* that two tests assert.
- ~~**`lib/queryClient.ts` imports `features/file-browser/fileBrowserKeys`**~~ — **CLOSED 2026-08-09.**
  It was a lower layer importing a feature, and a strictly worse inversion than the one this decision
  targets. `invalidateListing` moved to `features/file-browser/invalidateListing.ts`, beside the key
  factory it builds from; `lib/queryClient.ts` now owns only the client and imports no feature.
  `features/query`'s save-results flow reaches it through the file-browser barrel — feature-to-feature,
  which is allowed, and which was already true transitively through `lib/`.

  **The rule widened with it**, to `src/lib/**` and `src/hooks/**`. That was the point of the move:
  fixing the one file without widening the glob leaves the next one to be found by hand.

  **The test exemption is load-bearing on `src/lib/**`, not a formality.** `lib/support.test.ts`
  imports seven feature service modules — it is the consolidated lib suite, and testing a lib helper
  against real feature callers is what it is for. Without `src/lib/**/*.test.{ts,tsx}` on the
  exemption list the rule reports **6** violations there and `npm run lint` fails. The
  `src/hooks/**` test glob is inert today (nothing under `src/hooks/` imports a feature) and is
  carried for symmetry. Non-test files in both directories were clean, which is what made the
  widening a one-line glob change rather than a migration.

  The mock count in the original note was wrong — **two** test files mocked the module by path
  (`fileOpHooks.test.ts`, `UploadQueueProvider.test.tsx`); the other four merely imported it. That
  overstatement is most of why this looked expensive enough to defer.

  **What the rule still does not catch:** a dynamic `await import('../features/…')`. Base
  `no-restricted-imports` only sees static import/export forms — type-only imports, `export … from`
  and deep relative paths are all caught. The hole predates the widening and is unchanged by it.

## History

### 2026-08-09

- **Changed:** The lower-layer import in `lib/queryClient.ts` was moved out and the rule widened to `src/lib/**` and `src/hooks/**`.

### 2026-08-06

- **Settled:** SPEC-155.
