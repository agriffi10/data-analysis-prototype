---
type: Spec
id: SPEC-246
title: "Archive and Restore Get Their Own Kill Switch"
description: "Gives archive and restore their own archive feature flag, so an operator can withdraw both entry points by publishing the flag document without an app build or disabling the whole file browser."
spec_status: Completed
depends_on: [SPEC-162, SPEC-163, SPEC-172, SPEC-190]
---

**Dependency notes:** SPEC-162/163 (the flag document and the gated-surfaces registry), SPEC-172 (the archive and restore entry points), SPEC-190 (the first kill switch, `asyncFileOperations`)
## Overview

Archive is the one place in the portal where a mistake cannot be undone: it copies a user's files
into a Glacier vault and deletes the originals, and the way back is a restore that takes hours and
removes the archived copy once it has copied it back. Today the only way to stop people starting
either gesture is to turn off `files`, which removes the whole file browser. This spec gives archive
and restore a flag of their own, `archive`, so an operator who finds a defect in the archive plane
can withdraw both entry points by publishing the flag document, with no app build and without
taking anything else away. It is the argument that earned `asyncFileOperations` its key, applied to
the area where it matters most.

## Scope

### In Scope

- An eighth flag key, `archive`, a **kill switch** (the `asyncFileOperations` kind, not an area):
  default on, added in every place that enumerates a key.
- Off, the Archive and Restore controls leave the file browser and the archive guide leaves Help.
  On, nothing changes.
- Registry rows for those surfaces under `archive`, walked in both states.
- The record: the flag taxonomy, and every place that says archive inherits `files` rather than
  gaining a key, marked superseded.

### Out of Scope

- **A server-side stop.** A flag is presentation, never authorization (identity-and-access Fences):
  the `archive.archive` and `archive.restore` API routes stay live and ungated with the flag off,
  and a hand-built request still enqueues. Every archive and restore the product starts begins at
  one of the controls this spec hides, so hiding them stops the realistic path; stopping the plane
  itself is an operator action on the infrastructure, not a flag.
- **Anything already running, or already open.** Throwing the switch does not stop, cancel or alter
  an execution in flight; it finishes and notifies as it would have. A session that already holds
  the flag document keeps the controls until it next reads the document (FR-004 says when), and a
  dialog already open can still submit.
- **The notifications and their links.** Archive and restore notifications, and their links into
  `/files`, are not gated by `archive` — the record of what happened outlives the surface that
  started it (the notification rule in `gatedSurfaces.ts`), and the destination is the file
  browser, which `archive` does not hide.
- **The receipt folder, `system_settings/archive/`.** It stays listed and stays write-locked; the
  receipts are the user's record of what was archived and hold the ids a later restore needs.
- **Other guides that mention archiving in passing.** The "Rename, move, copy, or delete" guide
  names Archive (`helpContent.ts`, guide `rename-move-copy-delete`) and stays visible with the
  switch off; only the archive guide itself is hidden.
- **Separate archive and restore keys.** One key covers both: they run on one state machine, so a
  defect found in it can affect either direction, and hiding Restore delays data that already takes
  hours to return rather than losing any.
- Any change to the archive or restore dialogs, their copy, or the plane.

---

## Functional Requirements

### FR-001: The `archive` key

#### Description:

`archive` becomes a flag key everywhere the set of keys is written down, defaulting to on, so a
published document can turn it off and an unreadable one leaves it on.

#### Acceptance Criteria:

- [ ] `FeatureFlagKey` (`featureFlags.types.ts`) includes `'archive'`, and `FEATURE_FLAG_KEYS`
      (`featureFlagDefaults.ts`) lists it **last**, after `resultsConversion` — the order rule in
      that file, since `FeatureRoute` offers the first enabled key with a nav row as its fallback.
- [ ] `FEATURE_FLAG_DEFAULTS.archive` is `true`, and `config/feature-flags.json`'s `defaults` block
      carries `"archive": true`; the existing test asserting the two match passes.
- [ ] `scripts/validate_feature_flags.py`'s `FLAG_KEYS` and `lambdas/test_feature_flags_config.py`'s
      restated `FLAG_KEYS` both include `archive`; the validator accepts the updated
      `config/feature-flags.json` (exit 0) and still refuses a document naming an unknown key.
- [ ] `getFeatureFlags` resolves a document with `archive: false` in an environment block to a set
      with `archive: false` and every other key unchanged, and resolves a document that omits
      `archive` everywhere to `archive: true`, the compiled-in default. An UNUSABLE document is a failure from the service
      (`FeatureFlagsUnusable`); it is `useFeatureFlags` that then reports status `'fallback'` with
      `archive: true`, and a test in `useFeatureFlags.test.ts` asserts that value.
- [ ] Every `FeatureFlags` value in the test suites carries `archive`, and **both `tsc -b` and the
      suite** pass. The typed literals (`ALL_ON` and kin) fail `tsc` when a key is missing; the
      untyped ones in `featureFlags.service.test.ts` — `allOn` and the inline `toEqual` objects —
      fail only at runtime, which is why the suite is part of the check.

### FR-002: Off, the archive and restore controls are absent

#### Description:

The file browser offers Archive and Restore only when both `files` and `archive` are on. With
`archive` off the controls are absent — not disabled — in every place they render, and nothing
else in the file browser changes.

#### Acceptance Criteria:

- [ ] With `archive` off and `files` on, none of these five renders appear, each asserted absent by
      accessible name: the `ArchiveButton` in the selection toolbar (`SelectionToolbar.tsx`), in
      the file details panel (`MetadataPanel.tsx`) and in the folder details panel
      (`FolderDetailsPanel.tsx`); the `RestoreArchiveButton` in the primary toolbar and in the
      mobile action bar (both `FileBrowser.tsx`). The toolbar, file-panel and primary-toolbar
      Restore cases are walked by FR-003's rows; the folder panel is asserted in
      `archiveJourney.test.tsx`, and the mobile action bar in `FileBrowser.test.tsx` on its
      existing narrow-window pattern.
- [ ] With `archive` on, each of those controls renders exactly as it does before this spec,
      including the receipt-folder write lock that already withholds Archive inside
      `system_settings/archive/`.
- [ ] With `archive` off, the rest of the selection toolbar is unaffected — asserted by the presence
      of "Copy selected items", "Move selected items", "Delete selected items" and "Send to another
      user" on a one-file selection.
- [ ] With `archive` off, `system_settings/` is still listed at the space root and `archive` is still
      listed inside it.
- [ ] The gate is expressed in `FileBrowser.tsx` beside the existing one: `archiveEnabled` and
      `restoreEnabled` each additionally require `useFeature('archive')`. No archive service, hook
      or dialog reads a flag, and the existing sweep that forbids a `*.service.ts` from importing
      the flags module passes unchanged.

### FR-003: The registry walks it

#### Description:

The surfaces `archive` hides are rows in `GATED_SURFACES`, so the walking test proves each
disappears with the key off and returns with it on. The rows already under `files` stay, because
the `files` gate in `FileBrowser.tsx` stays too — one row per (surface, flag), on the precedent of
`Explore data`, which is registered under both flags that can remove it.

#### Acceptance Criteria:

- [ ] `GATED_SURFACES.archive` holds exactly these four rows, whose names are descriptive rather than
      accessible names, on the precedent of rows like `Shared spaces in the save-results dialog`;
      each recipe queries the control's accessible name:
      - `Archive in the selection toolbar` — control, `/files`
      - `Archive in the details panel` — control, `/files` (the recipe opens the FILE panel)
      - `Restore Archived Data in the file browser` — control, `/files` (the primary toolbar)
      - `Archive and restore guide under the archive switch` — guide, `/help`, `helpId: 'archive-files'`
- [ ] `GatedSurface.name`'s JSDoc says a name is the accessible name where the row is one control
      queried by it, and a description where the recipe queries something inside the surface —
      which is what the registry already does.
- [ ] The four existing `files` rows (`Archive selected items`, `Archive this item`,
      `Restore Archived Data`, `Archive and restore guide`) are unchanged, and their comment no
      longer says archive "inherits this flag rather than gaining one".
- [ ] `gatedSurfaces.test.tsx` has a recipe for each new row, and its contract table carries an
      `archive` entry listing the four names; the walk passes for all four in both states.
- [ ] A standalone test in `help.test.tsx` calls `visibleHelpSections` with only `archive` off and
      asserts the `files` section is present and its guides exclude `archive-files`; with every
      flag on the guide is present (the control).
- [ ] `useVisibleHelpSections`' flag map includes `archive` (the map is total over
      `FeatureFlagKey`, so omitting it is a type error).
- [ ] Mutation: removing the `useFeature('archive')` clause from `FileBrowser.tsx` reddens the
      three control rows' off-half, the folder-panel test and the action-bar test; removing the
      `archive` guide row reddens the standalone Help test. Both reverted.

### FR-004: The record

#### Description:

The places that describe the flag set say there are now two kill switches, the settled claim that
archive inherits `files` is marked superseded where it stands rather than silently rewritten, and
an operator can find how to throw the switch and what it will not do.

#### Acceptance Criteria:

- [ ] Every statement of the flag taxonomy says five areas, **two** kill switches and one
      presentation flag, and names `archive` as the second switch: `featureFlags.types.ts`' JSDoc;
      the `browser.md` entries *The kill switch is a flag key, and it is the sixth* ("Five flags are
      areas; `asyncFileOperations` is a switch") and *A flag can be neither an area nor a kill
      switch*; the `FLAG_KEYS` docstring in `scripts/validate_feature_flags.py`; the count of
      `useFeature` calls in `visibleSections.ts`' JSDoc; the count of places in
      `lambdas/test_feature_flags_config.py`'s docstring, which is already stale and is corrected
      to the real number; and `docs/testing/e2e.md`, which calls `asyncFileOperations` "the odd one
      out — a kill switch".
- [ ] A new entry in `docs/decisions/browser/`, beside *The kill switch is a flag key, and it is
      the sixth*, records why `archive` is a key: the only other off switch was `files: false`;
      one key covers both directions because they share a state machine; the switch is
      presentation-only and leaves the API routes live; notifications and the receipt folder are
      not gated. The entry is listed in the file's contents.
- [ ] The sentence in *The kill switch is a flag key, and it is the sixth* that says "one control
      cannot hold a row under two flags; the choice had to be made rather than hedged" is marked
      superseded in place: the `Explore data` rows already held one surface under two flags, and
      the archive rows now do the same.
- [ ] Every other statement that archive follows `files` alone is rewritten (code) or marked
      superseded in place (docs): `gatedSurfaces.ts` and the contract-table comment in
      `gatedSurfaces.test.tsx`; `docs/specs/ARCS.md` (the archival arc: "inherit the Files flag
      rather than gaining one of their own"); `docs/specs/SPEC-172-*.md` ("it inherits the Files
      flag"); and the archive and restore prop JSDocs that give "the `files` flag is off" as the only
      flag reason, in `FileBrowserDialogs.tsx`, `FolderDetailsPanel.tsx`, `MetadataPanel.tsx` and
      `SelectionToolbar.tsx` (`onRequestArchive`). A closing
      `git grep -niE "inherit.*(files|this) flag|files. flag is off" -- apps docs ':!docs/specs/SPEC-246-*'`
      returns only rewritten or superseded sites, plus `SelectionToolbar.tsx`'s `onRequestSend`
      JSDoc, which is right as it stands: sending follows `files` alone.
- [ ] `apps/portal/info/runtime-configuration.md` gains a short "throwing a switch" paragraph: set
      the key `false` under the environment's block in `config/feature-flags.json`, merge, and
      `deploy-config.yml` publishes it. It says **when it takes effect**: a new session reads it at
      once, but an open session keeps its cached document until it is an hour old
      (`STALE_TIME_MS` in `useFeatureFlags.ts`), and after that only re-reads it when something
      mounts a flag reader — moving to another page, or opening a dialog, drawer or panel that
      reads one, but not opening a folder inside Files — when the network reconnects, or on a
      reload; there is no refetch on window focus and no interval, so a session that sits on one
      screen and opens nothing keeps the controls until one of those happens. (Amended while
      building: this said "at least an hour" and "the next navigation"; a dialog mounting a flag
      reader re-reads a stale document too, and a folder click does not.) A dialog
      already open can still submit. It names what the switch does not do: the API routes stay live, and running
      executions finish.
- [ ] `apps/portal/info/component-inventory/feature-flags-feature.md` names `archive` wherever it
      lists the keys, and its count of places a key is added matches the real number.

### FR-005: Verification

#### Description:

The key reaches production and is read, and the checks the suites cannot run are recorded.

#### Acceptance Criteria:

- [ ] Formatter, both linters, both suites, mypy, `npm run build`, `validate_docs.py` and
      `validate_feature_flags.py` exit 0 locally before the push.
- [ ] After the merge, `deploy-config.yml` and the SPA image deploy are green on the merge commit.
- [ ] Live, signed in: `GET /v1/feature-flags` answers 200 with a document whose `defaults`
      carries `"archive": true` and which `validate_feature_flags.py`'s rules accept — the read
      that tells a resolved document from the all-on fallback, which the UI cannot.
- [ ] Live, signed in, with `archive` on in production: the file browser shows Archive on a
      selection and Restore Archived Data in the toolbar — the switch's default changed nothing.
- [ ] `docs/testing/e2e.md` gains an `archive` sitting beside the `asyncFileOperations` and
      `resultsConversion` ones, on their pattern, and it is run once after the merge: set
      `environments.prod` to `{"archive": false}`, publish, hard-reload; the three Archive controls
      and Restore Archived Data are absent (not disabled), Help's *Files* section keeps "Rename,
      move, copy, or delete" and loses "Archive and restore files", `system_settings/archive/` is
      still listed, and Copy/Move/Delete still work on a file; then set it back to `{}`, publish,
      hard-reload, and everything returns — on the same image tag throughout, which is what proves
      the prod block is read for the new key. The sitting's result is recorded in
      `docs/testing/sessions.md`.

---

## Data Model

```ts
// apps/portal/src/features/feature-flags/featureFlags.types.ts
export type FeatureFlagKey =
  | 'files' | 'query' | 'sharedWorkspaces' | 'dataQuality' | 'dataExplorer'
  | 'asyncFileOperations' | 'resultsConversion' | 'archive';

// apps/portal/src/features/feature-flags/gatedSurfaces.ts — the new list
archive: [
  {name: 'Archive in the selection toolbar', kind: 'control', path: '/files'},
  {name: 'Archive in the details panel', kind: 'control', path: '/files'},
  {name: 'Restore Archived Data in the file browser', kind: 'control', path: '/files'},
  {name: 'Archive and restore guide under the archive switch', kind: 'guide', path: '/help', helpId: 'archive-files'}
]
```

```json
// config/feature-flags.json — defaults gains one key; environments unchanged
{"version": 1, "defaults": {"...": true, "archive": true}, "environments": {"prod": {}}}
```

## File & Folder Structure

```
config/feature-flags.json                                     (edit)
scripts/validate_feature_flags.py                             (edit)
lambdas/test_feature_flags_config.py                          (edit)
apps/portal/src/features/feature-flags/
├── featureFlags.types.ts                                     (edit)
├── featureFlagDefaults.ts                                    (edit)
├── gatedSurfaces.ts                                          (edit)
├── gatedSurfaces.test.tsx                                    (edit)
└── useFeatureFlags.test.ts                                   (edit)
apps/portal/src/features/file-browser/
├── FileBrowser.tsx                                           (edit)
├── FileBrowser.test.tsx                                      (edit)
├── FileBrowserDialogs.tsx, FolderDetailsPanel.tsx, MetadataPanel.tsx, SelectionToolbar.tsx (JSDoc)
apps/portal/src/features/archive/archiveJourney.test.tsx      (edit)
apps/portal/src/features/help/visibleSections.ts              (edit)
apps/portal/src/features/help/help.test.tsx                   (edit)
apps/portal/src/**/*.test.ts(x)                               (edit — FeatureFlags values)
apps/portal/src/test/renderWithProviders.tsx                  (edit — a `featureFlags` option)
apps/portal/info/component-inventory/test-utilities.md        (edit — that option)
apps/portal/info/runtime-configuration.md                     (edit)
apps/portal/info/component-inventory/feature-flags-feature.md (edit)
docs/decisions/browser/                                     (edit)
docs/specs/ARCS.md, docs/specs/SPEC-172-*.md                  (superseded markers)
docs/testing/e2e.md, docs/testing/sessions.md                (the archive sitting)
```

## Implementation Phases

### Phase 1: The key and the gate

- Add the key in every enumerating place (FR-001), then the `FileBrowser.tsx` clause (FR-002).
- Registry rows, recipes, the contract entry, the folder-panel, action-bar and Help tests (FR-003);
  the mutation pair.

### Phase 2: The record and the landing

- The taxonomy, the new register entry and the superseded sites (FR-004).
- Gates, one PR, the post-merge deploy watch and the two live reads (FR-005); completion ritual.
- **Amended while building:** the sitting costs two more PRs and the close a fourth. Publish Config
  can only publish `main`'s document — the deploy role trusts `refs/heads/main` and pull requests
  only — so turning the switch off and back on is a merge each, and the record of what the second
  publish produced can only be written after it merges. The queue lock is held from the first
  sitting PR through the second, so no peer's merge can move the image tag between them.
