---
type: Spec
id: SPEC-113
title: "Data Quality — File-Browser UI + the Report View"
description: "Adds a Check data quality action to the file browser with a confirm dialog and toast, hides the reports folder, and provides the report view users open to read a check's findings."
spec_status: Completed
depends_on: [SPEC-109, SPEC-112, SPEC-058, SPEC-095, SPEC-045, SPEC-106, SPEC-074, SPEC-120]
arc: data-quality
arc_order: 6
---

**Dependency notes:** SPEC-109 (enqueue service + contract), SPEC-112 (the pipeline actually produces a report), SPEC-058 (the notifications pipeline FR-008 amends), SPEC-095 (responsive foundation), SPEC-045 (a11y), SPEC-106 (error messaging), SPEC-074 (help content), SPEC-120 (**optional** — FR-006 only)
> **Read `docs/data-quality-architecture.md` §1 and §6 first.** Presentation + enqueue only — no new AWS calls beyond the SPEC-109 service and a read of the report object — plus **one contract change to the shipped notifications pipeline (FR-008)**. This spec is browser-side only and has **no `cpcommon` dependency**, which is why SPEC-107 is deliberately absent from Depends On.

## Overview

Surface the feature, and — critically — **make the report readable**.

From the Files browser, with a file or folder selected, the user presses **"Check data quality"**, confirms in a small dialog, and gets a transient toast while the async pipeline runs. The durable outcome arrives as a notification (SPEC-114) that **deep-links into a report view**.

**That view is in scope, not a follow-up.** The report is the arc's only durable artefact. The report folder must be hidden from the file browser (the `_`-prefix convention is a Lambda-side convention the SPA never learned — `fileBrowser.service.ts:81-99` filters nothing, and `protectedFolders.ts:11` hides only `user_settings`), and hiding it *without* providing a viewer would produce a file the user is told about and cannot open. Six specs of infrastructure delivering nothing readable is not a shippable outcome.

## Scope

### In Scope

- A **"Check data quality"** action in the Files browser, on a selected file **or** folder, in personal and shared spaces.
- A confirmation dialog naming the target and stating that the check is **read-only** and runs in the background.
- Enqueue via `enqueueQualityCheck` (SPEC-109); pending state + transient toast; failures via `toUserMessage` (SPEC-106).
- **Hide `_data-quality-reports`** in the file browser (`HIDDEN_BROWSER_FOLDERS`) **and** lock it out of the move/copy picker (`PICKER_LOCKED_FOLDERS`).
- A **read-only report view** at **`/data-quality/:space/:requestId`**, which fetches and renders the report JSON: the verdict, the exact findings, the approximate findings **clearly marked as such**, and the cross-file column disagreements.
- The view's **follow-through actions** (FR-006) — Convert to Parquet, Re-run check, Open folder — which are what make it a destination rather than a dead end.
- The **screen design** (FR-007), built entirely from primitives that already exist.
- The **notification link field** (FR-008) — without it, the deep link SPEC-114 requires cannot exist and the page is unreachable.
- **Responsive** per SPEC-095; **a11y** per SPEC-045; **error wording** per SPEC-106; **help content** per SPEC-074.

### Out of Scope

- Polling for completion. The notification is the completion channel (SPEC-114); no new background poll.
- Charts or visualizations of the findings. The view is a readable, accessible rendering of the JSON — tables and text.
- Per-finding actions (a "fix this column" button on an individual row). The page's follow-through is at the **page** level (FR-006), not the finding level.
- Any **new shared component**. Everything on the page is an existing primitive (FR-007). A new `EmptyState` or `Table` component would be scope creep — the codebase deliberately has neither.
- Multi-select — one file or one folder per request in v1.
- The notification's **content** — SPEC-114. (Its **delivery mechanism** — the link field — is FR-008 here, because without it SPEC-114 cannot be built.)

---

## Amendments (2026-07-21, at implementation)

Five corrections, each made after reading the code this spec was written against. They are
recorded here rather than silently applied because four of them contradict what the spec
originally said.

1. **The action lives in the file browser's `SelectionToolbar`, not the `MobileActionBar`**
   (FR-009 amended). It is a **selection**-scoped action — the same scope as Copy/Move/Delete,
   which is exactly what that toolbar holds — whereas the `MobileActionBar` holds
   **folder**-scoped actions (New folder, Upload). `SelectionToolbar` already renders at every
   breakpoint with the labelled-at-`tablet:`/icon-only-on-mobile idiom
   (`FileBrowser.tsx:405-437`), so this delivers FR-009's actual requirement — one component
   tree, no `*Mobile`/`*Desktop` twin, reachable on a phone — more faithfully than its letter
   did. Precedent that not every action belongs in the `MobileActionBar`: `CreateTableButton`
   is mount-gated to `!isMobile` and has no mobile presence at all (`FileBrowser.tsx:663`).

2. **The Data Model is re-derived from `dqcommon/report.py`, which is shipped** (SPEC-112).
   The original Data Model predates it and disagrees with it in four places — see the
   corrections called out inline below. The rule the spec already states stands: the SPA
   mirrors the report byte-for-byte and does not reinterpret it. Where the two disagreed, the
   Lambda won.

3. **`start` toasts on failure as well as success, and the dialog closes either way**
   (FR-002/FR-003 clarified). The confirm dialog has nothing to re-enter, so keeping it open
   on failure — the table-builder pattern, where a form's inputs are worth preserving — would
   strand the user on a dialog whose only remaining move is Cancel. It also keeps the stated
   `Promise<void>` contract honest for FR-006's **"Re-run check"**, which calls the same hook
   with no dialog mounted at all and for which a toast is the *only* feedback channel.

4. **FR-006 ships with two actions, not three.** SPEC-120 is still `Draft`, so per FR-006's own
   conditional the "Convert to Parquet" button **and its import** are absent from the codebase.
   Re-run check and Open folder both keep default visual weight; the primary slot stays empty
   rather than being promoted, so that adding SPEC-120's button later is a pure addition.

5. **The verdict banner warns on `hasIncompleteFigures`, not `hasApproximateFigures`**
   (FR-007 amended). The latter is **true on every report the arc can produce**, so the
   qualifier FR-007 originally attached to it would fire on a perfectly clean CSV — a warning
   that never varies is one users learn to ignore, and it would undercut the exact/approximate
   distinction this whole view exists to communicate. The soft "some figures are estimates"
   line stays on `hasApproximateFigures`; the warning moves to the flag that varies.

---

## Functional Requirements

### FR-001: The action

#### Acceptance Criteria:

- [ ] "Check data quality" is available on exactly one selected file or one selected folder, in a personal space and in a shared space the user belongs to.
- [ ] It is **not** offered on the `..` parent row (SPEC-098), on `user_settings`, on `_data-quality-reports`, on an empty selection, or on a multi-select.
- [ ] Selecting an `.xlsx` file and running the check enqueues normally; the **pipeline** rejects it as a plain `unsupported_format` (no convert-first guidance — Excel is unsupported everywhere, SPEC-110 FR-002), and that failure arrives as a **SPEC-114 notification minutes later**, not as a synchronous SPA error. There is no client-side extension pre-check in v1 — stated so nobody expects the dialog to catch it.

### FR-002: The dialog

#### Acceptance Criteria:

- [ ] The dialog names the exact target and states plainly that the check **reads the files and changes nothing**.
- [ ] It states that the check runs in the background and the user will be notified when it finishes.
- [ ] Confirming enqueues via `enqueueQualityCheck` and closes the dialog; cancelling does nothing.
- [ ] **The dialog closes on failure too** (amendment 3), with the failure delivered as a danger
      toast (FR-003). It has nothing to re-enter, so holding it open would leave the user on a
      dialog whose only remaining move is Cancel.
- [ ] The confirm button is disabled while the request is in flight (no double-enqueue).

### FR-003: Feedback and errors

#### Acceptance Criteria:

- [ ] A successful enqueue raises a transient toast confirming the check has started. The browser does **not** block or wait.
- [ ] Every failure is rendered via `toUserMessage` (SPEC-106) — never `error.message`, never raw AWS/SQS text — as a **danger toast**, which is the only channel FR-006's dialog-less "Re-run check" has.
- [ ] A missing `VITE_DATA_QUALITY_QUEUE_URL` produces the friendly "contact the Administrator" path, not a crash.

### FR-004: Hide the reports folder — and lock it in the picker

#### Acceptance Criteria:

- [ ] `_data-quality-reports` is added to `HIDDEN_BROWSER_FOLDERS` (`apps/portal/src/features/file-browser/protectedFolders.ts`) so it does not appear in the Files listing. A test asserts it is absent from a listing that contains it.
- [ ] It is also added to `PICKER_LOCKED_FOLDERS`, so it cannot be chosen as a move/copy destination. (`athenaresults/` is already locked this way; a hidden folder that is still a valid paste target is a trap.)
- [ ] A comment records why both are needed: the `_`-prefix convention is Lambda-side only, and the SPA has no such filter.

### FR-005: The report view

#### Acceptance Criteria:

- [ ] The route is **`/data-quality/:space/:requestId`** and it renders a read-only view of `{space}/_data-quality-reports/{requestId}/report.json`. `:space` is the space name — the **username** for a personal space, the **shared-space name** for a shared one — from which the view resolves the kind and the bucket (personal ⇒ the user-space bucket; a name matching one of the user's shared spaces ⇒ the shared-space bucket).
- [ ] **Resolution precedence:** the actor's **own username always resolves personal**; shared-space names are checked **only when the segment ≠ the username**. (SPEC-114's link builder pins the same rule from the producer side.)
- [ ] A comment records why the space is **in the route and not derived**: the report lives at `{space}/_data-quality-reports/{requestId}/report.json`, and `requestId` alone **does not say which space** — so a `/data-quality/:requestId` route could not locate a shared-space report **at all**, and the notification's deep link (SPEC-114 FR-001) would land on a permanent "not found." A test opens a shared-space report by URL and asserts it renders.
- [ ] A `:space` the user has no access to (not their username, not one of their shared spaces) renders the friendly empty/denied state — it never probes S3 on a guess and never leaks whether the space exists.
- [ ] It shows: the verdict, the source location and file count, the **exact** findings (row count, duplicate rows, per-column type consistency with the offending-value samples, null/blank ratios), the **cross-file column disagreements**, and the **approximate** findings.
- [ ] Approximate figures are **visually and textually distinguished** from exact ones, each carrying the reason it is approximate — the ragged-row count says **both** that quoted commas and that newlines inside quoted fields may over-count it (SPEC-112 FR-003); the encoding figure says what percentage of bytes was examined. A test asserts an approximate figure never renders without its qualifier.
- [ ] A **`skipped`** figure and a **`not_computed`** figure each render with their reason and are **never** styled as a clean pass. That covers **every** `skipped` variant SPEC-112 defines: type consistency on Parquet, **encoding on Parquet** ("binary format — encoding is defined by the file format"), **encoding on `.gz`** ("compressed source — raw bytes are DEFLATE output"), and **ragged rows on non-CSV** — plus `not_computed` ragged/duplicates figures. A test asserts a Parquet report shows no green type-consistency result it did not earn.
- [ ] A report that cannot be fetched (deleted, wrong space, not yet written) renders a friendly empty state via `toUserMessage`, not a crash or a raw 404.
- [ ] **No new IAM** — the user's own role's existing space-read grants (personal prefix / membership tag) already cover the report key; the implementation plan confirms it.
- [ ] The view is read-only — no controls that mutate anything.

### FR-006: The report view is a FOLLOW-THROUGH page, not a dead end

#### Description

A user who reads "412 values in `amount` aren't numbers" needs somewhere to go next. A report that only reports is a dead end. This FR is what makes the page the **artifact users are sent to**, rather than a JSON dump with a nicer font.

#### Acceptance Criteria:

- [ ] The page header carries three actions, in this order of visual weight: **"Convert to Parquet"** (primary), **"Re-run check"** (default), **"Open folder"** (default). **As shipped it carries two** — SPEC-120 is `Draft`, so per the conditional two criteria below the primary is absent (amendment 4). The primary slot stays *empty* rather than promoting Re-run check into it, so SPEC-120's integration is a pure addition and no button silently changes weight underneath the user.
- [ ] **"Convert to Parquet"** opens SPEC-120's `ConvertToParquetDialog` prefilled with this report's source folder. It is the **fix** for a CSV or JSON source the user wants as typed Parquet — most of what this page reports (stray types, ragged rows, encoding) — so it earns the primary slot. A comment records that this is the one action that changes the data, which is why the rest of the page is read-only and this button is unmistakably the exception.
- [ ] **This integration is conditional on SPEC-120 having shipped.** If it has not, the button **and its import are absent from the codebase entirely** — the integration is added when SPEC-120 lands (hence "SPEC-120 (optional — FR-006 only)" in Depends On). Once integrated, an unset `VITE_FILE_CONVERTER_QUEUE_URL` still renders the button **absent**, not disabled-and-broken. A test asserts it.
- [ ] **"Re-run check"** re-enqueues the same check via `useDataQualityCheck` (FR-001), toasts, and does **not** navigate away — the current report stays on screen until the new one arrives by notification.
- [ ] **"Open folder"** navigates to the Files browser at the report's source location (`/files?space=…&prefix=…`).
- [ ] Actions are rendered through `PageLayout`'s `actions` prop with **`stackActionsOnMobile`**, so they wrap on mobile rather than overflowing — the same pattern `NotificationsPage.tsx:75` and `ConnectionsPage.tsx:240` already use.

### FR-007: Screen design

#### Description

The page is built from primitives that already exist. **No new shared component is introduced.** Anything below that looks like a new component is an existing one being reused — a comment should say which.

#### Acceptance Criteria:

- [ ] The page uses **`PageLayout`** (title "Data quality report", subtitle = the source location in `font-mono`, `contentClassName="max-w-[920px] gap-4"`, `stackActionsOnMobile`) — so it is the `<main id="main">` landmark and the skip-link target for free. Route wrapper is a thin `routes/DataQualityReportPage.tsx` re-export, per the Notifications convention.
- [ ] **Verdict banner** at the top: the existing **`Banner`** — `variant="success"` for `clean`, `variant="warning"` for `issues_found`.
- [ ] **The banner's two qualifiers key off two different flags** (amendment 5). `hasApproximateFigures` is **true on every report this arc can produce** — `report.py::_has_approximate` documents that ragged and encoding are filed under `approximate` whenever computed and under `skipped` when not, so neither has an exact branch — which makes it useless as a *warning* trigger: it would fire on every clean CSV and users would learn to ignore it. So the banner qualifies **softly and always** on `hasApproximateFigures` ("some figures are estimates — see the notes below"), and **warns** only on **`hasIncompleteFigures`**, the flag that actually varies ("some checks couldn't be completed"). This is the same split SPEC-114 was told to use for the notification body; the two surfaces must not disagree about what a report means.
- [ ] **Summary tiles**: four metric tiles (rows, files, duplicate rows, columns with issues) in a `grid` — 4 columns at `tablet:`/`desktop:`, **2×2 on mobile**. Tiles are `bg-surface-2 rounded-md` with a `text-xs text-text-2` label above a larger value; a value that represents a problem uses `text-danger`.
- [ ] **"What to look at first"** — the top-issues list (SPEC-112 FR-003, capped at 5), each as a bordered finding row carrying an icon, a one-line headline naming the file and/or column, a supporting line explaining *why it matters*, and a **status chip**.
- [ ] **Status chips follow the `ConnectionsPage.tsx:506-520` `StatusBadge` pattern exactly**: `inline-flex … rounded-full … text-xs font-semibold`, a `bg-current` dot **plus a text label**, tone from `bg-danger-soft text-danger` / `bg-warning-soft text-warning` / `bg-success-soft text-success`. **Never colour-only.** The chip vocabulary is `Exact`, `Approximate`, `Sampled`, `Skipped`, `Not computed`.
- [ ] **Columns section** — the per-column findings. **Table on desktop, cards on mobile**, mount-gated with `useIsMobile()` exactly as the Files browser does (`FileBrowser.tsx:514-516`) — a flex faux-table (`overflow-hidden rounded-lg border border-border bg-surface`, an `aria-hidden` header strip, `border-border-2` row dividers) at `tablet:`/`desktop:`, and a two-line card `<li>` list on mobile. **It must not become a horizontally-scrolling table on a phone.**
- [ ] A column with an issue is tinted `bg-danger-soft` **and** carries its off-type count in `font-medium` — tint is never the only signal.
- [ ] **Qualifier callouts** for approximate and sampled figures use the existing `HelpGuideCard` callout shape (`HelpGuideCard.tsx:100-106`): a bordered, tinted box with an icon and a leading bold clause. The encoding callout states the **coverage percentage**; the ragged-row qualifier states **both** over-counting causes (quoted commas *and* newlines inside quoted fields).
- [ ] A **metadata footer** (`text-xs text-text-3`, `border-t`) states when the check ran, how many files were read, and — plainly — that **nothing was modified**.
- [ ] Every token used is from the `@theme` block in `index.css` (`text-text-2`, `bg-surface-2`, `border-border-2`, `bg-danger-soft`, …). **No raw Tailwind grays.** (`routes/NotFoundPage.tsx` still uses `text-gray-900` — it is an outlier and must not be copied.)

### FR-008: The notification's deep link has to actually work

#### Description

SPEC-114 requires the notification to link to `/data-quality/{space}/{requestId}`. **It currently cannot.** `notifications.types.ts` defines `Notification = { id, message, read, timestamp }` — there is **no link field** — and `NotificationRow.tsx:46-49` renders the message as **plain text**. Without this FR, SPEC-114's requirement is unimplementable and the report page is unreachable from the one place users are told to look.

#### Acceptance Criteria:

- [ ] The notification record gains an **optional `link?: string`** — an in-app path only. A test asserts an absolute URL or any non-`/`-prefixed value is **rejected at render** and the row falls back to plain text, so a notification can never become an open-redirect.
- [ ] `NotificationRow` renders the message as a `react-router` `<Link>` when `link` is present, and as plain text when it is not. Existing notifications without the field render exactly as they do today — a test pins that.
- [ ] The notifications **writer** persists `link` on `create` when the producer supplies it (SPEC-058's record shape gains one optional field; no other change). A comment records that this is a **contract change to a shipped pipeline** and is why it is called out here rather than assumed.
- [ ] The link is keyboard-focusable and has an accessible name that is not just "here" — the message text itself is the link.
- [ ] Table Builder's and Table Share's existing notifications are **unaffected** (they supply no `link`), and their tests pass unchanged.

### FR-009: Responsive + accessible

#### Acceptance Criteria:

- [ ] The **action** lives in the file browser's **`SelectionToolbar`**, beside Copy/Move/Delete (amendment 1) — **one** component tree with responsive utilities, not a `*Mobile`/`*Desktop` twin (`best-practices/react.md` §20). It is labelled at `tablet:`/`desktop:` and icon-only on mobile via that toolbar's existing `hidden tablet:inline` idiom, so it is reachable at all three breakpoints without a second mount. It is **not** added to the `MobileActionBar`, which holds folder-scoped actions (New folder, Upload) rather than selection-scoped ones.
- [ ] The **dialog** uses `Modal`'s small-screen presentation on mobile.
- [ ] The **report view** reflows at all three breakpoints: summary tiles 4-up → 2×2, header actions stacked, and the columns table becoming a card list (FR-007). It never scrolls horizontally on a phone.
- [ ] Where a mobile/desktop swap is **mount-gated** (`useIsMobile()`), a comment records why a CSS-only swap was not used — it would duplicate the markup in the DOM (the `NotificationRow.tsx:23` precedent).
- [ ] A11y tests are co-located `*.a11y.test.tsx` files using `expectNoA11yViolations` with **`ROUTE_AXE_OPTIONS`** for the page and `COMPONENT_AXE_OPTIONS` for the dialog (`src/test/axe.ts`), and are re-run at `window.innerWidth = 400` — mirroring `NotificationsPage.a11y.test.tsx:65-83`.
- [ ] The page asserts exactly **one `heading level 1`** and one `main` landmark.
- [ ] Loading is a `role="status"` line, not a bare spinner. The dialog traps focus (`focus-trap-react`), is dismissible with `Escape`, and returns focus to the trigger.

---

## Data Model

**Re-derived from `lambdas/data-quality-common/dqcommon/report.py::build`, which is shipped**
(amendment 2). The four ✏️ markers are where the original Data Model disagreed with it. The
rule is unchanged and is the reason the drift mattered: the SPA mirrors the report
**byte-for-byte** and does not reinterpret it, so a type that is merely *plausible* would
render a field that is never there and miss one that always is.

```ts
// apps/portal/src/features/data-quality/dataQuality.types.ts  (extended)

export type DataQualityVerdict = 'clean' | 'issues_found';

/** A figure that could never apply here (`skipped`) or was attempted and failed
 *  (`not_computed`). Both ALWAYS carry their reason, and neither may ever render as a
 *  clean pass — a green result the data did not earn is worse than no result. */
export type SkippedFigure = { status: 'skipped'; reason: string };
export type NotComputedFigure = { status: 'not_computed'; reason: string };

// ✏️ `nullBlankRatio` is on BOTH branches, not just the first: report.py::_column writes
//    name + nullBlankRatio before it ever branches on the skip reason. A skipped column
//    still has a real, exact null/blank ratio and the view must show it.
export type ColumnFinding = { name: string; nullBlankRatio: number } & (
  | { typeConsistency: 'skipped'; reason: string }
  // ✏️ `dominantType` is NOT free-form, and its casing is inconsistent at the source:
  //    a matched cast is upper-cased ('BIGINT' | 'DOUBLE' | 'TIMESTAMP' | 'DATE'), while
  //    the free-text fallback is the lower-case literal 'text'. The view normalizes for
  //    display; it must not assume upper-case.
  | { dominantType: 'BIGINT' | 'DOUBLE' | 'TIMESTAMP' | 'DATE' | 'text';
      nonParsingValues: number; sampleOffending: string[] }
);

export type RaggedRowsFigure =
  | { count: number; note: string }
  | NotComputedFigure          // a degraded query, or a line over Athena's 200 MB limit
  | SkippedFigure;             // non-CSV — not a line-delimited text format

export type EncodingFigure =
  | { invalidUtf8Sequences: number; sampleOffsets: number[];
      coverage?: 'complete' | 'sampled'; coveragePercent: number; note: string }
  | SkippedFigure              // Parquet (binary format) or .gz (DEFLATE output)
  // ✏️ report.py::_encoding also returns not_computed, for an absent byte-scan block —
  //    "an absent figure is not a clean one". The original union omitted this variant.
  | NotComputedFigure;

export type DataQualityReport = {
  requestId: string;
  location: string;
  format: string;
  fileCount: number;
  verdict: DataQualityVerdict;
  /** True on EVERY report this arc produces — a soft qualifier, never a warning (FR-007). */
  hasApproximateFigures: boolean;
  // ✏️ Added by SPEC-112 (user decision) and missing from the original Data Model. THE FLAG
  //    THAT ACTUALLY VARIES: something was skipped or failed, as opposed to something being
  //    approximate by nature. This is what the verdict banner warns on.
  hasIncompleteFigures: boolean;
  completedAt: string;         // ISO-8601 — the ONLY field a replay changes
  exact: {
    rowCount: number;
    rowCountsByFile: { key: string; rows: number }[];   // sorted by key, reconciled to fileCount
    duplicateRows: number | NotComputedFigure;
    columns: ColumnFinding[];
    crossFile: {
      columnsAgree: boolean;
      disagreements: { file: string; missing: string[]; extra: string[] }[];
    };
  };
  approximate: { raggedRows: RaggedRowsFigure; encoding: EncodingFigure };
  topIssues: string[];         // at most 5, severity-ordered (SPEC-112 FR-003)
};
```

## API / Interface Contract

```ts
// apps/portal/src/features/data-quality/useDataQualityCheck.ts
export function useDataQualityCheck(): {
  start: (target: { space: DataQualitySpace; location: string }) => Promise<void>;
  isPending: boolean;
};
// mints the requestId, calls enqueueQualityCheck (SPEC-109), and TOASTS EITHER WAY —
// success, or the failure routed through toUserMessage (SPEC-106). It resolves rather than
// reporting an outcome to its caller (amendment 3), which is what lets FR-006's "Re-run
// check" reuse it with no dialog mounted: the toast is that path's only feedback channel.

// apps/portal/src/features/data-quality/useDataQualityReport.ts
// Both route params are required: the report key is {space}/_data-quality-reports/{requestId}/report.json,
// so a requestId alone cannot locate a shared-space report.
export function useDataQualityReport(space: string, requestId: string): {
  report: DataQualityReport | undefined;
  isLoading: boolean;
  error: string | undefined;   // already passed through toUserMessage
};
```

## File & Folder Structure

```
apps/portal/src/features/data-quality/
├── DataQualityDialog.tsx
├── DataQualityDialog.test.tsx        # incl. vitest-axe
├── DataQualityReportPage.tsx         # the /data-quality/:space/:requestId view
├── DataQualityReportPage.test.tsx    # incl. vitest-axe + the "approximate is always qualified" test
├── useDataQualityCheck.ts        (+ test)
├── useDataQualityReport.ts       (+ test)
├── dataQualityReport.service.ts  (+ test)   # reads report.json
└── index.ts
apps/portal/src/features/file-browser/protectedFolders.ts   # HIDDEN_BROWSER_FOLDERS + PICKER_LOCKED_FOLDERS
apps/portal/src/features/notifications/notifications.types.ts  # + optional `link` (FR-008)
apps/portal/src/features/notifications/NotificationRow.tsx     # renders `link` as a <Link> (FR-008)
lambdas/notifications-writer/…                                  # persists `link` on create (FR-008 — shipped-pipeline contract change)
apps/portal/src/features/help/helpContent.ts                # the guide (completion ritual step 6)
```

## Implementation Phases

### Phase 1: Hook + dialog + folder protection

- `useDataQualityCheck` over the SPEC-109 service; the dialog with its read-only reassurance; toast + `toUserMessage`; hide and picker-lock `_data-quality-reports`. Tests incl. `vitest-axe`.

### Phase 2: The report view

- The **`/data-quality/:space/:requestId`** route, the read service, and the rendering — with approximate, skipped and not-computed figures always carrying their qualifier. Empty/error states, including an inaccessible `:space`. A test opening a **shared-space** report by URL. `vitest-axe`.

### Phase 3: Files integration, responsive, completion ritual

- `SelectionToolbar` wiring (amendment 1); verify all three breakpoints, including the findings tables reflowing to cards on mobile.
- Help & guides entry (SPEC-074 FR-005 — document only what is shipped and wired end to end), explaining in user language what the check does, that it changes nothing, and how to read the exact-versus-approximate distinction. Delivery doc, INDEX status, component-inventory rows.
