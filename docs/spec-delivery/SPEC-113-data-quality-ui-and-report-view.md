# Completed Spec — SPEC-113: Data Quality — File-Browser UI + the Report View

The arc's first user-facing surface: a way to start a check, and a page that makes its
report readable. Shipped in four PR commits on one branch.

## What was completed?

- **Start a check** — `features/data-quality/useDataQualityCheck.ts` (mints the request id,
  enqueues via SPEC-109, toasts either way) + `DataQualityDialog.tsx` (composed on the
  shared `ConfirmDialog`, so focus trapping/Escape/focus-return are inherited). Wired into
  the file browser's **`SelectionToolbar`**, enabled on exactly one selected file or folder.
- **The report view** — `/data-quality/:space/:requestId`: `dataQualityReport.service.ts`,
  `useDataQualityReport.ts` (space resolution + fetch), `DataQualityReportPage.tsx`, and a
  thin `routes/DataQualityReportPage.tsx`. Verdict banner, four summary tiles, top issues
  with status chips, a columns faux-table that becomes cards on mobile, cross-file
  disagreements, qualifier callouts, metadata footer. No new shared component.
- **`_data-quality-reports` is hidden and picker-locked** (`protectedFolders.ts`, both lists).
- **Notifications gained an optional `link`** (FR-008) — see below.
- **Help guide** — "Check data quality" in the Files section (`helpContent.ts`), scoped to
  starting a check (see the gap below).

## KNOWN GAP — the report view has no in-app route yet

**A finished check surfaces nowhere.** SPEC-113 shipped copy promising "you'll get a
notification with a link to the report", but nothing sends one: `dq_notify_failure` is
still a SPEC-108 pass-through stub and there is no success emitter at all — that is
**SPEC-114**, unbuilt. The runs dashboard (**SPEC-123**) is unbuilt too. So today the only
way to open a report is to type `/data-quality/{space}/{requestId}`.

This was caught on the first live run (2026-07-21): the check succeeded in 51s and wrote its
report; the user saw nothing. The false promise was removed from the dialog, the success
toast and the help guide in a follow-up, and `DataQualityDialog.test.tsx` now asserts the
dialog says nothing about notifications. **SPEC-114 should delete that assertion and restore
the wording in the same change.**

The lesson for the arc: SPEC-113 verified the SPEC-058 notifications *pipeline* worked, but
never checked that anything on the data-quality side *calls* it. Half a flow tested end to
end is not an end-to-end test.

### Deliberate deviations (all recorded as Amendments in the spec)

1. The action lives in the **`SelectionToolbar`**, not the `MobileActionBar` — it is
   selection-scoped, and that toolbar is already reachable at every breakpoint.
2. The report types are **re-derived from the shipped `dqcommon/report.py`**, which the
   spec's Data Model predated and disagreed with in four places (missing
   `hasIncompleteFigures`; `nullBlankRatio` on both `ColumnFinding` branches; a missing
   `not_computed` encoding variant; a constrained `dominantType`).
3. `start` **toasts on failure too** and the dialog closes either way — nothing to re-enter,
   and "Re-run check" calls the same hook with no dialog at all.
4. **Two header actions, not three**: SPEC-120 is still `Draft`, so "Convert to Parquet" and
   its import are absent from the codebase entirely, per FR-006's own conditional.
5. The verdict banner **warns on `hasIncompleteFigures`**, not `hasApproximateFigures` — the
   latter is true on every report the arc can produce, so it can only qualify softly.

## What changed from earlier specs?

- **SPEC-058's notification record gains one optional field, `link`** — a contract change to
  a shipped pipeline. `notifications_writer.apply_create` persists it when a producer
  supplies a non-empty string; every existing producer still writes byte-identical records
  (all 922 Lambda tests pass unchanged). The browser does **not** trust it:
  `isSafeInAppPath` gates it at render and the row falls back to plain text, so a
  notification can never become an open redirect. `notifications.service.normalize` had to
  be taught to carry the field — it rebuilds rows field-by-field.
- **`lib/errorMessages.ts`** gains two app codes (`DataQualityReportNotFound`,
  `DataQualityReportUnreadable`), kept separate from the generic `NotFound` because
  "refresh and try again" is wrong advice for a report that was deleted.

## Verification

`npm run format`/`lint`/`test`/`build` green locally (build is the only thing that
typechecks `*.test.tsx`), plus `pytest lambdas`. The report page was also rendered in a
browser at 1400px/375px from a temporary fixture-seeded harness (removed before commit),
which is what caught two wording bugs the tests could not: a stuttering callout lead
("This is an estimate. Approximate — …") and Lambda reason fragments rendering
mid-sentence-cased after a bold lead. Nine guards were verified by mutation — each was
observed failing when its code was broken; two of those mutations exposed real bugs (a
premature space resolution that cached a wrong-bucket read, and an untested `link` drop in
the notifications read path). **The live end-to-end run is still outstanding** — SPEC-112
deferred it until this spec landed so the check could be driven as a user drives it.

**Later correction to the first of those bugs:** no committed version of `useDataQualityReport`
could cache that wrong-bucket read. From the hook's first commit the username resolved personal
ahead of shared names, with or without the connections list, so the report's wait for the list
guarded no runtime read and has since been removed. What the wait did do was let the precedence
test catch a flipped precedence; that test now caches the list before the page mounts.
