# Completed Spec — SPEC-123: Data Quality — Runs Dashboard

## What was completed?

A **Data quality** destination listing every completed check the user can see, newest first,
with a click through to the full report. It closes a real gap: a report used to be reachable
**only** from its notification, so clearing that notification effectively lost the report.

- **`dqcommon/index_store.py`** — the per-space runs index, appended by `assemble-report`
  under **optimistic ETag CAS** with bounded retry (`DQ_INDEX_CAS_RETRIES`), capped at
  `DQ_INDEX_MAX_ENTRIES` (200, oldest dropped first), rebuilding a missing or corrupt index
  rather than failing. A replayed `requestId` **replaces** its row, matching the report key's
  own replay-safety.
- **`/data-quality`** — `DataQualityPage` + `DataQualityRunRow` + `useDataQualityRuns` +
  `dataQualityRuns.service`. Aggregates the personal space and every usable shared space,
  merges, sorts newest-first, 10/page, filter by verdict, refresh.
- **Navigation** — a `PrimaryNav` tab (Files · Query · Connections · Data quality) and an
  `AppNavDrawer` destination for mobile.
- **Help** — a "Find a past quality check" guide (SPEC-074).

**No new IAM, and no infra change at all.** The Lambda's existing
`*/_data-quality-reports/*` grant already covers `index.json` for both Get and Put, and the
browser already reads that prefix for the report view. Confirmed against
`policies/execution.json.tftpl` rather than assumed.

**Deviations from the spec, both agreed in-session:**

- **The shipping gate was amended.** The spec forbade shipping before SPEC-114 FR-004 **and
  FR-005**; FR-005 was removed on 2026-07-21 and replaced by the unbuilt **SPEC-126**. Rather
  than block, the FR-006 footer line is worded **"usually"** instead of as a guarantee, and a
  test pins that wording. **Tighten both when SPEC-126 lands.**
- **The notification is emitted before the index append**, not after. FR-001 only required
  the index to follow the report; putting up to `DQ_INDEX_CAS_RETRIES` round trips ahead of
  the user's only completion signal would mean a verb timing out mid-CAS leaves a written
  report nobody is ever told about.

## What changed from earlier specs?

- **`assemble-report` (SPEC-112) now writes twice.** Order is report → notification → index,
  most durable to least. Its test helper `_written` selected `puts[-1]`, which silently
  became the index; it now selects by key. A bare `len(puts) == 2` assertion in the replay
  test was measuring both objects at once and is now scoped to the report writes.
- **`dataQuality.format.locationLabel` is not used by the row.** It returns the basename, and
  FR-003 needs the path with its *end* kept visible. The row splits the location into a
  truncatable parent and a non-shrinking final segment — deliberately not the usual
  `direction: rtl` trick, which re-orders a leading or trailing `/` in an S3 key and renders
  `alice/sales/` as `/alice/sales`.
- `PrimaryNav`, `AppNavDrawer`, `App.tsx`, the feature barrel, `dataQualityKeys` (a `runs`
  key, keyed by joined space names so leaving a shared space cannot serve a stale merge).

## Verification

`pytest lambdas/` 989 passed · `vitest` 1159 passed · `npm run build`/`lint`/`format:check` ·
`tofu validate` not needed (no infra change).

**12 mutations, 12 guard failures** — including the CAS itself (removing the preconditions,
re-using a stale list across attempts), the cap direction, replay de-duplication, both write
orderings, the sampled chip, colour-only verdict, partial-space failure, and both failure
modes of the FR-006 footer line.

Rendered at desktop and mobile via the dev-unauth bypass: no console errors, no horizontal
overflow at 375 px, header actions stack. **Rows were not verified visually** — the bypass
renders unauthenticated, so no space resolves and the list is empty; row rendering and
truncation rest on the unit and a11y tests.

**Deferred:** the live end-to-end (user decision, 2026-07-21) — no smoke tests until 124 is
built, then one pass over the arc. **The index write is unproven against real S3**, and its
conditional-put behaviour is the part fakes model least well: `test_index_store_dqcommon.py`
implements the If-Match/If-None-Match contract by hand, so it verifies this code against a
*model* of S3's semantics, not against S3.
