# Completed Spec — SPEC-258: Files, Notifications and Help Move Onto the App Router

The build landed in one PR on 2026-11-15, #989 (`cde0c104`), after SPEC-256 read Completed and behind
SPEC-259, 260 and 261, so it was the last of the four area moves. `main` was green on its merge and its
Deploy SPA image run (43673208680) put it on the web tier, which other sessions held on. The live
checks ran in Andrew's signed-in Chrome in two windows that no deploy crossed: 04:41 to 04:42 UTC on the
image of `900c64f5`, and 12:01 to 12:02 UTC on the image of `923f32c3`. This spec neither switched the
tier on nor off: it was on when the checks began, and SPEC-262 still held it when they ended.

## What was completed?

- **Three App Router pages.** `src/app/(signed-in)/files/page.tsx`, `notifications/page.tsx` and
  `help/page.tsx`, each a client component that reaches its area's view through `next/dynamic` with
  `ssr: false`, with no loading fallback and no props.
- **The three area records say `'app'`**, so the route table no longer builds their routes and the
  seam sends every navigation that changes the path into or out of them through Next's router.
- **App Router proofs in the split tests** (`src/routes/areas/files.test.tsx`, `notifications.test.tsx`,
  `help.test.tsx`), below the inherited mocks. They cover:
  - each page served by its own file (`'as-recorded'`);
  - an upload across a round trip to Query on the catch-all;
  - the space switch, through neither router call and with no second mount of the page;
  - a notification's links to a Files folder and to a report, with Data quality on either router;
  - Help's sections with Back and Forward;
  - the contextual panel's link landing at its section, with the hash in the address.

  Each was shown red against a planted defect.

### Deliberate deviations

- **Two acceptance criteria were amended while building.** The arc's orchestrator asked for this after
  SPEC-256's completion review: `renderApp` serves every area from the catch-all unless a test names
  it. So the page tests read the records as recorded, and the inherited tests that should exercise
  these areas name their router as `'app'`. The amended tests are Files' render helper and its three
  sign-out tests, Help's protected-route test, and "serves /notifications inside the shell".
  "The inherited split tests pass unchanged" no longer described them.
- **The browser's own reload prompt was not seen.** The upload was running and the reload was asked
  for, but no one was at the keyboard. SPEC-256's owed row in `docs/testing/owed.md` carries it for
  both specs.
- **The tier was not switched by this spec.** Under the arc's holders rule, a session switches it off
  only when no other session holds it.

## What changed from earlier specs?

- **Navigations into and out of the three pages now fetch the page**, and scroll to the top, as
  SPEC-256 said the area moves would. A space switch on Files and a section change on Help remain
  native writes that fetch nothing.
- **A first visit to an App Router page announced the previous page's title** to screen readers.
  This spec's second diff review predicted it from the code, and it was measured live on the image
  of `cde0c104`, before the deploy that ended the first attempt.
  Next's announcer read the document title before the lazily loaded view had set its own. It was
  fixed in #998 (`923f32c3`), which sets each page's title as the page mounts, this spec's three
  among them. The second live window confirmed the fix: a first visit to Help read
  "Help & guides — Data Quarry".

## Verification

- **Local gates.** Every local gate passed by exit code on the rebased commit: the formatter, both
  linters, both suites (3,735 Vitest tests and the Lambda suite), mypy, `npm run build` (which lists
  `ƒ /files`, `ƒ /notifications` and `ƒ /help`), and every step `ci.yml` runs.
- **`next start`, signed out and in.** It answered 200 on all three pages and sent a signed-out
  `/files` to `/`. Signed in on localhost, it kept one shell element, one `/config.json` fetch and one
  document load across Files, Query, Notifications, Help and Files, with Back and Forward across both
  routers.
- **Live (FR-003).** The rows are in `docs/testing/e2e.md` §4.2, §4.12 and §4.13, and
  `docs/testing/sessions.md` has the run. These passed:
  - two 704 MB uploads went from 6–7% to 24–26% across Query and back, and each page kept its own title;
  - the space switch fetched only the API's listing;
  - the skip link, then Query, then Back showed Files;
  - the folder `spec 256 table/` opened from Query's **View source files**, and Back returned to Query;
  - a notification's link opened `e2e_1113/`;
  - Help's sections went Back and Forward.
- **Help & guides.** No change was needed. The guides name these pages' tabs, the bell and the help
  panel, all of which work as before, and say nothing about which router serves a page.
