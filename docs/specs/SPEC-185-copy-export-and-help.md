---
type: Spec
id: SPEC-185
title: "Copy, Export, Help and the Arc's Live Checks"
description: "Adds Data Explorer copy (plain and advanced with headers and formats), export of the current result into a chosen space, Help guides, and the live-check script that closes the feature."
spec_status: Completed
depends_on: [SPEC-180, SPEC-182, SPEC-184]
arc: data-explorer
arc_order: 10
---

## Overview

The last spec of the arc: getting data out, telling users the feature exists, and writing down
what only a real deployment can prove.

Copy works over SPEC-180's selection and offers the formats people paste into other tools.
Export reuses `useSaveResults` unchanged — it copies the execution's own results object, so a
filtered or grouped exploration exports exactly what is on screen with no second query and no
second bill. Help gets guides now rather than earlier because SPEC-074 FR-005 documents only
what is shipped and wired end to end, and until this spec the feature was still arriving.

## Scope

### In Scope

- Copy: the plain tab-delimited default and an advanced copy with headers, row numbers, quoting
  and a format choice.
- Export: the current exploration's result into a chosen space, over `useSaveResults`.
- Help guides for the Data Explorer, with their registry rows under `dataExplorer`.
- The arc's live-check script.
- The arc's completion ritual: `ARCS.md` narrative, `decisions/` entries, the Key Decisions
  digest lines, the component-inventory rows and the `INDEX.md` statuses.

### Out of Scope

- **Exporting a selection.** Export writes the execution's result object; a partial export would
  need a second query or a client-side re-serialization of rows that may not all be loaded.
  Copy is the selection-shaped tool.
- **New export formats on the S3 side.** The results object is Athena's CSV; this spec adds no
  conversion pipeline. Copy's formats are clipboard-only.
- **Scheduled or repeated exports.**
- Any change to `useSaveResults` beyond its call site.
  > **Amended in build (2026-08-14).** `useSaveResults` lives in `features/query/`, which
  > `features/data-explorer/` may not import (SPEC-176's sibling clause) — so "reuse it unchanged"
  > was unreachable from where it sat. It **moved** to `features/catalog/`, body untouched, with
  > `SaveResultsDialog` and `normalizeCsvName`; the exclusion above is read as "no behavioural
  > change", which the move meets. One field did change and it closed a live defect: the
  > destinations are now a **parameter**, because the hook's own unfiltered list had been offering
  > a colleague's space as a write target with `sharedWorkspaces` off. See `decisions/`.

---

## Functional Requirements

### FR-001: Copy

#### Description:

Copying the selection, in the shape the destination wants.

#### Acceptance Criteria:

- [ ] Ctrl/Cmd+C copies the selection as tab-delimited text, rows in grid order.
- [ ] Advanced copy offers: include headers, include row numbers, quote values, and a format
      choice of CSV, JSON, Markdown, SQL `INSERT` and XML.
- [ ] The values copied are the **raw** cell values, not transformed renderings (SPEC-184
      FR-005) — a URL-transformed column copies its underlying value.
- [ ] `NULL` and the empty string are distinguishable in every format.
- [ ] A discontiguous selection copies as the bounding rectangle with unselected cells empty,
      and the behaviour is stated in the UI rather than left to be discovered.
- [ ] Copying a column header selection copies the whole loaded column, and the label says the
      selection is over loaded rows.
- [ ] Copy issues no query.

### FR-002: Export

#### Description:

Writing the current exploration's result into a space, reusing the Query workspace's path.

#### Acceptance Criteria:

- [ ] Export copies the **current execution's** results object — so filters, ordering and
      grouping are reflected without a second query, asserted by `StartQueryExecution` count of
      zero across an export.
- [ ] The destination picker is `useSaveResults`' own, with its overwrite prompt and its
      cross-bucket copy behaviour unchanged.
- [ ] Export is unavailable before an execution has succeeded, refused through
      `Button.disabledReason`.
- [ ] The destination selector gets its own `sharedWorkspaces` registry row, following SPEC-175's
      finding that each selector instance needs one.
- [ ] A failed copy shows the mapped message and leaves the dialog open.

### FR-003: Help guides

#### Description:

`helpContent.ts` gains the Data Explorer, documenting only shipped, wired behaviour.

#### Acceptance Criteria:

- [ ] A guide covers: opening an exploration from the picker and from **Explore data**;
      filtering and sorting, and that each apply runs a query; grouping; Calc and what it
      aggregates; loading and saving `.sql` files, including that a saved exploration reopens as
      a query; and export.
- [ ] The guide states plainly that filtering and sorting run against Athena and scan data, and
      that the figures shown are the cost signal — this is the one thing a user cannot infer
      from the UI.
- [ ] Each guide has a `kind: 'guide'` registry row under `dataExplorer`, so it leaves both the
      Help list and the search index with the flag off — the registry is the only home of the
      guide→flag mapping.
- [ ] Nothing excluded from the arc is documented: no chart, no editing, no named filters, no
      References panel.

### FR-004: The live checks

#### Description:

What the deployment must prove, as a script rather than a prose summary — fixtures, exact
labels, expected numbers.

#### Acceptance Criteria:

- [ ] `docs/testing/e2e.md` exists, with one section per spec that owes a check.
- [ ] It records, at minimum: that a filter apply produces a **new** Athena execution and a
      changed bytes-scanned figure, observed in the network panel rather than inferred from the
      grid; that paging produces **none**; that a value containing a single quote filters
      correctly against real data (the `sqlLiteral` path, which no unit test can prove against
      the real engine); that a grouped exploration's disclosed SQL matches what Athena ran; that
      a `.sql` file saved here opens in the Query workspace and vice versa; and a Safari pass at
      400px and desktop.
- [ ] It names the browser, because the tooling used to build this is Chromium and the checks
      are Andrew's to run in Safari.
- [ ] Checks that were only proxied by unit tests are recorded as **owed**, not discharged.

### FR-005: The completion ritual

#### Acceptance Criteria:

- [ ] `ARCS.md` gains the Data Explorer arc's narrative: why it exists, and how ten specs
      compose.
- [ ] `decisions/` gains full entries for the arc's architectural decisions — the server-side
      engine and one-execution-per-rendered-SQL; the presentation/SQL split enforced by the
      renderer's signature; the TypeScript DML escaper and its distinction from the DDL one; the
      independent flag and the ungated expression bar; Calc-client/Grouping-server; and the
      saved-exploration-reloads-as-a-query loss with its rejected sidecar.
- [ ] Each gains **one line** in `CLAUDE.md`'s Key Decisions — never a paragraph, never the only
      home of a fact.
- [ ] Component-inventory rows are added to the file matching each component's path.
- [ ] Every spec 176–185 is `Status: Completed` with its `INDEX.md` row updated.
- [ ] `CLAUDE.md`'s Current work section is **pruned**, not appended to.

---

## API / Interface Contract

```ts
export type CopyFormat = 'tsv' | 'csv' | 'json' | 'markdown' | 'sql' | 'xml';

export type CopyOptions = {
  format: CopyFormat;
  includeHeaders: boolean;
  includeRowNumbers: boolean;
  quoteValues: boolean;
};

/** Pure: selection + raw rows + options → clipboard text. */
export function renderCopy(
  selection: Selection,
  columns: QueryColumn[],
  rows: string[][],
  options: CopyOptions
): string;
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── AdvancedCopyDialog.tsx
├── ExportExplorationDialog.tsx
├── renderCopy.ts
├── renderCopy.test.ts
└── copyExport.test.tsx

docs/testing/e2e.md      # NEW
```

---

## Implementation Phases

### Phase 1: Copy

- `renderCopy` across all six formats, with the raw-value, `NULL` and discontiguous rules.
- The plain and advanced copy surfaces.

### Phase 2: Export

- The `useSaveResults` call site, the disabled reason, and the zero-execution assertion.

### Phase 3: Help

- The guides and their registry rows, walked in both flag states.

### Phase 4: Live checks and the ritual

- The e2e script.
- `ARCS.md`, `decisions/`, the Key Decisions lines, the inventory rows, and the INDEX sweep.
