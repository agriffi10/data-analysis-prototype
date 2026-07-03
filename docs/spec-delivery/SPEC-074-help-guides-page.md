# Completed Spec — SPEC-074: Help & Guides Page (Top-Bar Icon + Documentation Page)

## What was completed?

An in-app **Help & guides** surface — presentation + authored content only, no data layer / network / AWS /
IAM / infra / env vars / deps.

- **Header help icon** — `HelpLink` (`NavLink` to `/help`, styled like `NotificationsBell`, active on `/help`),
  mounted left of the bell in the authenticated user-zone of `Header.tsx`; rendered only when authenticated.
- **`/help` route + page** — eager route under `ProtectedLayout` (`routes/HelpPage.tsx` wrapper → feature
  `HelpPage`). Section **sidebar** (`HelpSidebar`, content-derived guide counts, `aria-current`) + active
  section's guides as **accordion cards** (`HelpGuideCard`, `aria-expanded`/`aria-controls`, numbered steps,
  ≤1 Tip/Careful callout, first card default-open). Active section is synced to the **URL hash** (`/help#query`)
  with first-section fallback; document title via `usePageTitle`.
- **Content** — `helpContent.ts` (`HELP_SECTIONS`), code-grounded against the shipped app (FR-005): **Files**
  (upload, folders, download, rename/move/copy/delete, details, **+ Create a table from a folder**), **Query**
  (run, active database, save, history, results, save-results), **Shared connections** (create, add/manage/remove
  members, **+ pending/active join status**, leave, delete), **Notifications** (bell, read, mark-read/all).
  `renderInline` parses `<b>`/`<kbd>` in step + callout strings (no `dangerouslySetInnerHTML`). Icons added to
  `components/icons.tsx`: `HelpCircleIcon`, `ChevronDownIcon`, `DatabaseIcon`, `ConnectionsIcon`, `InfoIcon`,
  `WarningIcon`.
- **Deliberate deviation (FR-005):** the spec's exclusion examples (Table Builder 066→072, join status 073) were
  written while those were Draft; both shipped before implementation, so per FR-005's *document-what's-shipped*
  principle they are **now documented** (user-confirmed). Spec header carries an implementation note.
- **Process change (user ask):** added a **step 6 — user-facing docs sweep** to the completion ritual in
  `docs/process.md` §5 and CLAUDE.md, so every future spec checks whether `helpContent.ts` / onboarding copy
  need updating when a user-facing feature lands or changes.

## What changed from earlier specs?

Additive only. `Header.tsx` gained the `HelpLink`; `App.tsx` gained the `/help` route; `icons.tsx` gained six
icons. Nothing prior was edited in behavior.

## Verification

Prettier `format:check`, `tsc --noEmit`, and ESLint clean; full Vitest suite **881 passed** (15 new help tests
incl. `HelpPage.a11y.test.tsx` axe baseline + header-icon name). Manually verified in the dev-unauth browser at
`/help`: deep-link `#query`, sidebar section switch + hash update, accordion + `<b>`/`<kbd>` parsing, warning/tip
callouts — caught & fixed a callout not running through `renderInline` (literal `<b>`). No infra to `tofu`.
