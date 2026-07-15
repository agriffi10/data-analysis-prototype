# Spec: Data Quality — Start a Check from the Dashboard (the target picker)

**ID:** SPEC-124
**Status:** Draft
**Last Updated:** 2026-07-14
**Depends On:** SPEC-123 (the `/data-quality` page this action lives on), SPEC-113 (`useDataQualityCheck` — the enqueue path, the reassurance copy, the hidden reports folder), SPEC-109 (the request envelope + `enqueueQualityCheck`), SPEC-039 (`DestinationPicker`), SPEC-055 (the space-selector-over-picker precedent in `SaveResultsDialog`), SPEC-057 (`usableSpaceTargets` — the space→bucket/rootPrefix derivation this reuses), SPEC-052 (`useConnections`), SPEC-095 (responsive), SPEC-045 (a11y), SPEC-106 (error messaging), SPEC-074 (help)

> **Hard sequencing: 109 → 113 → 123 → 124.** None of the arc is built yet — every spec it depends on is `Draft`, there is no `features/data-quality/`, no `useDataQualityCheck`, no `/data-quality` route. This spec is written against those specs' **contracts**, not against shipped code, and cannot start before they ship.
>
> Browser-side only: **no new IAM, no new AWS call, no new Lambda change, no new env var.** The picker lists with the same `ListObjectsV2` the file browser already makes under the user's own role (`fileBrowser.service.ts`), and `SaveResultsDialog` already drives that picker against **both** the user-space and shared-space buckets. It does newly cause the `/data-quality` page to read `VITE_S3_USER_SPACE_BUCKET` and `VITE_S3_SHARED_SPACE_BUCKET` — existing vars, new reader (FR-002).

## Overview

SPEC-123 gives quality checks a home page, but no way to *start* one from it. Today the only entry point is the Files browser: navigate to the data, select it, press **Check data quality**. That is the right entry point when the user is already looking at their files — and the wrong one when they are looking at their check history and want to run another.

This spec adds the second entry point. On `/data-quality`, a **New quality check** action opens a modal that asks the one question the pipeline actually needs answered — **which data?** — by letting the user pick the **space** and then browse to the **parent folder** (or a single file) inside it.

Both entry points converge on the **same** `useDataQualityCheck` hook and the **same** SPEC-109 envelope. There is one enqueue path in the SPA, and this spec does not add a second.

**The one thing that is not free** is the picker. `DestinationPicker` (SPEC-039) already browses folders across the personal space and shared spaces, honours `PICKER_LOCKED_FOLDERS`, and is already composed under a space selector by `SaveResultsDialog` (SPEC-055) — that is the whole modal, reused. But it renders files as **deliberately non-interactive muted rows** (`DestinationPicker.tsx:282-297`), because a move/copy destination is never a file. A quality check *can* target a single file (SPEC-113 FR-001 allows it from Files, and dropping it here would make the two entry points quietly unequal), so the picker gains an **opt-in** selectable-files mode. Opt-in is the requirement, not a nicety: three shipped callers (`MoveDialog`, `CopyDialog`, `SaveResultsDialog` — verified, they are the only ones) depend on files being unselectable, and a default-on change would silently make a file a valid paste target.

## Amends (declare it here, or it happens by accident)

- **SPEC-113 — `useDataQualityCheck`'s contract.** `start` currently returns `Promise<void>` and always toasts. This spec needs an **outcome** (to close the dialog and raise FR-005's banner only on success) and needs the toast **suppressible** (FR-005's banner is the dashboard's receipt; a toast *and* a banner is two receipts for one action). New contract in **API / Interface Contract** below. The Files-browser caller is unchanged in behaviour.
- **SPEC-123 FR-005** — the empty-state body copy, which today sends the user to the Files browser (FR-001).
- **SPEC-039 — `DestinationPicker`'s props.** Four additive, opt-in props (FR-003); the three existing callers are not modified.

## Scope

### In Scope

- A **"New quality check"** action in the `/data-quality` page header, and a matching call-to-action **inside the empty state**.
- A **`StartQualityCheckDialog`**: space selector (personal + the user's *usable* shared spaces) → `DestinationPicker` → confirm, targeting **one folder or one file**.
- An **opt-in `selectableFiles` mode** on `DestinationPicker` (+ the three props that make it usable), with the existing three callers unchanged.
- Enqueue through the **existing** `useDataQualityCheck` (SPEC-113 FR-001), amended per **Amends** above.
- The **post-enqueue honesty banner** (FR-005): a check that has just started is *not* in the list, and the page must say so rather than look broken.
- **One SPEC-106 conformance fix**: the picker's listing-error line renders raw `Error.message` today (`DestinationPicker.tsx:226-232` ← `useFileBrowser.ts:73`). Routing it through `toUserMessage` is a two-line change, in scope here because this spec puts that error path in front of the user in a new place — and it fixes Move/Copy/Save results at the same time.
- **Responsive** (SPEC-095), **a11y** (SPEC-045), **error wording** (SPEC-106), **help content** (SPEC-074).

### Out of Scope

- **A pending/in-progress row on the dashboard.** The arc persists **nothing** until `assemble-report` writes the index entry (SPEC-123 FR-001), so a "running…" row would need a new store of in-flight requests. Deliberately not built; FR-005 makes the gap explicit to the user instead of papering over it.
- **A second enqueue path.** The dialog calls `useDataQualityCheck`. If this spec ends up importing `enqueueQualityCheck` directly, it has gone wrong.
- **Multi-select.** One folder **or** one file per request — the same v1 limit as SPEC-113 FR-001.
- **A client-side format pre-check.** An `.xlsx` selection enqueues and is rejected by the pipeline as `unsupported_format`, arriving as a notification minutes later (SPEC-113 FR-001). Restated because the picker now *shows* the user every file, which makes it look like the dialog is vetting them. It is not.
- **Search / filter / deep pagination in the picker.** The picker lists a page at a time behind "Load more" (`LISTING_PAGE_SIZE`, `DestinationPicker.tsx:299-308`). Finding **one file** in a folder of hundreds means clicking "Load more". Accepted as a v1 limit — the **folder** target is the common case (it is what the modal asks for), and the Files browser remains the entry point when the user needs to hunt for a specific file.
- **Free-text path entry.** A typed prefix turns every typo into a background failure the user learns about minutes later, by notification.
- **A new shared component.** The dialog is `Modal` + `<select>` + `DestinationPicker`, the `SaveResultsDialog` composition.
- Changing the Files-browser entry point (SPEC-113 FR-001) in any way.

---

## Functional Requirements

### FR-001: The action on the dashboard

#### Acceptance Criteria:

- [ ] The `/data-quality` page (SPEC-123 FR-002) carries a **primary** `Button` — **"New quality check"** — in `PageLayout`'s `actions`, alongside the existing filter and refresh controls, under `stackActionsOnMobile` (`PageLayout.tsx:22`) so the header wraps rather than overflows on a phone.
- [ ] The action opens `StartQualityCheckDialog` (FR-002). It renders whether the list is populated, empty, filtered-empty, loading, or in its **error** state — **starting a check never depends on the history being readable**. A test asserts the button renders while `useDataQualityRuns` is in its error state.
- [ ] The **empty state** (SPEC-123 FR-005) gains the same action as a call-to-action button, and **this spec amends SPEC-123 FR-005's body copy**: it no longer tells the user to go to the Files browser, it offers to start a check right there. Files remains a valid entry point and the help content (FR-007) still says so — the empty state simply stops sending the user away from the page that can now do the job.
- [ ] The report view's **"Re-run check"** (SPEC-113 FR-006) is untouched: it re-enqueues a *known* target and never opens this dialog.

### FR-002: The dialog — pick a space, then a target

#### Description

The modal answers one question — *which data?* — in the order a user thinks about it: which space, then where in it. It is the `SaveResultsDialog` composition (`SaveResultsDialog.tsx:82-121`) with the filename field removed and the picker's confirm repurposed.

#### Acceptance Criteria:

- [ ] `StartQualityCheckDialog` renders inside `Modal` (`ariaLabel="Start a quality check"`, `dismissible={!isPending}`), with a heading, a one-line body, the space selector, the picker, the target line (FR-003), and the picker's confirm/cancel footer.
- [ ] The body carries SPEC-113 FR-002's reassurance — the check **reads the files and changes nothing** and runs **in the background**, with a notification on completion. Same promise, same words; **referenced, not re-legislated**.
- [ ] **Spaces are derived by reusing `usableSpaceTargets` (`file-browser/useFileSpace.ts`)** — the existing `Connection[] → {id, bucket, rootPrefix, kind, label}` derivation, already filtered by `isConnectionUsable` (`query.types.ts`: personal, or shared with `status === 'active'`). It is **not** re-derived: `useConnections` carries **no bucket and no rootPrefix**, those come from `VITE_S3_USER_SPACE_BUCKET` / `VITE_S3_SHARED_SPACE_BUCKET` + the username, and there are already two derivations of this in the codebase (`QueryWorkspace`, `useFileSpace`). A third would be the one that drifts. A comment records this.
- [ ] The selector lists **personal first, then shared A–Z**, and renders as a `<select>` **only when there is more than one space** (`SaveResultsDialog.tsx:82`); with one space it is omitted and the picker is rooted at the personal space.
- [ ] A shared space that is **not usable** (`isConnectionUsable` false — provisioning, failed, leaving) is **not offered**. A test asserts a provisioning space is absent from the selector. (This is space *provisioning* status, **not** SPEC-073's per-member Pending/Active join chip — a Pending **member** of an active space is authorized, SPEC-109 FR-005, and must be offered.)
- [ ] **Zero usable spaces** (the bucket env var is unset — the only way this happens, since a personal space always exists) renders the dialog `null` and the **action absent**, with the SPEC-106 "contact the Administrator" path — never an open modal with an empty picker.
- [ ] Changing the space **remounts the picker** (`key={space.id}`, `SaveResultsDialog.tsx:108`), so the breadcrumb, the browse prefix, and any file selection reset to that space's root. A test asserts a file selected in space A does not survive a switch to space B.
- [ ] The picker is rooted at the space root (`rootPrefix` = the space's navigation floor) and cannot climb above it, so a target can never escape the chosen space.
- [ ] `_data-quality-reports`, `athenaresults/`, and `user_settings/` are **not navigable** — `PICKER_LOCKED_FOLDERS` already carries the latter two (`protectedFolders.ts:14`, root-only match) and SPEC-113 FR-004 adds the first. A test asserts none of the three is offered. A comment records the dependency: **SPEC-113 FR-004 is what makes the reports folder unpickable here**, so this dialog must not ship before it.

### FR-003: The target — one folder, or one file

#### Description

`DestinationPicker` gains an **opt-in** selectable-files mode. Every part of the change is shaped by the fact that three shipped callers rely on the current behaviour — and by the fact that the picker today owns its browse state **privately** (`browsePrefix`, `DestinationPicker.tsx:114`) and takes a **static** `confirmLabel` (`:27`). Neither the label nor the target line FR-003 requires can be produced without lifting the target out, so this FR pins **who owns what**: the picker owns the state, the caller is *told* the target.

#### Acceptance Criteria:

- [ ] `DestinationPicker` gains four **additive, opt-in** props:
  - **`selectableFiles?: boolean`** (default `false`),
  - **`onTargetChange?: (target: {prefix: string; fileKey?: string}) => void`** — fired on mount and on **every** navigation and selection change,
  - **`markerKey?: string`** — *already exists*; it becomes **required whenever `selectableFiles` is true** (see below),
  - **`listLabel?: string`** (default `"Destination folders"`) — the list's `aria-label` (`:236`), which is wrong in a mode where files are selectable and nothing is a "destination".
- [ ] `onConfirm` gains an **optional third argument**: `onConfirm(destPrefix, destBucket, selectedFileKey?)`. Existing callers ignore it and are **not modified**. A comment records that this is why the argument is appended rather than the signature reshaped.
- [ ] When `selectableFiles` is `false`, file rows render exactly as today — `aria-disabled`, muted, non-interactive (`:282-297`). **A test asserts Move, Copy, and Save results are unaffected.** A comment records why the flag is opt-in: a file is never a valid move/copy/save destination, and a default-on change would silently make it one.
- [ ] When `selectableFiles` is `true`, each file row is a **`button`** with `aria-pressed`, an accessible name of **"Select file *X*"** (parity with the existing `"Open folder X"`, `:267`), and a selected treatment of `bg-accent-soft` — the `SpacesList.tsx` precedent, since the picker has **no** selected-row style of its own today.
- [ ] **`markerKey` is required when `selectableFiles` is true.** Without it, `useFileBrowser` does not filter the space's `DO_NOT_DELETE.txt` prefix marker (`useFileBrowser.ts`, `fileBrowser.constants.ts`), which would appear at **every space root as a selectable target** — enqueuing a check that fails minutes later as `unsupported_format`. Harmless for Move/Copy/Save (files are inert there), fatal here. A test asserts the marker is absent from a selectable listing.
- [ ] Selection is **single-target and mutually exclusive with the folder**: selecting a file makes the file the target; selecting nothing makes the **currently browsed folder** the target. Clicking a selected file again **deselects** it, returning the target to the browsed folder. A test asserts each transition.
- [ ] **Navigating clears any file selection** — descending into a folder, the `..` row, or a breadcrumb. A comment records why: the target must always be the thing the confirm button says it is, and a selection surviving a navigation would silently enqueue a check on a file the user is no longer looking at.
- [ ] Confirm is **disabled when the browsed folder is empty** (no subfolders and no files) with the reason stated inline — the one invalid target the picker can detect for free. Everything deeper (format, readability) stays server-side and arrives by notification.
- [ ] The dialog passes the picker's **required-but-unmentioned-in-v1-drafts** props explicitly: `items={[]}`, `currentPrefix={space.rootPrefix}`, **`allowCurrentParent`** (without it, `currentParentBlocked` disables confirm **at the space root** — `:140-147` — and the root target is dead on arrival), `busyLabel="Starting…"`, plus `markerKey` and `listLabel`.
- [ ] The **confirm label names the target** — **"Check this folder"** / **"Check this file"** — computed by the dialog from `onTargetChange` and passed as the existing `confirmLabel` prop. Never a generic "OK": the user is one click from a background job.
- [ ] The **target line** — the resolved location in `font-mono`, truncated from the left so the leaf stays visible — is rendered **by the dialog** (not the picker, so the three existing callers are untouched) above the confirm row, and updates on every navigation and selection. A test asserts the enqueued `location` equals the location the dialog last displayed.
- [ ] The folder target is a **prefix ending in `/`**; the file target is a **full object key**. Both are passed as `location` unchanged — the SPA does not reinterpret the shape SPEC-109 FR-001 defined.
- [ ] The picker's **listing-error** line routes through `toUserMessage` (SPEC-106) instead of rendering the raw `Error.message` from `listFiles`. A test asserts an `AccessDenied` (a shared space whose membership was revoked but is still in the cache) renders friendly text, not raw AWS text.

### FR-004: Enqueue — one path, not two

#### Acceptance Criteria:

- [ ] Confirming calls **`useDataQualityCheck().start(...)`** (SPEC-113 FR-001) — the same hook the Files-browser action calls. The dialog does **not** import `enqueueQualityCheck`, does **not** mint a `requestId`, and does **not** build an envelope. A test asserts the hook is the only enqueue seam.
- [ ] `space` is the `DataQualitySpace` (`{kind, bucket, prefix}`, SPEC-109) derived from the selected target space — `kind: 'personal'` for the user's own space, `'shared'` otherwise.
- [ ] `start` **resolves to an outcome** (see **Amends** / the contract below). The dialog closes **only on success**; on failure it **stays open with the target intact**, so the user does not lose their selection to an error they cannot fix.
- [ ] The confirm button is **disabled while the request is in flight** and the modal is **not dismissible** while it is (no double-enqueue, no orphaned send).
- [ ] Success does **not** navigate and does **not** refetch the list — the run is not in the index yet, and a refetch would re-render the same rows (misleading motion).
- [ ] Failure wording is the hook's, via `toUserMessage` (SPEC-106) — including the missing-`VITE_DATA_QUALITY_QUEUE_URL` path (SPEC-113 FR-003). **Referenced, not restated**: that behaviour lives inside the hook and the dialog cannot implement it differently.

### FR-005: What happens next — say it, don't hide it

#### Description

The user starts a check and is returned to a list that **does not contain it**, and will not for minutes: the dashboard lists completed checks only (SPEC-123). Without this FR, the most common first impression of the feature is *"I pressed the button and nothing happened."*

#### Acceptance Criteria:

- [ ] After a successful enqueue **from the dashboard**, the page renders a dismissible **`Banner variant="info"`** above the list: the check has started, it runs in the background, and it will **appear here when it finishes** — the user will also be notified. A test asserts it appears on success and not on failure.
- [ ] The dashboard enqueue **suppresses the hook's toast** (`start(target, {toast: false})`, per **Amends**) — the banner is the receipt, and it says strictly more than the toast does. **One action, one confirmation.** The Files-browser entry point keeps the toast (it has no list to explain).
- [ ] The banner does not persist across a reload — it is a receipt for an action just taken, not a state of the world.
- [ ] The banner **never claims a result**. It says the check has started; it does not say it will pass.
- [ ] SPEC-123 FR-006's footer line (completed checks only; failures live in notifications) is the **standing** explanation and the banner is the **momentary** one. A comment records that the two together are what keep a completed-only list honest.

### FR-006: Responsive + accessible

#### Acceptance Criteria:

- [ ] The dialog uses `Modal`'s small-screen presentation (viewport-capped, scroll-in-panel, SPEC-095); the picker keeps its own `max-h-64` scroll region and the page behind the modal never scrolls.
- [ ] The header action wraps under `stackActionsOnMobile`; the page **never scrolls horizontally** at the mobile breakpoint.
- [ ] One component tree with responsive utilities — **no `*Mobile`/`*Desktop` twin** (`best-practices/react.md` §20).
- [ ] **Initial focus is explicit**: `Modal` sets `initialFocus: false` and defers to the consumer (`Modal.tsx:40-50`), and this dialog has **no text field** to inherit it (the `SaveResultsDialog` precedent focuses its filename input, which does not exist here). Focus goes to the **space `<select>`** when it is rendered, otherwise to the dialog panel. A test asserts it.
- [ ] The space `<select>` has a visible `<label>`; the picker list uses the caller-supplied `listLabel` (FR-003); selectable file rows expose `aria-pressed`; the confirm button's accessible name names the target.
- [ ] Focus is trapped (`focus-trap-react` via `Modal`), `Escape` dismisses when not busy, and focus returns to the **"New quality check"** trigger on close.
- [ ] A co-located `StartQualityCheckDialog.a11y.test.tsx` uses `expectNoA11yViolations` with **`COMPONENT_AXE_OPTIONS`** (`src/test/axe.ts`), re-run at `window.innerWidth = 400`. `DataQualityPage.a11y.test.tsx` (SPEC-123) is extended to render with the dialog open and stays clean.

### FR-007: Help content

#### Acceptance Criteria:

- [ ] The SPEC-074 data-quality guide (authored by SPEC-113) documents **both** entry points: from the Files browser with a file or folder selected, and from **Data quality → New quality check**, where you choose the space and browse to the folder or file.
- [ ] It states that a check that has just started is **not yet in the list**, that completed checks appear there, and that failures arrive as notifications — matching FR-005 and SPEC-123 FR-006. Document only what is shipped and wired end to end (SPEC-074 FR-005).

---

## Data Model

No new persisted shape. The dialog produces the **existing** SPEC-109 target.

```ts
// apps/portal/src/features/data-quality/dataQuality.types.ts  (existing — SPEC-109/113)
// { space: DataQualitySpace, location: string }
// `location` = a prefix ending in "/" (folder target) or a full object key (file target).
```

```ts
// apps/portal/src/features/file-browser/DestinationPicker.tsx  (extended — FR-003)
type Props = {
  // …unchanged…
  /** Opt-in: render file rows as selectable. Default false — a file is never a valid
      move/copy/save destination, and defaulting this on would silently make it one. */
  selectableFiles?: boolean;
  /** Fired on mount and on every navigation/selection so the caller can render the
      target and compute the confirm label. The picker keeps owning the state. */
  onTargetChange?: (target: {prefix: string; fileKey?: string}) => void;
  /** aria-label for the list. Default "Destination folders" — wrong when files are selectable. */
  listLabel?: string;
  /** Existing prop; REQUIRED when selectableFiles is true, or DO_NOT_DELETE.txt becomes a target. */
  markerKey?: string;
  /** `selectedFileKey` is present only when selectableFiles and a file row is selected. */
  onConfirm: (destPrefix: string, destBucket: string, selectedFileKey?: string) => void;
};
```

## API / Interface Contract

```ts
// apps/portal/src/features/data-quality/useDataQualityCheck.ts  (AMENDS SPEC-113 FR-001)
// `start` must resolve to an outcome: the dashboard closes its dialog and raises its banner
// only on success, and a Promise<void> that never rejects cannot say whether it succeeded.
// `toast` is suppressible so the dashboard's banner (which says strictly more) is the single
// confirmation for a single action.
export function useDataQualityCheck(): {
  start: (
    target: {space: DataQualitySpace; location: string},
    opts?: {toast?: boolean}          // default true — the Files-browser behaviour, unchanged
  ) => Promise<boolean>;              // true = enqueued; false = failed (already surfaced via toUserMessage)
  isPending: boolean;
};

// apps/portal/src/features/data-quality/StartQualityCheckDialog.tsx
export function StartQualityCheckDialog(props: {
  /** From `usableSpaceTargets` (SPEC-057) — personal first, usable shared A–Z. Empty ⇒ renders null. */
  spaces: FileSpaceTarget[];
  isPending?: boolean;
  /** `location` is a folder prefix ("…/") or a full object key. */
  onStart: (target: {space: DataQualitySpace; location: string}) => void;
  onCancel: () => void;
}): JSX.Element | null;
```

## File & Folder Structure

```
apps/portal/src/features/data-quality/
├── StartQualityCheckDialog.tsx           (+ test, + a11y test)
├── useDataQualityCheck.ts                # amended: Promise<boolean> + opts.toast
├── DataQualityPage.tsx                   # + header action, empty-state CTA, the FR-005 banner
└── index.ts                              # + the dialog export
apps/portal/src/features/file-browser/DestinationPicker.tsx      # + selectableFiles/onTargetChange/listLabel (FR-003)
apps/portal/src/features/file-browser/DestinationPicker.test.tsx # + the three-caller regression test
apps/portal/src/features/file-browser/useFileBrowser.ts          # listing error via toUserMessage (SPEC-106 fix)
apps/portal/src/features/help/helpContent.ts                     # both entry points (FR-007)
```

## Implementation Phases

### Phase 1: The picker's selectable-files mode

- `selectableFiles` (default off), `onTargetChange`, `listLabel`, the required `markerKey`, the selected-file state, the clear-on-navigate rule, the empty-folder confirm guard, the appended `onConfirm` argument, and the `toUserMessage` listing-error fix.
- **Tests: default mode renders files non-interactive (Move / Copy / Save results unaffected); select → deselect → navigate-clears; `DO_NOT_DELETE.txt` absent; confirm disabled in an empty folder; the confirm callback carries the file key only when a file is selected.**

### Phase 2: The dialog

- The `useDataQualityCheck` amendment (`Promise<boolean>`, `opts.toast`) and its test.
- The modal: `usableSpaceTargets`-derived spaces, the selector, the keyed picker with its full prop set (`allowCurrentParent`!), the live target line, the dynamic confirm label, the in-flight lock, the zero-spaces `null`.
- Tests including the enqueued `location` matching the displayed target, and the single-space no-selector case.

### Phase 3: The page, responsive, completion ritual

- The header action, the empty-state CTA (amending SPEC-123 FR-005's copy), the FR-005 banner (and the suppressed toast).
- All three breakpoints; `*.a11y.test.tsx` at 400px; the SPEC-123 page a11y test extended with the dialog open.
- Help & guides (FR-007), delivery doc, INDEX status, component-inventory rows (`StartQualityCheckDialog`; the `DestinationPicker` row gains the `selectableFiles` note).
