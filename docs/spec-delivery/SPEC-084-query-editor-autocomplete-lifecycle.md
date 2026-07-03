# Completed Spec — SPEC-084: Query Editor Autocomplete Lifecycle Fix

## What was completed?

Made the Monaco SQL completion provider's registration/disposal robust to editor
unmount/remount (query-tab switches, React StrictMode), so schema-aware autocomplete
can't silently die or stack duplicates. Presentation-only; no data/completion-content change.

- **`SqlEditor.tsx` — ref-counted registration (FR-001):** the shared `sql` completion provider is now
  **acquired on mount / released on unmount via a ref-count** — registered when the first editor mounts,
  disposed only when the **last** unmounts — replacing the fragile mix of "register in Monaco `onMount`" +
  "dispose in a per-instance `useEffect` cleanup that nulled the singleton." Registration moved into a
  `useEffect` using the module `monaco` import (decoupled from Monaco's editor-creation timing). The
  `completionSchemaRef` ref-forwarding (latest active-DB schemas) is unchanged.
- Net effect: across a tab-switch/StrictMode mount→unmount→remount there is always **exactly one** active
  provider — never a disposed-then-never-re-registered gap, never a duplicate.

## What changed from earlier specs?

`SqlEditor` internals only (`registerSqlCompletionsOnce` → `acquireSqlCompletions`/`releaseSqlCompletions`);
no props or exported API changed. Reuses the SPEC-065/077 `createSqlCompletionProvider` unchanged.

## Verification

`format:check`, `tsc`/`build`, ESLint (no `exhaustive-deps` suppression), Vitest **907 passed**. New
`SqlEditor` tests: the provider stays alive while a second editor instance is still mounted (fails under the
old per-instance disposal), and one active + still-functional provider survives an unmount→remount. Live
browser deferred — `/query` is Cognito-gated and needs the Monaco worker + live Athena (same limitation as
prior query-workspace specs).
