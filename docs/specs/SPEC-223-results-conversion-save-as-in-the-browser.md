# Spec: Results Conversion — "Save as" in the Browser, the Flag & Help

**ID:** SPEC-223
**Status:** In Progress
**Last Updated:** 2026-09-07
**Depends On:** SPEC-222 (the converter and its notification), SPEC-049 and SPEC-185 (the two Save-results surfaces and `useSaveResults`), SPEC-162/163 (feature flags and the gated-surfaces registry), SPEC-207 (Help)

## Overview

The plane exists and converts; this spec lets a user ask it to. **Save results to my files** on the
Query workspace and the Data Explorer gains a format: CSV, which stays the instant copy it is today,
or Parquet, JSON or Excel, which hand the request to the plane and come back as a notification with
a link to the file. The dialog, the destination picker and the overwrite question are the ones both
surfaces already share, so a user who has saved a CSV already knows how to save a Parquet.

Two things are settled here. **The collision question is asked before the request leaves the
browser**, with the same warn-and-confirm the CSV path uses, and the plane's conditional write stays
the authority — the pre-flight is a courtesy, not the guard. And **the new formats are a
presentation flag**: `resultsConversion` off hides three options and changes nobody's access to
anything, gated through the registry so one test walks the surface in both states.

## Scope

### In Scope

- A format choice in `SaveResultsDialog`, shared by both surfaces; the file-name rule generalised
  from `normalizeCsvName` to one function per format.
- The pre-flight destination probe through `objects.exists`, and the overwrite confirm reused.
- `resultsConversion.service.ts` and the enqueue path inside `useSaveResults`, so the CSV copy and
  the three conversions share one hook and one dialog.
- The `resultsConversion` feature flag, its default, its registry entry and the both-states sweep.
- The notification's link opening the destination folder, with that folder's listing refreshed on
  the way.
- Help & guides for both surfaces, accessibility, mobile, and the live checks folded into
  `docs/testing/e2e.md`.

### Out of Scope

- An in-flight surface for pending conversions. The notification is the completion channel, as
  it is for data quality; the toast on submit says so. A session-scoped record like file-ops' is
  not built, because nothing here locks a space and nothing waits on the outcome.
- Remembering the last chosen format across sessions or tabs. Every open of the dialog starts at
  CSV.
- Choosing compression, a sheet name, a delimiter or any other per-format option.
- Converting from the Files browser (a CSV already in a space). This surface saves a result set;
  the file-converter arc that would have done the other thing is cancelled.
- Progress. A conversion has no progress event the browser can see, and a bar that guesses is the
  bar the upload rule forbids.

---

## Functional Requirements

### FR-001: The format choice

#### Description:

One more field on the dialog both surfaces share.

#### Acceptance Criteria:

- [ ] `SaveResultsDialog` gains a labelled `<select>` **Format** with `CSV`, `Parquet`, `JSON` and
      `Excel`, defaulting to `CSV`; its accessible name is "Format" and the axe assertion for the
      dialog covers the open dialog with the select present.
- [ ] The file-name rule becomes `normalizeResultsName(name, format)`: it appends the format's
      extension (`.csv`, `.parquet`, `.json`, `.xlsx`) unless the user already typed it
      (case-insensitive), never doubling it, and **replaces** the extension of another format the
      user had typed before switching (typing `report.csv` then choosing Parquet yields
      `report.parquet`). `normalizeCsvName` is deleted, and a grep finds no caller.
- [ ] Choosing `CSV` takes the existing synchronous copy, byte for byte unchanged — the same
      `copyObject` call with the same arguments, asserted on the call.
- [ ] Choosing any other format enqueues through FR-003; the dialog's primary button reads
      **Save here** for CSV and **Convert and save** otherwise, so the user is told a wait is coming
      before they click.
- [ ] With the `resultsConversion` flag off the select is **absent** (not disabled) and the dialog
      behaves exactly as before the spec; the gated-surfaces registry carries the entry and the
      both-states test walks it. With `query` off the whole dialog is gone, as today.

### FR-002: The pre-flight collision

#### Description:

The user is asked about an existing file before the request leaves, and the plane still decides.

#### Acceptance Criteria:

- [ ] Before enqueueing, the hook asks `objects.exists` for the destination key with `target`
      omitted (the route's default, `"object"`; `"prefix"` is the other value). `true` opens the existing overwrite confirm, whose confirm re-submits with
      `onConflict: "overwrite"`; `false` submits with `refuse`.
- [ ] A 403 from the probe counts as occupied and opens the same confirm — the space may hold a
      file the actor cannot see, and the plane will refuse it.
- [ ] A probe that fails for any other reason shows the failure toast and submits nothing; the
      dialog stays open.
- [ ] The plane's `destination_occupied` notification (a name taken between probe and write) is
      rendered by FR-004 like any other failure; nothing in the browser retries.

### FR-003: The enqueue service and the hook

#### Description:

One hook, two paths.

#### Acceptance Criteria:

- [ ] `resultsConversion.service.ts` exposes `enqueueResultsConversion(request)` calling the
      generated `resultsConversion.enqueue` route through `apiRequest`, returning `ServiceResult<{requestId}>`;
      the request type is the generated one and `requestId` is a fresh UUID per submit.
- [ ] `useSaveResults` routes on the format: CSV to `copyObject`, the rest to the service; both
      share `open`, `busy`, `overwritePrompt`, `save`, `confirmOverwrite` and `cancelOverwrite`, and
      the Explorer's `ExportExplorationDialog` and the Query workspace's dialogs need no change
      beyond the field.
- [ ] On an accepted enqueue the dialog closes and a toast says *Converting to Parquet — you'll get a
      notification when {filename} is ready*, naming the format and the file; no listing is
      invalidated yet, because nothing has been written.
- [ ] A refused enqueue (a 4xx from the route) shows the mapped sentence from `lib/errorMessages.ts`
      and keeps the dialog open; raw route text is never rendered, asserted by rendering a refusal
      whose body carries a sentinel string and finding it absent from the document.
- [ ] `apiRequest` retries nothing for this route; `idempotent` is `false` in the generated contract,
      asserted by reading the generated route table.

### FR-004: The notification, the link and the listing

#### Description:

What arrives when the plane finishes.

#### Acceptance Criteria:

- [ ] A success notification's `link` stays the **message anchor** the row already renders,
      through the existing `isSafeInAppPath` gate, and following it lands on the destination folder
      in Files (personal) or the shared space's browser. **Following the link** invalidates that
      folder's listing before navigating, so the file is present on arrival;

      **Amended mid-build.** This criterion said the link renders *as "Open folder"*, which
      contradicts the rule `NotificationRow` states and justifies for every producer — the message
      IS the link, never a trailing control, so the row is one target whose accessible name says
      where it goes. Honouring both would have put two anchors on one href, which is the duplicate
      the component records having shipped twice. Andrew took the call: keep the message anchor and
      drop the label. The invalidation is therefore a **mechanism over any `/files` link** rather
      than a clause for this producer — file send and archive deep-link into folders they have just
      written to as well, and a per-producer version would silently do nothing for the next plane.
      It also means the link needs **no gated-surfaces row**: its destination is `/files`, already
      covered by that flag's link clause, exactly as the archive plane's link is.
 the notification's arrival invalidates nothing,
      because notification-driven listing reconciliation is the mechanism the file-ops provider
      records as deliberately not used (the poll is a minute wide and pauses on a hidden tab), and
      the listing's own focus refetch already covers the user who is simply looking at the folder.
- [ ] A failure notification renders the plane's sentence; the `excel_row_limit` one is checked
      end-to-end to name the count and suggest Parquet, so the wording registered on the plane is
      the wording a user sees.
- [ ] Neither notification renders a column name or the SQL, asserted on fixtures carrying both.

### FR-005: Help, accessibility and the live checks

#### Description:

The surface is documented only once it is wired end to end.

#### Acceptance Criteria:

- [ ] The Query help section *Save results to your files* and the Explorer's *Copy or save what
      you found* say the four formats, that CSV is immediate and the others arrive as a
      notification, that JSON is one object per line, and Excel's row limit and precision note.
- [ ] The dialog passes the axe assertion with the select present; the select is reachable by
      keyboard and Enter still submits from the file-name field only.
- [ ] At 375 px the dialog's fields stack — the format `<select>` is full-width like the name and
      space fields above it — and the primary button is unchanged by this spec; verified in the
      responsive band 375–899 as well as at 900.

      **Amended mid-build: the 38 px was a false premise.** The dialog's primary button is
      `DestinationPicker`'s, which is the `Button` primitive at its default `h-9` — **31.5 px** at
      this app's 14 px root, at every width, and the same in all six DestinationPicker dialogs. The
      38 px figure is this repo's *mobile touch* pattern (`h-[38px] tablet:h-9`), which that button
      has never used. Resizing it would change six dialogs no part of this spec is about, so the
      criterion asserts what this change owes instead: the select does not disturb the button, and
      the fields stack. 31.5 px clears SC 2.5.8's 24 px minimum comfortably, so nothing is being
      waived. The measurement itself is a live check — jsdom measures no geometry at all.
- [ ] `docs/testing/e2e.md` gains the live checks: each format saved from the Query workspace and
      from the Explorer, the file read back (Parquet through *Create table*, JSON through *Create
      table*, Excel opened), the overwrite confirm, a shared-space destination, the flag off, and a
      refusal at the Excel row limit staged with a fixture above it. Each check names the exact
      labels and the expected numbers.
- [ ] Every check that cannot run from a signed-in session is a row in `docs/testing/owed.md`.

---

## Data Model

```ts
// apps/portal/src/features/catalog/catalog.types.ts
export type ResultsFormat = 'csv' | 'parquet' | 'json' | 'xlsx';

// apps/portal/src/features/catalog/catalog.format.ts
export function normalizeResultsName(name: string, format: ResultsFormat): string;

// apps/portal/src/features/catalog/resultsConversion.service.ts
export function enqueueResultsConversion(
  request: ResultsConversionEnqueueRequest
): Promise<ServiceResult<{requestId: string}>>;

// useSaveResults `save` gains the format
save: (args: {destBucket: string; destPrefix: string; filename: string; format: ResultsFormat}) => void;
```

## File & Folder Structure

```
apps/portal/src/features/catalog/
├── SaveResultsDialog.tsx            (+ Format select)
├── useSaveResults.ts                (routes on format; pre-flight probe)
├── resultsConversion.service.ts
├── resultsConversion.service.test.ts
└── catalog.format.ts                (normalizeResultsName)
apps/portal/src/features/feature-flags/featureFlags.types.ts, featureFlagDefaults.ts, gatedSurfaces.ts
config/feature-flags.json                     (the served document)
scripts/validate_feature_flags.py             (its literal key set)
lambdas/test_feature_flags_config.py          (the key set asserted from the Lambda side)
apps/portal/src/features/help/helpContent.ts
docs/testing/e2e.md
```

## Implementation Phases

### Phase 1: The format field and the name rule

- `ResultsFormat`, `normalizeResultsName`, the select, the flag and its registry entry.

### Phase 2: The service and the routed hook

- `resultsConversion.service.ts`, the pre-flight probe, the two paths in `useSaveResults`, the toast
  and the refusal wording.

### Phase 3: The notification

- The link and the listing invalidation on arrival.

### Phase 4: Help, accessibility and the responsive band

### Phase 5: Verification

- The live checks in `e2e.md`, run from a signed-in session; owed rows for the rest.

### Phase 6: Completion ritual

- Delivery doc, INDEX row, the inventory rows, the Help sweep, and the arc's closing note in
  `ARCS.md`.
