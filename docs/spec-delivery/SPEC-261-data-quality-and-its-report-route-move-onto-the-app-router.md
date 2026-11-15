# Completed Spec — SPEC-261: Data Quality and Its Report Route Move Onto the App Router

The build landed as one PR, #984 (`90618bbb`), on 2026-11-14, after SPEC-256's completion (#983).
The live checks ran the same day on that image, with the web tier switched on through CI and off
again afterwards (`docs/testing/sessions.md`). Nothing changes for a user: the runs page and the report look and behave
as before, now served by App Router pages.

## What was completed?

- **Two App Router pages**: `src/app/(signed-in)/data-quality/page.tsx` and
  `src/app/(signed-in)/data-quality/[space]/[requestId]/page.tsx`. Each is a client page that reaches
  the area's view (`DataQualityView`, `DataQualityReportView`) through `next/dynamic` with
  `ssr: false`, with no loading fallback and no props. The report reads `space` and `requestId` through
  the seam's `useParams`, decoded.
- **The record**: `src/lib/navigation/areas/data-quality.ts` says `'app'`, so the route table stops
  building both routes. The view, the flag gate and the report page are unchanged.
- **Tests** in `src/routes/areas/data-quality.test.tsx`, rendering the real views through `renderApp`
  with `routers: {'data-quality': 'app'}`:
  - the runs list, and a run's report and Back;
  - an encoded space (`a%40b%20c`) read as `a@b c`;
  - no report read with the flag off or before a late flag answers;
  - the link wait reading once, and not again on Back onto the entry;
  - a notification's link from Notifications on either router.

  Each guard was mutation-checked, and the page stand-ins became a switch so the inherited scenarios stay as written.

### Deliberate deviations

- **FR-001's test criterion was amended while building.** SPEC-256's completion made the catch-all the
  harness default for any area a test does not name. The new tests name the area's router as `'app'`,
  and the inherited scenarios use `routers: 'as-recorded'`. Without those, they would keep testing the
  catch-all after the move.
- **The malformed-escape 500 was left to SPEC-263.** `/data-quality/%E0/r1` answers 500 with nothing
  logged under `next start`, and so do `/files/%E0`, `/%E0` and `/_next/%E0`. None of those responses
  carries the proxy's headers, so Next fails in its own routing before the proxy or any page runs. A
  page file has no way to answer 4xx there.

## What changed from earlier specs?

- The data-quality routes leave `src/routes/table.tsx`'s output; neither file was edited (SPEC-256's
  record-driven table).
- A percent-encoded spelling of the static path (`/data%2Dquality/…`) no longer opens the page. Next
  does not decode a static segment, and the seam still claims that spelling for the shell, so it now
  shows the 404 inside the shell where react-router decoded it. No link builds it. It was passed to
  SPEC-263, which replaces the seam's matcher.

## Verification

- **Local gates**, all green by exit code on the rebased branch: the formatter, both linters, the
  portal suite with coverage, pytest, mypy, `npm run build` and the bundle check, plus every validator
  `ci.yml` runs.
- **Production build**: `next build` lists both routes as dynamic, and `next start` answers each with
  status 200.
- **Reviews**: the second diff review compared the pages with `/files` under `next start` and the
  standalone server. The headers, the per-request nonce and `no-store` match. The HTML is identical for
  a known and an unknown space, apart from Next's escaped params echo.
- **Live, on the deployed image**: all of FR-003, plus an upload kept in the shell's queue across Files,
  then Data quality, then Files, all in one document. The upload was 9 MB and started at 0 B; Data
  quality rendered 1.06 s later, so whether it was still in flight then is not proved.
- **The tier**: switched on for the checks (Deploy Infrastructure dispatch 43613021039), then off
  again through the repository variable once no other session held it (dispatch 43668180729:
  *"0 added, 0 changed, 55 destroyed"*, every destroy under `module.network[0]` or `module.spa[0]`).
