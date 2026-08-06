# Completed Spec — SPEC-154: Frontend Journey Coverage — Testing the Wires Between Tested Halves

## What was completed?

Every flow a user can actually perform now has at least one test that performs it. The gap this
spec closed was structural, not sloppy: a hook tested with `renderHook`, a component tested with a
stub callback, and nothing testing the wire between them.

**1499 → 1539 tests**, across three PRs (#380 phases 1–2, #381 phases 3–4, #382 phases 5–7).

### The journeys that did not exist

- **FR-001 — table share.** Rail menu → dialog → submit → service → toast, structured on the
  SPEC-145 refresh block. Covers a renamed destination table, a shared-space recipient, the mapped
  failure text as *rendered* text, and no share item for a view. One test drives the share from a
  **shared-space** rail node: in the default fixture the personal DB name *is* the username
  (SPEC-033), so `source.database === 'alice'` was satisfied by reading the rail node, reading
  `auth.user.username`, or hard-coding it — three different programs, one passing assertion.
- **FR-002 — authentication.** Sign out, Sign in and Create account had never been clicked by any
  test; the `role="alert"` auth banner had never been rendered. All four now are, and the sign-out
  test drives a real context transition so the *resulting UI state* is asserted, not only the call.
- **FR-003 — collision resolution.** Overwrite / Rename / Cancel for a single upload, Overwrite all
  / Cancel for a batch **copy and move**. Each asserts the retry's `overwrite` flag *and* the
  user-visible result. Resolution used to be invoked on hook internals.
- **FR-004 — an upload to completion.** The real `UploadQueueProvider` behind the real `UploadList`:
  queued → uploading (progress at `aria-valuenow` 50) → Uploaded; the Failed state with the mapped
  message; cancel in flight and cancel while queued; the concurrency gate.
- **FR-005 — pagination.** `'Next'` did not appear in the workspace suite and the fixture could not
  enable it (`nextToken` was hard-coded `undefined`). Next threads the token, Prev returns from
  cache, rows-per-page re-fetches and carries across **real** result tabs, column width survives a
  tab switch, the layout preset persists.
- **FR-006 — the remainder.** Remove-member driven from the drawer against the **second** of two
  spaces (the `managing.name` closure is what goes wrong here); a populated partition-key array
  asserted field by field; a notification link **followed** into the report route; and the
  dev-unauth bypass, which had zero coverage.

### The cleanups

- **FR-007.** The four files that built a bare `new QueryClient()` left retries **on**, so a mocked
  rejection waited for a backoff; they and six more go through `renderHookWithProviders`. Bespoke
  trees that remain each carry a written reason.
- **FR-008.** `fileBrowser.a11y.test.tsx` dropped `vi.mock('./useFileBrowser')` — the hook §21 names
  explicitly — and axes `DestinationPicker` against the real tree, on the **driven** container after
  the listing resolves. `useCopy`'s mock factory stopped re-implementing `validateFolderName`; the
  copy it shipped **omitted the control-character rule entirely**.
- **FR-009.** The `describe('at a narrow viewport')` that never changed the viewport is renamed to
  what it pins, and its one case with an accessible contract is asserted through it (the label's
  `w-full` is kept *alongside*, not replaced — it is what makes the target hittable). A redundant
  `animate-spin` beside `toBeDisabled()` is gone. Class assertions that remain pin SPEC-095's
  documented one-tree contract and say so.

  **A deletion here was wrong and was reverted during review.** The `ConnectionsPage` header
  assertion was removed on the grounds that `PageLayout.test.tsx` owned it. It does not:
  `PageLayout.test.tsx` asserts the stacking only in a render that passes `stackActionsOnMobile`
  *itself*, and the prop defaults to false — so it pins "the prop works", never "this page opts
  in". Deleting it left `ConnectionsPage.tsx`'s bare `stackActionsOnMobile` unpinned, and a
  tidy-up that dropped the prop would have kept every file green while the heading and the New
  button collide at 400px. The DOM chain stays, with FR-009 AC3 explicitly yielding to AC5.

## The one production change, and why it was allowed

`MembersList`'s Remove button gained `aria-label={\`Remove ${member.username}\`}`. Every row rendered
a button whose accessible name was just "Remove", so a screen-reader user hearing the control list
got N identical buttons with no way to tell which member each acts on — and no test could target one
without an index. This is the spec's stated exception (a component that must expose an accessible
name to be testable at all): additive, appearance unchanged, and recorded here. Four existing tests
moved to the member-specific query, which also retired three `.closest('li')` reaches.

## Findings filed rather than fixed

**1. FR-004 AC3 described behaviour the app does not have, and should not.** It said cancelling an
in-flight upload "removes it". `UploadQueueProvider` transitions an in-flight cancel to a terminal
`Cancelled` row and drops only a *queued* item — which is better, because a row that vanishes gives
no confirmation the cancel took. **The AC was corrected in the spec file**; both halves are asserted
as they behave.

**2. Column-width persistence is bounded by the query cache, not by the session.**
`useColumnWidths`' docstring promises widths survive "query-tab switches within the session". They
survive as long as the results query stays cached: switching tabs sends `displayExecutionId` to
null, the query key changes, and the old execution is left with no observer. Production uses
TanStack's default 5-minute `gcTime`, so a user who works elsewhere for six minutes and returns
silently loses their widths — same `columnCount 1 → 0 → 1` re-seed. A rows-per-page change re-keys
the query and does the same. Not fixed here (tests only); worth a follow-up if it matters.

**3. A harness artefact that nearly became a pinned "feature".** The shared `createTestQueryClient()`
sets `gcTime: 0`, which made the column width reset on every tab switch under test. Asserting that
would have pinned the test client's behaviour as the product's. That test uses a realistic `gcTime`
and explains the mechanism.

**4. Three a11y files depend on a warm cache across two renders**, and `createTestQueryClient()`'s
`gcTime: 0` broke that premise mid-spec — they passed only on GC-timer timing, one `await` away from
axing an empty loading state and reporting no violations. Reverted to a default-`gcTime` client with
the reason written down.

## Deviations from the plan

- **Six phases landed as three PRs** (1+2, 3+4, 5+6+7) rather than one each. Each PR is
  independently landable and independently reviewed, which is what "its own PR" was protecting.
- **FR-005 AC6** ("reduce the hook test that now duplicates") was consciously not done.
  `useQueryResults.test.ts` keeps its cases behind a scope note: it asserts `pageIndex`,
  `hasPrev`/`hasNext`, row numbering across pages of unequal length, the execution-id reset and the
  per-execution page memory — none of which the workspace can see. §21 forbids testing the same
  *logic* at two levels, not the same *flow* with each level asserting what only it can.
- **The dev-unauth guard is asserted BOTH ways, and an earlier draft got this wrong.** That draft
  claimed "there is no runtime seam" and tested source text only. There is a seam: `vite.config.ts`
  defines no `DEV`, so `import.meta.env.DEV` is a live property under Vitest and
  `vi.stubEnv` + `vi.resetModules()` + a dynamic import genuinely re-evaluates a module-scope const.
  The security claim is now **behavioural** — with `DEV` false and the flag on, `listFiles` still
  resolves credentials — with the opposite direction asserted too, so the test cannot pass by the
  bypass being broken outright. The source assertions remain for `ProtectedLayout` and `FilesPage`,
  which compute the same expression and which a render-level test would only cover one at a time;
  sources arrive via `?raw` and the site list is checked against `import.meta.glob`, so a fourth
  ungated reader fails the suite.

## Verification

`npx vitest run` (183 files, 1539 tests), `npx tsc -b`, `npx eslint src --quiet` and
`npm run format:check` all green locally, and on CI for each of the three PRs. Every new guard was
additionally verified to **fail** against the defect it targets, by breaking the production code and
re-running: the dev-unauth `DEV` conjunct, the rail-node share provenance, the `ProtectedLayout`
prefetch effect.

## Known limits of what shipped

- **The notification-link pair does not reach the producer.** The tests pin the link's shape to
  `App.tsx`'s declared pattern, but the link is minted in Python
  (`lambdas/data-quality-common/dqcommon/notify.py`, `_REPORT_ROUTE = "/data-quality"`), and nothing
  joins the two languages. A rename on either side is caught only on its own side.
- **The route-pattern check does not pin which element the route renders.** Swapping
  `DataQualityReportPage` for a redirect would keep both tests green.

## Component inventory / help

**No new reusable service, hook or component** — no inventory row is owed. **Nothing user-facing
changed**: the only production edit is an `aria-label` that alters the accessible name of an existing
control and nothing a sighted user sees, so no Help & guides update is owed.
