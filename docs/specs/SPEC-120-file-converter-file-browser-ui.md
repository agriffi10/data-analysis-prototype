---
type: Spec
id: SPEC-120
title: "File Converter — File-Browser \"Convert to Parquet\" UI"
description: "Would have delivered a Convert to Parquet dialog in the file browser with an editable destination and a warning about writing under an existing table, cancelled before it was built."
spec_status: Cancelled
depends_on: [SPEC-116, SPEC-118, SPEC-119, SPEC-095, SPEC-045, SPEC-106, SPEC-074]
arc: file-converter
arc_order: 6
---

**Dependency notes:** SPEC-116 (enqueue service + contract), SPEC-118/119 (the pipeline actually converts), SPEC-095 (responsive foundation), SPEC-045 (a11y), SPEC-106 (error messaging), SPEC-074 (help content)
> **Read `docs/file-converter-architecture.md` §3.1 and §5 first.** Presentation + enqueue only.

## Overview

Surface the feature: from the Files browser, on a selected file or folder, **"Convert to Parquet"** opens a dialog with a proposed destination, the user confirms, and the async pipeline runs. The outcome arrives as a notification (SPEC-121).

**This spec carries a safety obligation, not just a form.** The destination is user-editable — a deliberate product decision (`file-converter-architecture.md` §3.1) taken in preference to a locked-down reserved namespace. The residual risk that decision accepts is this: if the user points the output **underneath a folder an existing Glue table already reads**, Athena will pick the new Parquet files up on that table's next query, and the query may **succeed while returning wrong rows**. The pipeline deliberately does not spend a Glue lookup to detect this, so **the dialog is the only place the user can be told.** The warning must **name that specific case** — a generic "be careful where you put this" discharges nothing.

## Scope

### In Scope

- A **"Convert to Parquet"** action on a selected file or folder, in personal and shared spaces.
- A dialog with: the source, an **editable destination** (default `{parent}/{folderName}_parquet/`), the **nested-destination warning**, and a note that conversion runs in the background.
- Client-side pre-validation mirroring the server rules (same space, not a reserved prefix) so common mistakes fail **instantly in the form** rather than 30 seconds later in a notification. The server (SPEC-116) remains the authority; the client check is UX, not security.
- Enqueue via `enqueueConversion` (SPEC-116); pending state + transient toast; failures via `toUserMessage` (SPEC-106).
- **Hide `_fc-work` in the file browser** and lock it in the move/copy picker.
- **Responsive** (SPEC-095), **a11y** (SPEC-045), **error wording** (SPEC-106), **help content** (SPEC-074).

### Out of Scope

- Any Glue/catalog lookup to check whether the destination sits under a table's LOCATION. The warning is the mitigation. (SPEC-118 does give the execution role Glue read, so a server-side check later is cheap — a deliberate follow-up, not a permanent exclusion.)
- A progress bar or per-file progress. The pipeline is fire-and-forget; the notification is the completion channel.
- Letting the user pick the CSV delimiter (comma, v1).
- Excel (`.xlsx`) conversion — deferred entirely (user decision 2026-07-13); see FR-001.
- Multi-select conversion. One file or one folder per request.

---

## Functional Requirements

### FR-001: The action

#### Acceptance Criteria:

- [ ] "Convert to Parquet" is available on exactly one selected file or folder, in a personal space and in a shared space the user belongs to.
- [ ] It is **not** offered on the `..` parent row (SPEC-098), on `user_settings`, on `_data-quality-reports`, on `_fc-work`, on an empty selection, or on a multi-select.
- [ ] It is **not** offered on a `.parquet` source (there is nothing to convert). A test asserts this.
- [ ] It is **not** offered on a `.xlsx` source — Excel conversion is deferred entirely (user decision 2026-07-13), following the same not-offered model as `.parquet`. A test asserts this. (A `.xlsx` inside a selected *folder* is caught server-side as `unsupported_format`, SPEC-117 FR-001 — the client does not list folder contents to pre-check.)

### FR-002: The destination field

#### Acceptance Criteria:

- [ ] The destination defaults to `{parent}/{folderName}_parquet/` and is **editable**.
- [ ] Client-side pre-validation rejects, with an inline message and a disabled confirm button: a destination outside the current space; a destination under `athenaresults/`, `user_settings/`, `shared_tables/`, `_data-quality-reports/`, or `_fc-work/`; and the root `DO_NOT_DELETE.txt`.
- [ ] The client check is documented in code as **UX only** — SPEC-116's `validate-authorize` is the authority, and a request that slips past the client is still rejected server-side.
- [ ] A **non-empty destination** surfaces the server's `destination_not_empty` through `toUserMessage`, with guidance to choose an empty folder.

### FR-003: The nested-destination warning

#### Description

The one thing this dialog exists to say. It discharges the accepted risk of `file-converter-architecture.md` §3.1.

#### Acceptance Criteria:

- [ ] The dialog displays a **persistent** (not dismissible-and-forgotten) warning naming the specific hazard: **if the destination sits inside a folder that one of your tables already reads, the converted files will show up in that table's query results.**
- [ ] The warning is phrased in user language — it does **not** say "LOCATION", "Glue", or "Athena catalog" — and tells the user what to do instead (pick a folder that no table points at).
- [ ] **The warning is shown in every dialog state — default, edited, and pending.** The default destination is **not** safe by construction, so there is no state in which the warning may be dropped. A comment records the counterexample that killed the edited-only display: a table over `alice/sales/` with the source `alice/sales/raw/` yields the default `alice/sales/raw_parquet/` — **nested under the live table's LOCATION and empty**, so it passes every server check and poisons the table. A test asserts the warning is present with the untouched default.
- [ ] The warning text is covered by a test, so a future copy edit cannot silently gut it.

### FR-004: Feedback and errors

#### Acceptance Criteria:

- [ ] A successful enqueue closes the dialog and raises a transient "converting…" toast. The browser never blocks.
- [ ] Every failure is rendered via `toUserMessage` (SPEC-106) — never `error.message`, never raw AWS/SQS/Athena text.
- [ ] The dialog does **not** render pipeline failures like `inconsistent_headers` — those arrive minutes later as SPEC-121 notifications, authored Lambda-side. Instead, the **help content** (Phase 3, SPEC-074) carries the obligation: the guide explains that a folder of CSVs must share one header, and that conversion outcomes — success or failure — arrive in **Notifications**.
- [ ] The confirm button is disabled in flight (no double-enqueue).
- [ ] A missing `VITE_FILE_CONVERTER_QUEUE_URL` produces the friendly "contact the Administrator" path, not a crash.

### FR-005: Hide the scratch folder

#### Acceptance Criteria:

- [ ] `_fc-work` is added to `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` (`apps/portal/src/features/file-browser/protectedFolders.ts`), alongside the existing entries (and `_data-quality-reports` where SPEC-113 has shipped).
- [ ] A test asserts it is absent from a listing that contains it, and cannot be selected as a move/copy destination.

### FR-006: Responsive + accessible

#### Acceptance Criteria:

- [ ] Reachable via `MobileActionBar` on mobile and the toolbar/menu at `tablet:`/`desktop:` — **one** component tree with responsive utilities, not a `*Mobile`/`*Desktop` twin (`best-practices/react.md` §20).
- [ ] The dialog uses `Modal`'s small-screen presentation. The destination field **and the warning** are both fully usable at the mobile breakpoint — the warning must not be clipped or scrolled out of view, because it is the point of the dialog. A test asserts it is visible at the mobile viewport.
- [ ] `vitest-axe` reports no violations in the default, edited-destination, and pending states (the warning is present in all three — FR-003).
- [ ] Focus is trapped (`focus-trap-react`), `Escape` dismisses, focus returns to the trigger on close.
- [ ] The pending/toast state is announced to assistive technology.

---

## API / Interface Contract

This section serves as the spec's Data Model — the feature introduces no data shapes beyond these signatures (the request envelope is SPEC-116's).

```ts
// apps/portal/src/features/file-converter/useFileConversion.ts
export function useFileConversion(): {
  start: (req: Omit<FileConversionRequest, 'requestId'>) => Promise<void>;
  isPending: boolean;
};
// mints the requestId, calls enqueueConversion (SPEC-116),
// toasts on success, routes failures through toUserMessage (SPEC-106).

// apps/portal/src/features/file-converter/destination.ts
export function proposeDestination(sourceKey: string): string;                                 // `{parent}/{folderName}_parquet/`
export function validateDestinationClientSide(dest: string, space: ConverterSpace): string | null;  // null = ok
```

## File & Folder Structure

```
apps/portal/src/features/file-converter/
├── ConvertToParquetDialog.tsx
├── ConvertToParquetDialog.test.tsx    # incl. vitest-axe + the warning-text test
├── useFileConversion.ts          (+ test)
├── destination.ts                (+ test)
└── index.ts
apps/portal/src/features/file-browser/protectedFolders.ts   # + _fc-work
apps/portal/src/features/help/helpContent.ts                # the guide (completion ritual step 6)
```

## Implementation Phases

### Phase 1: Destination logic + hook

- `proposeDestination`, `validateDestinationClientSide`; `useFileConversion` over the SPEC-116 service. Unit tests for every blocklist entry.

### Phase 2: Dialog

- The form; the **nested-destination warning** (FR-003) — present in every state — with its text test; the toast/error path. `vitest-axe` in all three states.

### Phase 3: Files integration, responsive, completion ritual

- Toolbar + `MobileActionBar` wiring; hide and picker-lock `_fc-work`; verify the warning is fully visible at the mobile breakpoint.
- Help & guides entry — in user language: what conversion does, where the files land, that a folder of CSVs must share the same header, that outcomes (success or failure) arrive in **Notifications**, and the destination caveat. Delivery doc, INDEX status, component-inventory rows.
