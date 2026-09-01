# The browser

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries the one-line digest of each entry. This file holds the reasoning, the constraints and the
explicit "do NOT build" fences for one area. **Read the entry you need, not the file.**

## Contents

- [State](#state)
- [Responsive (SPEC-095)](#responsive-spec-095)
- [Help & guides (SPEC-074)](#help--guides-spec-074)
- [User-facing error messaging (SPEC-106)](#user-facing-error-messaging-spec-106)
- [`components/` may not import from `features/` (SPEC-155)](#components-may-not-import-from-features-spec-155)
- [Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)](#dialog-enter-to-submit-fires-from-one-field-never-from-the-form-spec-155)
- [Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)](#escape-dispatches-by-tree-depth-not-per-component-opt-out-spec-155-supersedes-closeonescape)
- [The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)](#the-byte-formatters-share-a-unit-ceiling-and-it-goes-to-tb-spec-155-fr-007)
- [A display page is not a listing page, and the space selector is gated (SPEC-174)](#a-display-page-is-not-a-listing-page-and-the-space-selector-is-gated-spec-174)
- [The shared layer is extracted before its second consumer exists, and the rule that guards it had to be verified by violating it (SPEC-176)](#the-shared-layer-is-extracted-before-its-second-consumer-exists-and-the-rule-that-guards-it-had-to-be-verified-by-violating-it-spec-176)
- [The key namespace moves with the module, and a prefix is not cosmetic](#the-key-namespace-moves-with-the-module-and-a-prefix-is-not-cosmetic)
- [The producer decides where a type lives, not the consumer](#the-producer-decides-where-a-type-lives-not-the-consumer)
- [`no-restricted-imports` matches the SOURCE STRING, so a sibling rule needs relative patterns](#no-restricted-imports-matches-the-source-string-so-a-sibling-rule-needs-relative-patterns)
- [What did not move, and why](#what-did-not-move-and-why)
- [Geometry is keyed by NAME, NULL is kept apart from empty, and a page nobody watched is not "no rows" (SPEC-180)](#geometry-is-keyed-by-name-null-is-kept-apart-from-empty-and-a-page-nobody-watched-is-not-no-rows-spec-180)
- [One `apply` per gesture, a numeric refusal at the INPUT, and a failure that keeps the rows (SPEC-181)](#one-apply-per-gesture-a-numeric-refusal-at-the-input-and-a-failure-that-keeps-the-rows-spec-181)
- [A palette is measured, not chosen; a link's encoding depends on where the value lands (SPEC-184)](#a-palette-is-measured-not-chosen-a-links-encoding-depends-on-where-the-value-lands-spec-184)
- [The palette is a bounded token set, because the contrast criterion is otherwise unassertable](#the-palette-is-a-bounded-token-set-because-the-contrast-criterion-is-otherwise-unassertable)
- [The dark palette is derived under the harness, not chosen, and the theme boundary put four fences there (SPEC-210)](#the-dark-palette-is-derived-under-the-harness-not-chosen-and-the-theme-boundary-put-four-fences-there-spec-210)
- [The URL transformer's encoding is position-dependent, and both simple rules are wrong](#the-url-transformers-encoding-is-position-dependent-and-both-simple-rules-are-wrong)
- [A rule's `scope` is a field the spec's model did not have](#a-rules-scope-is-a-field-the-specs-model-did-not-have)
- [The raw value drives everything, and the transform lives at the cell](#the-raw-value-drives-everything-and-the-transform-lives-at-the-cell)
- [A link in a grid is not a tab stop, and the app must not manufacture backtracking](#a-link-in-a-grid-is-not-a-tab-stop-and-the-app-must-not-manufacture-backtracking)
- [A hidden column is still part of the row](#a-hidden-column-is-still-part-of-the-row)
- [A stored formatting block is discarded WHOLE](#a-stored-formatting-block-is-discarded-whole)
- [Copy is the selection-shaped tool and export is the result-shaped one, and reusing the save path meant moving it (SPEC-185)](#copy-is-the-selection-shaped-tool-and-export-is-the-result-shaped-one-and-reusing-the-save-path-meant-moving-it-spec-185)
- [The two ways out divide on the line the whole arc divides on](#the-two-ways-out-divide-on-the-line-the-whole-arc-divides-on)
- [A NULL and an empty string stay apart in all six formats, and quoting is what disambiguates the WORD](#a-null-and-an-empty-string-stay-apart-in-all-six-formats-and-quoting-is-what-disambiguates-the-word)
- [A discontiguous selection copies as a rectangle, and a SQL INSERT names a placeholder](#a-discontiguous-selection-copies-as-a-rectangle-and-a-sql-insert-names-a-placeholder)
- [Reuse required a MOVE, and the move closed a live flag defect](#reuse-required-a-move-and-the-move-closed-a-live-flag-defect)
- [Every guide row before this spec lived in the section the Help page opens on](#every-guide-row-before-this-spec-lived-in-the-section-the-help-page-opens-on)
- [A default that an empty string can defeat is not a default (SPEC-186)](#a-default-that-an-empty-string-can-defeat-is-not-a-default-spec-186)
- [`??` does not fall back on `''`, and a helper returning `''` is a trap for every consumer](#-does-not-fall-back-on--and-a-helper-returning--is-a-trap-for-every-consumer)
- [A refusal announced after the confirm is worse than no affordance at all](#a-refusal-announced-after-the-confirm-is-worse-than-no-affordance-at-all)
- [jsdom has no layout, so a containment property must be arithmetic](#jsdom-has-no-layout-so-a-containment-property-must-be-arithmetic)
- [A procedure that cannot produce its claimed outcome invites a false bug report](#a-procedure-that-cannot-produce-its-claimed-outcome-invites-a-false-bug-report)
- [A persistent in-flight surface is NEW scope, with no precedent here (SPEC-190)](#a-persistent-in-flight-surface-is-new-scope-with-no-precedent-here-spec-190)
- [There is no progress percentage, and there cannot be one (SPEC-190)](#there-is-no-progress-percentage-and-there-cannot-be-one-spec-190)
- [The kill switch is a flag key, and it is the sixth (SPEC-190)](#the-kill-switch-is-a-flag-key-and-it-is-the-sixth-spec-190)
- [Help is read where the work is, and a gated page's help is gated by derivation (SPEC-207)](#help-is-read-where-the-work-is-and-a-gated-pages-help-is-gated-by-derivation-spec-207)
- [One split, two clamp domains, and the pair has to agree (SPEC-209)](#one-split-two-clamp-domains-and-the-pair-has-to-agree-spec-209)
- [The divider needs a click path, because a drag is not an alternative to itself (SPEC-209)](#the-divider-needs-a-click-path-because-a-drag-is-not-an-alternative-to-itself-spec-209)

## State

TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)

## Responsive (SPEC-095)

Mobile-first with **two custom breakpoints** in `index.css` `@theme` — Tailwind defaults (`sm`/`md`/`lg`/`xl`/`2xl`) reset to `initial`, only `tablet:` (≥900) / `desktop:` (≥1300) compile; unprefixed = mobile. Reflow via responsive utilities on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); a separate markup branch is allowed only for genuine structural divergence (Files table vs card list) or mount-cost/mobile-chrome cases. One viewport hook `useBreakpoint`/`useIsMobile` (`src/lib/`) for **mount-gating only**, never styling. Mobile nav = Header hamburger → `AppNavDrawer`; shared `Menu` + `MobileActionBar` primitives; `Modal`/`Drawer` gain small-screen presentations. Detail: `apps/portal/info/best-practices/react/react.md` §20.

## Help & guides (SPEC-074)

> **Superseded in part by SPEC-207:** the header icon opens a **panel over the current route** on
> the six routes that have one, and stays a link to `/help` everywhere else. The page, its section
> sidebar and its hash addressing are unchanged. Full entry below, *Help is read where the work is*.

In-app how-to surface — a header help icon → `/help` page (Files/Query left-rail shell: section sidebar + accordion guide cards, active section in the URL hash). **Presentation + authored content only** (no data layer/network/AWS/IAM/infra/env/deps). Content is a **static, code-grounded** module (`features/help/helpContent.ts`) documenting only shipped, wired-end-to-end behavior (FR-005) — **keep it in sync via the completion-ritual step 9** whenever a user-facing feature lands/changes.

## User-facing error messaging (SPEC-106)

Raw AWS/Cognito/Athena text is **never** shown to a user. One SPA mapping module (`lib/errorMessages.ts` `toUserMessage`) is the single source of error wording — app code → AWS/Cognito name → Athena pattern → generic "Contact the Administrator" fallback; never render `error.message` directly (route it through the mapper at the code-in-scope boundary). App-level `ToastProvider`/`useToast` + `ErrorBanner` replace per-page toasts; dev-only original-error log (`import.meta.env.DEV`). Lambda control planes (tb/tscommon, shared-space create/delete) emit friendly failure notifications + cache `reason`, keeping raw text in logs + the SFN/registry record. Detail: `spec-delivery/SPEC-106`.

## `components/` may not import from `features/` (SPEC-155)

`features/query/` had become a shared layer nobody declared: `components/ToastProvider` and
`components/Sidebar` imported from it, and five sibling features pulled `CATALOG_IDENTIFIER_RE`,
`Connection`, `isConnectionUsable` and `useConnections` out of it. That direction is backwards —
`components/` is the shared presentation layer that features compose, so it cannot depend on one.

The fix moved each shared thing to where its direction is correct: `Toast` to `components/`, the
identifier rule to `lib/catalogIdentifier.ts`, and the connections domain — `Connection`,
`ConnectionKind`, `isConnectionUsable`, `useConnections`, `connectionStatusLabel`, plus the two nav
surfaces `Sidebar` and `SpacesList` — into a new `features/connections/`.

**The rule is enforced, not documented.** `eslint.config.js` bans `features/**` imports under
`src/components/**`. Two things are exempt, both deliberately:

- **Tests.** Integration-style tests mount real features by design (`react.md` §21), so the rule can
  only produce noise on that glob.
- **`Header.tsx` and `ProtectedLayout.tsx`.** These are app *chrome*: they exist to wire features
  into the shell, so composing features is what they are for. Bringing them under the rule needs a
  separate app-shell layer, which is a re-layering rather than an import fix. They are **named in
  the config** rather than left as a silent violation, so a third such file requires an explicit
  edit to that list. Everything else that was on the list has been moved out of `components/`.

Two residuals, both recorded rather than hidden:

- `features/connections/useConnections.ts` still reads `queryKeys.connections` from
  `features/query/queryKeys.ts`. Feature-to-feature is allowed, and splitting the key factory would
  change key *values* that two tests assert.
- ~~**`lib/queryClient.ts` imports `features/file-browser/fileBrowserKeys`**~~ — **CLOSED 2026-08-09.**
  It was a lower layer importing a feature, and a strictly worse inversion than the one this decision
  targets. `invalidateListing` moved to `features/file-browser/invalidateListing.ts`, beside the key
  factory it builds from; `lib/queryClient.ts` now owns only the client and imports no feature.
  `features/query`'s save-results flow reaches it through the file-browser barrel — feature-to-feature,
  which is allowed, and which was already true transitively through `lib/`.

  **The rule widened with it**, to `src/lib/**` and `src/hooks/**`. That was the point of the move:
  fixing the one file without widening the glob leaves the next one to be found by hand.

  **The test exemption is load-bearing on `src/lib/**`, not a formality.** `lib/support.test.ts`
  imports seven feature service modules — it is the consolidated lib suite, and testing a lib helper
  against real feature callers is what it is for. Without `src/lib/**/*.test.{ts,tsx}` on the
  exemption list the rule reports **6** violations there and `npm run lint` fails. The
  `src/hooks/**` test glob is inert today (nothing under `src/hooks/` imports a feature) and is
  carried for symmetry. Non-test files in both directories were clean, which is what made the
  widening a one-line glob change rather than a migration.

  The mock count in the original note was wrong — **two** test files mocked the module by path
  (`fileOpHooks.test.ts`, `UploadQueueProvider.test.tsx`); the other four merely imported it. That
  overstatement is most of why this looked expensive enough to defer.

  **What the rule still does not catch:** a dynamic `await import('../features/…')`. Base
  `no-restricted-imports` only sees static import/export forms — type-only imports, `export … from`
  and deep relative paths are all caught. The hole predates the widening and is unchanged by it.

## Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)

`FormDialog` (SPEC-155 FR-002) turned eleven hand-written dialog chromes into one. Its body is a real
`<form>` with a `type="submit"` primary button — but **the browser's implicit submission is
suppressed on purpose**, and Enter submits only from the field named by `submitOnEnterRef`
(defaulting to `autoFocusRef`).

Adopting the form naively is the trap: implicit submission fires from *every* text input in a form.
The dialogs being consolidated each had exactly one field that submitted on Enter; handing it to all
of them filed a table build from a partition-key row the user was still editing — **measured before
the fix, not hypothesised**. A radio group is the same shape: arrow keys move a choice, Enter would
commit one the user never made.

A child that already handled the key wins over both, so a combobox's Enter-to-commit still works
inside a dialog.

## Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)

`useEscapeKey` now maintains a module-level registry of enabled handlers, each tagged with its
`EscapeLayer` depth, and dispatches Escape to **the innermost one only**. Nested dialogs are correct
by construction.

What this replaces: `Drawer`'s `closeOnEscape` prop, a per-component opt-out that every new nesting
had to remember. It is **gone**, not deprecated — it had no consumer left, and a prop nobody sets is
a rule nobody applies. `Modal`'s `dismissible={false}` now **swallows** Escape (`useEscapeBlock`)
instead of letting it fall through and dismiss the layer beneath — the case `dismissible` could not
express before without also disabling backdrop dismiss.

This sits beside, and does not contradict, the settled finding that `stopPropagation` from a React
handler DOES stop `useEscapeKey`'s `document` listener (SPEC-147, measured). That is still true: a
child that stops the event never reaches the registry at all. Depth-based dispatch decides between
layers that *do* reach it.

## The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)

`fileBrowser.format.formatSize` and `query.format.formatBytes` are documented as "deliberately not
merged", and on `undefined` handling that is defensible. On the **unit ceiling** it was not: a 3 TB
object read `3072.0 GB` in the file browser and `3.0 TB` in the query status bar, from the same
number, on two screens of one app.

**Decided: unify the ceiling at TB.** This is a **user-visible change**, which is why it is a
decision and not a refactor — SPEC-155's scope otherwise forbids one. The two functions stay
separate for their `undefined` handling; only the unit table is now shared. Silently keeping both was
explicitly not an outcome the spec allowed.

## A display page is not a listing page, and the space selector is gated (SPEC-174)

**Decision (2026-08-11).** The saved-queries surfaces page over **filtered rows**, never over S3
keys, and the two counts do not track each other. SPEC-173's store returns only the top-level
`.sql` files of a folder it deliberately left ordinary, so one `ListObjectsV2` page of 25 keys can
yield 25 rows, three, or **zero while more pages remain**. Paging the listing directly would render
a folder of two hundred CSVs and one saved query as an empty list with a "Load more" the user has
to guess the meaning of.

`useSavedQueriesPager` therefore **keeps fetching while the listing is truncated and it holds fewer
rows than the page in view needs.** Two bounds make that safe and neither is optional: the
listing's own end (`hasNextPage` goes false), and **an error stops the fill** — a failed
`fetchNextPage` leaves `hasNextPage` true and `isFetchingNextPage` false, which is exactly the
condition the effect fires on, so without the error guard one failure spins forever.

While it fills, the surface reads as **loading**. `isFilling` (no rows yet, pages remain) is a third
state beside `isEmpty` (listing exhausted, no rows) and the first-page load, because the two
alternatives are both wrong: an empty state that a fetch is about to contradict, and a pager
reading `0–0 of 0+`. The label carries `Z+` while pages remain for the same reason — S3 reports no
total, and `24` and `at least 24` are different claims.

**The window advances past the loaded rows and the clamp holds the view.** Next sets the index
beyond what exists; `safeIndex` clamps it to the last real page while the fill runs, and the new
page lands when its rows arrive. That one mechanism also covers a delete emptying the last page,
which is why FR-005's "move to the new last page" needed no code of its own.

**The selector is gated, deviating from FR-001's "exactly the spaces `useQuerySpaces()` returns".**
With `sharedWorkspaces` off it offers **My files alone**. SPEC-163 already filters the connections
list and the schema rail on that flag; a dropdown still naming a colleague's space, moments after
every other shared-workspace surface disappeared, reads as a bug rather than a policy. The filter
is applied in `QueryWorkspace` — at the **view**, never in `useQuerySpaces` and never in a service
(SPEC-162 FR-006) — and it needed no new fallback: `useSavedQuerySpace` takes its spaces as a
**parameter** and already resolves an id naming nothing offered to personal, so a revoked
membership and a flag turning off travel the same path. It is a **new registry row** (*Shared
spaces in the saved-queries selector*), not a widening of *Shared databases in the schema rail*:
that row gates the connections the rail browses, this one gates a control reading a different hook,
and SPEC-163's rule is one surface per row. Its reach-recipe opens the **real drawer** on the
**real workspace**.

## The shared layer is extracted before its second consumer exists, and the rule that guards it had to be verified by violating it (SPEC-176)

`features/query/` had become the portal's catalog layer by accident: the Glue reader, the Athena
start/poll/results/cancel layer, the space list, the results pager, the background row-count walk and
the column-width store all lived inside a feature that owns an editor and a tab strip. The Data
Explorer (SPEC-179 onward) needs every one of them.

**The extraction leads the arc rather than following it.** Building the Data Explorer first and
factoring afterwards would mean writing `import {useSchema} from '../query/useSchema'` and living
with it — which is exactly the undeclared shared layer SPEC-155 spent a whole spec dismantling, one
directory over. Extracting first costs a large mechanical diff against a codebase where every test
still passes; extracting later costs the same diff plus a second feature's worth of call sites, at a
moment when the pressure is to ship the feature. So `features/catalog/` exists with **no** user-
visible change, no new behaviour and no altered AWS call — the change most likely to go wrong,
made when nothing is riding on it.

## The key namespace moves with the module, and a prefix is not cosmetic

`catalogKeys` is rooted at `['catalog']`, not `['query']`. Keeping the old prefix would have been a
smaller diff and is the wrong call: a key namespace naming a feature the module no longer belongs to
is the same hidden coupling the extraction removes, and it would make a future
`invalidateQueries({queryKey: queryKeys.all})` in the Query workspace silently reach into the Data
Explorer's caches. Cache keys are in-memory and per session, so the change needs no migration and the
spec asserts none.

## The producer decides where a type lives, not the consumer

`useSchema.ts` moved carrying an import of `DatabaseSchema` from `sqlCompletions.ts`, which stays
behind — FR-001's "no catalog module imports from `features/query/`" broken by the first file moved.
`DatabaseSchema` is `{database: string; tables: GlueTableSummary[]}`: it had been declared beside the
completion provider that consumes it rather than the hook that produces it, and nobody had reason to
think of it as domain until the layers were separated. It is in `catalog.types.ts` now. Where a
producer sits in a lower layer than its consumer, the type belongs with the producer.

## `no-restricted-imports` matches the SOURCE STRING, so a sibling rule needs relative patterns

The SPEC-155 rule forbids `components/`, `lib/` and `hooks/` importing `**/features/**`, and it works
because those layers sit *above* `features/` and must name it: `'../features/query/queryKeys'`. The
sibling clause written the same way — `'**/features/query/**'`, `'**/features/data-explorer/**'` —
resolved onto exactly the right files and **caught nothing**, because one feature reaches another as
`'../query/queryKeys'`, which contains no `features/` segment at all. The load-bearing patterns are
the relative ones (`'../query'`, `'../query/**'`, `'../../query'`, `'../../query/**'`, and the same
four for `data-explorer`); the `**/features/…` globs stay for any path written the long way.

This is why FR-006 required the rule be **verified by committing a violation in each direction and
observing the failure**, not by reading the config. A rule that resolves onto the right files, prints
a correct `--print-config` and is written in the same shape as a working one is not a rule that
fires. `features/data-explorer/` is named in the rule before it exists, so the first file created
there lands under a guard already known to work.

**Tests are not exempt from this clause**, unlike the shared-layer rule above it. That exemption
exists because integration-style tests mount real features by design (react.md §21) — but a Query
test importing the Data Explorer is the coupling itself, not a mount of the tree under test.

## What did not move, and why

`SchemaBrowser`, `DatabaseNode`, `QueryResultsTable` and every dialog stay: the Data Explorer's
picker and grid are different components with different requirements, and SPEC-155's precedent is to
move the *domain*, not every consumer. The display page-size constants stay too —
`MAX_RESULTS_PAGE_SIZE` is a SPEC-087 workspace preference, not a property of Athena. `formatBytes`
went to `lib/format.ts` rather than into `catalog/`: it is a pure formatter with no catalog domain,
and both features render the same scanned-bytes figure.

## Geometry is keyed by NAME, NULL is kept apart from empty, and a page nobody watched is not "no rows" (SPEC-180)

The grid replaces SPEC-179's placeholder wholesale, and three of its decisions reach outside the
feature.

**Column geometry is keyed by the column NAME, which is why it is not `useColumnWidths`.** FR-001
asks to reuse SPEC-176's width store; that store keys by execution id and column **index**, in
memory, and re-defaults on a column-count change. Every other requirement points the other way — the
spec's own `columnWidths: Record<string, number>`, FR-001 AC7's per-tab persistence through
`sessionStorage`, and FR-006 AC3's "geometry for a column that no longer exists is discarded". Name
keying makes that last one true **by construction**: a width, a pin or a hide belonging to a column
this result set does not contain simply never resolves, where an index would have landed it on
whichever column moved into that position after a re-order or a `GROUP BY`. Stale entries are left
in place rather than pruned, so a re-execution that brings a column back brings its geometry back
too. The catalog's sizing constants and its resize gesture are reused; the hook is not.
`ColumnResizeHandle` itself **moved to `features/catalog/`**, generic over its column key (index for
the Query workspace, name here) — two sibling features now draw result grids and neither may import
the other, so the alternative was the `*Mobile`-style twin SPEC-095 calls a smell.

**A focusable `role="separator"` needs a value, and the Query workspace had been shipping without
one.** axe raised `aria-required-attr` the first time a grid full of handles was driven into a live
state — the violation was always there, but no axe assertion had ever run over a header row carrying
handles. `aria-valuenow`/`aria-valuemin`/`aria-valuetext` now ship with the shared handle, so both
surfaces gain the fix.

**`getQueryResults` stopped collapsing SQL NULL to `''`, because nothing downstream can undo that.**
Athena's Datum omits `VarCharValue` for NULL and carries an empty one for an empty string; the
service mapped both to `''`, so FR-003 AC5 ("an empty string and a `NULL` are visibly different")
was **unbuildable** at the layer that had to satisfy it. Rows are now `(string | null)[][]`. The
Query workspace renders both as blank exactly as before — this is information kept, not behaviour
changed — and SPEC-181's `isNull` filters and SPEC-185's copy both need the distinction. Its cost is
that every consumer of a cell now handles `null`, which the compiler enumerated: six sites.

**A remembered page index outliving its cached pages rendered a result WITH rows as "No rows
returned".** `useQueryResults` keeps a per-execution page position (SPEC-078's result tabs); the
pages behind it are collected once nobody observes that execution for `gcTime`, and the refetch
starts again from page 1. The remembered index then selected a page that was not there, and **an
absent page is indistinguishable from an empty one** — so the pager read `rows: []` with
`isPending: false` and the grid drew the friendly empty state over a full result. The index is now
clamped to the pages actually loaded, only while any are. The neighbouring test named for the page
memory could not have caught it: the test client runs `gcTime: 0`, so it was asserting the transient
index during a refetch rather than a restored position, and it now holds a second observer warm so
the case it is named for is the case it runs.

**`presentation: null` means UNCHOSEN, and that is the whole of FR-007's mobile default.** Below
`tablet` an unchosen tab opens in Record; a tab whose user has chosen keeps that choice at every
width. A non-null default would have had to be picked when the tab is created, by
`useExplorationTabs`, which has no business reading the viewport — and `useIsMobile` would then have
been deciding a persisted value rather than mount-gating one (SPEC-095 FR-008). Record and the grid
share **one** focused row, so switching between them lands where the other left off rather than
where the cursor happened to be.

**The selection model is explicit because two later specs are built on it.** `ranges` is a list of
inclusive rectangles and **the last one is live** — its `from` is the anchor a Shift gesture extends
from, its `to` is the cursor — and a Ctrl/Cmd+click appends a single-cell rectangle that becomes the
live one. Toggling off removes only a rectangle that is exactly that cell, because punching a hole
in a rectangle is not something the model can represent. The count is taken over a **set of
coordinates**, not summed per rectangle, since overlapping ranges are one click away and a sum would
report more cells than the page has. Everything is addressed by (row on the page, column name), so
coordinates are meaningless across a page change — the reset happens **during render**, not in an
effect, because an effect paints one frame of the old selection over the new page's rows, which is
precisely the state AC8 forbids. Cells carry an explicit `role="gridcell"`: a bare `td` inside
`role="grid"` maps correctly only through one HTML-AAM lookup, and several accessibility APIs (and
the test renderer) resolve it statically as `cell`, a role with no selected state.

**Hide, pin and reorder live in a PANEL, not in the header.** SPEC-181 owns the per-column header
menu, so putting them there would have meant building that menu a spec early and rebuilding it a
spec later; the panel is also where the **keyboard alternative to dragging** belongs (Move earlier /
Move later, announced in a live region), since a drag has no keyboard equivalent to inherit. A
cross-block drag — an unpinned column dropped onto the pinned block — is **refused rather than
coerced into a pin**, because inferring a pin from where a drag ended is a mutation the user did not
ask for and pinning has its own control.

## One `apply` per gesture, a numeric refusal at the INPUT, and a failure that keeps the rows (SPEC-181)

This is the spec the Data Explorer exists for, and the only place in it where a user gesture spends
money. Four decisions are worth keeping.

**Every description change goes through ONE `apply`, and that is what makes "one gesture is one
execution" structural.** Four surfaces edit the query — the header menu, filter-by-cell, the
expression bar, the settings dialog — and each of them hands a `Partial<ExplorationQuery>` to
`useExplorationQuery.apply`, which writes the tab's description once; `useExploration` then renders
one statement and the execution cache decides whether it costs anything. Nothing else may write a
description. An apply that changes nothing is a **no-op**, compared with `sameQuery` on a canonical
form rather than field by field, because `filters` and `ordering` are arrays whose order carries no
meaning (priority does) — without that, applying the same filter twice would fill Back with
duplicates of one description. `clearAll` deliberately **preserves `grouping`**: that is SPEC-182's,
and un-grouping a view from a control labelled "Remove all filters" is a change nobody asked for.

> **SUPERSEDED by SPEC-182 (FR-006 AC3): `clearAll` clears the grouping too, and the control's LABEL
> changes with it** — `Remove all filters` becomes `Remove all filters and grouping` while a grouping
> is in force. The concern above was never the clearing, it was the silence; naming the action is the
> other way to keep the same promise. `isEmptyQuery` counts grouping from the same spec, so its
> refusal wording changed with it.

**The hook takes the tabs result rather than reading its own** — a deviation from the spec's
`useExplorationQuery(tabId)`. The history lives with the tab in `sessionStorage` (FR-006 AC3) and
`useExplorationTabs` owns that document, so a second instance would be a second writer to one key,
diverging on the first edit. The tab id still names which tab, because a description and the history
entry it pushes have to be written in **one** update — `updateTab(id, fn)` exists for that; written
through two calls, a tab switch between them files the entry against the wrong tab. For the same
reason there is **no `stage`**: the spec's staging channel is query-only while FR-005 AC3 requires
Cancel to discard the **presentation** changes too, so the settings dialog holds one draft object
containing both halves and `apply` takes the whole staged description. Split in two, half a draft
could survive a Cancel.

**A numeric value is refused at the INPUT, with the renderer's own predicate.** SPEC-178 emits a
numeric filter's value **bare** (Trino does not coerce) and throws `ExplorationRenderError` for a
value that is not a number — and that message names a column and an operator, which SPEC-106 forbids
rendering to anyone. So `isBareNumeric` is exported and both value inputs refuse with it, rather
than each growing a numeric rule of its own that can disagree with the renderer. The same predicate
drives a `Button.disabledReason` on *Filter by this value*, so a numeric column whose cell holds
something unfilterable refuses at the gesture instead of seconds later as a generic failure. The
value itself never reaches SQL unescaped either way: it rides on a `ColumnFilter` and is quoted by
`sqlLiteral` at render time, which is why the whole hazard — a cell containing `O'Brien` filtered by
`=` — is one test and not one code path per surface. Column names are **quoted, never validated**:
`CATALOG_IDENTIFIER_RE` describes names this app CREATES, and a column named `total amount` is
ordinary.

**A failure keeps the last good rows, and Athena's refusal had to be made into an error first.** A
query Athena rejects is not an error anywhere in the plumbing — `getQueryStatus` **resolves**, and
the reason arrives as `stateChangeReason` on a successful poll — so `useExploration` now surfaces a
`FAILED`/`CANCELLED` execution as `{code, message}`, the shape `toUserMessage` maps engine text
from; without it a syntax error surfaced one layer later as "couldn't read the results", a true
sentence about the wrong thing. And `ExplorationResultsRegion` was restructured so the query toolbar
and the expression bar render whatever the results are doing, with `useQueryResults` pointed at the
**last execution whose rows actually arrived** while the current one is failed. A failed apply has
to leave the user somewhere they can correct it, and a toolbar that disappears with the rows takes
the correction with it. The test for this is only meaningful because the failed execution's results
also fail — mocked to succeed, it passed with the fallback deleted.

**FR-006 AC4 needed a mechanism the spec did not name.** "Navigating history never re-runs a query
that failed" cannot come from the cache: SPEC-178 deliberately **evicts** a failed execution on the
way out, so restoring its description would start a fresh one. The tab keeps an in-memory set of
statements seen to fail this session, and a history step onto one **suspends** — `useExploration` is
handed nothing to run and a *Run it anyway* control is the retry. An `apply` always clears the
suspension, because an apply IS the user asking again. The set is not persisted: a failure from a
previous session should not stop this one from trying.

**Cost can only ever be reported, never predicted.** Athena will not say what a query will scan
before running it — no dry run, no `EXPLAIN` byte estimate, and the per-query statistics exist only
once the execution has finished — so a pre-flight "this looks expensive" confirm is **not
buildable**, and the guards are the workgroup's per-query cutoff plus this reporting. A cache hit
**says so** rather than repeating the figure the execution originally scanned, which is true about
the execution and false about the gesture; it is decided by reading the tab's ledger **during
render, before `recordScan` writes to it**, since after that write every execution looks known and
every apply would report itself free.

**A cost is only reportable once the execution is TERMINAL, and the fixtures hid the opposite.** A
`QUEUED`/`RUNNING` poll carries no `Statistics`, so `useExploration` reported a perfectly confident
0 B — and because the per-apply figure is captured once per execution (it must be, to read the ledger
before `recordScan` writes to it), that zero stuck for the life of the query while the running total
beside it said something else. Every test fixture in the feature returned `SUCCEEDED` on the first
call, so the AC's own test passed over a surface that was wrong for every real query. `cost` is now
null until the state is terminal.

Three implementation traps worth naming, because each looked correct and was silent.
`moveSortPriority` stamps priorities from the **array position** after the swap — re-stamping
through the shared "sort by priority, then number them" helper put the two entries straight back,
so the ↑/↓ controls were a no-op the dialog rendered as a success. **State that belongs to a tab
must be keyed by the tab**, and two pieces of it were not: `suspended` froze *every* tab, and the
last-good-execution fallback drew one tab's rows under another's error banner (visible only when the
failing tab had never succeeded — a tab with a good execution of its own falls back correctly either
way, which is why the first version of that test could not fail). And a `Modal` **does not portal**:
`FilterValueDialog` rendered inside a `<th>` would have been confined to that cell's stacking
context and painted under the sticky headers, which nothing in jsdom can see — the region raises it
and the header menu asks.

## A palette is measured, not chosen; a link's encoding depends on where the value lands (SPEC-184)

Everything this spec adds changes how a value *looks* and nothing about what is *fetched*. That is
SPEC-178's rule seen from the other side, and it is now asserted twice rather than promised: a
scripted UI sequence touching every rule and transformer leaves `runQuery` on the tab's opening
execution, and a transitive **import-closure walk** from `renderExplorationSql.ts` proves no module
this spec added is reachable from the renderer at all. The renderer's signature is a promise about
one function; the closure is a property of the whole graph.

## The palette is a bounded token set, because the contrast criterion is otherwise unassertable

FR-002 AC8 asks that every colour pairing meet contrast requirements. Nothing can promise that
about a colour picker, so the model narrows the spec's `foreground?: string` to a five-token union
(`text`, `text-2`, `accent-text`, `success`, `danger`) and its backgrounds to the four `*-soft`
tints, all of them tokens `index.css` already declares — this spec adds none.

**`warning` was measured out of the foreground set.** It clears 4.5:1 on white (5.02) and fails on
the soft backgrounds this spec introduces: **4.49 on `accent-soft`, 4.39 on `danger-soft`**. A
colour that is legible only sometimes is worse than one fewer colour, because nothing at the point
of choosing tells the user which case they are in. The test recomputes the full cross product, the
**sampled gradient** at every step it can quantise to — including the mixed shades between two
tints of different hues, where a "both ends are pale" argument breaks — and the exclusion itself,
so a token that moves reddens CI rather than quietly failing WCAG.

**The surfaces measured against include the SELECTION.** A formatted cell is still selectable, and
an inline background beats the class that paints a selected one — so the cell drops its formatting
fill while selected (`aria-selected` says so either way), and `accent-soft` is one of the three
base surfaces every foreground has to clear.

**Axe cannot carry this criterion.** `color-contrast` is disabled in `test/axe.ts` because jsdom
has no layout engine, so the axe pass over a coloured grid proves its markup and the computation
proves its contrast. Reporting "the axe pass is green" as evidence of contrast would be a claim
that tool never makes.

`FORMATTING_TOKEN_HEX` existed only because a gradient must interpolate values and contrast must be
computed from them; a second test pinned every entry against `src/index.css` itself, since a copy
needs a guard. Vitest resolves a stylesheet `?raw` import **and** a raw `import.meta.glob` to an
empty string (measured), which would have made that guard pass by finding nothing — so it reads the
file, through a one-function ambient declaration rather than by adding `"node"` to the app's
`types` and handing every module in `src/` the Node surface.

> **Superseded in part by SPEC-210 (dark mode).** There is no copy any more, so there is nothing
> for that guard to pin: `formattingTokenHex(theme)` and `formattingBaseSurfaces(theme)` **resolve**
> from `lib/palette.ts`, which is itself pinned to `index.css` by `lib/contrast.test.ts`. The block
> scoping below is now exercised by a real second block rather than only by a synthetic one, and
> the cross product runs **per theme** with the admissible foreground set recomputed rather than
> copied — `warning` is measured out in light and measured back IN on dark, while the offered set
> stays five in both, because a colour a user can pick in one theme and not the other is a rule
> that changes meaning when they switch. Full entry: *The dark palette is derived under the
> harness…* below.

**That parse is scoped to the `@theme` block, and the scoping is the load-bearing part.** A
whole-file `--color-*` match reads every token declaration anywhere in the stylesheet, so the day a
second block appears — which is what a dark theme adds — its values overwrite the light ones and
every contrast assertion goes on passing while measuring a palette the light theme never paints. A
synthetic two-block stylesheet asserts it, because `index.css` cannot exercise the case until that
second block exists.

> **Both of this entry's guards were deleted and restored.** The 2026-08-28 suite reduction
> (`a41bda69`) removed the `index.css` agreement test *and* the sampled-gradient cross product. It
> left `src/test/node-fs.d.ts` with a docstring whose stated *reason* — that the palette has to be
> checked against `index.css` — described a check that no longer existed; the declaration itself
> kept a live consumer in `lib/runtimeConfig.test.ts`, which is why nothing pointed at the gap. And
> it left this entry and `dataExplorer.constants.ts`'s own comment both claiming a guarantee the
> repo no longer held. Restored 2026-08-28. The lesson is about the shape, not the commit: **a copy
> of a source of truth is only as good as the test that pins it, and deleting that test is
> invisible** — the mirror keeps working, the suite stays green, and the three places that promise
> the guard exists go on promising it.

## The dark palette is derived under the harness, not chosen, and the theme boundary put four fences there (SPEC-210)

The rule this project already had — *a palette is measured, not chosen* — is what decides a second
palette too. `lib/palette.ts` declares both themes and every pairing the design uses;
`lib/contrast.test.ts` computes WCAG ratios from those values and fails naming the pair and its
measured ratio, in **both** themes. The dark values are whatever passes it. The harness ran against
the **light** palette first and reproduced every ratio `index.css`'s comments record, which is what
makes it trustworthy for a palette nobody has measured before. axe cannot carry any of this:
`color-contrast` is disabled in jsdom, at both sites in `test/axe.ts`, and the app shell gets one
dark axe pass for markup — the cap is written into that module rather than inferred from absence.

**A completeness guard, not a pairing count.** Every token is either in a pairing or in a named
decorative exemption carrying its reason; a token in neither fails. Measured against the light
palette the four borders are 1.06–1.27, so **any** floor fails the shipped palette — the exemption
is a fact about hairlines, not a convenience, and the list is frozen so "decorative" cannot become
where a failing colour is put. The harness has a deliberately-failing pair asserted to be reported,
because one that silently passes everything is indistinguishable from one that works.

**Four fences the second theme put there, each of which ships green if you get it wrong:**

- **A themed `--shadow-*` is inert.** Tailwind **inlines** an `@theme` shadow value into the utility
  and emits no `--shadow-*` custom property at all (read out of the built CSS), so a dark block
  redefining `--shadow-md` changes nothing while the stylesheet-agreement check beside it passes.
  What survives inlining is a `var()` **inside** the value: each shadow references a
  `--shadow-tint-*`, and the theme overrides the tint. Colours are unaffected — `bg-surface`
  compiles to `var(--color-surface)` and themes itself.
- **One token cannot be both a text colour and a fill.** In the light palette `danger` reads on
  white *and* backs a white button, and `accent-hover` happens to equal `accent-text`. In the dark
  palette those roles pull apart: `danger` has to be light enough to read on a dark surface, which
  leaves it too light to carry white. So the one danger BUTTON gained `--color-on-danger`, and
  `accent`/`accent-hover` are measured as white-on-the-fill rather than as text — which is the
  pairing the design actually uses, verified by grep before the pairing list was written.
- **A fixed brand surface has to be made fixed.** The landing call-to-action strip was `bg-accent`
  with `text-accent-text` buttons; both theme, and in the dark theme the label goes light and
  vanishes against its white button. Its six colours are now plain custom properties declared
  outside `@theme` and outside every theme block, declared once more in `palette.ts`, pinned
  together by a test and measured as four raw pairings.
- **A hex-only sweep misses the colours that matter most.** `text-gray-900` is as unreachable by a
  theme as `#15191e` and invisible to a sweep looking for `#`. Three of them sat on the 404 page —
  a public route that renders the themed shell to a signed-out visitor. The guard reads every
  non-test source through `import.meta.glob('?raw')` (measured to work for `.ts`/`.tsx`, unlike a
  stylesheet) and sweeps hexes, Tailwind's numbered scales, and `white`/`black` separately, the last
  exempted per file with a reason.

**The preference is a module store read through `useSyncExternalStore`** — three states
(`light`/`dark`/`system`, anything else read as `system`), `localStorage`, per browser. **A Context
provider would work equally well, and the entry says so because two justifications for preferring
the store were written here and both were false.** The first: a provider would remount its subtree.
It would not — a reviewer built one and measured it; consumers re-render, the controlled input keeps
its value, the DOM node is identical, and FR-004's no-remount criterion is met by either shape. The
second, written to replace the first: the consumers sit in disjoint subtrees, so a provider would
have to sit above the router. Also false — `RootLayout` renders the header and the `Outlet` as
siblings and already hosts `NavRailProvider` in the exact position a theme provider would occupy.

The one real asymmetry is small: the state lives outside React, so the setter is callable without a
render and the module resolves the preference the same way `theme-init.js` does, with no provider to
thread. **The lesson is not about theming.** A design choice that is genuinely a preference attracts
a justification anyway, each one plausible and each one written with more confidence than the last;
both of these were caught only by someone building the alternative rather than reading the argument
for it. When the honest answer is "either would do", write that.
`public/theme-init.js` stamps `data-theme` before the first paint and is **external, not inline**:
the CSP is `script-src 'self'` with no nonce and no hash, so an inline initialiser would work in dev
and be refused in production. It throws on nothing, because it blocks the module script behind it.

**The control is in the header unless the drawer is showing it.** Below `tablet` an authenticated
header is over its width budget before anything is added (SPEC-211 FR-007), so the three choices go
into `AppNavDrawer` — but that drawer is mounted only for an authenticated user, so the signed-out
header keeps the control at every width, and the landing route, which suppresses the app header
entirely, carries its own copy.

## The URL transformer's encoding is position-dependent, and both simple rules are wrong

Encoding the value **unconditionally** is right inside a path or a query — a value must not climb
out of its segment, add a parameter or graft a fragment on — and wrong at the **start** of the
template, where `${value}` is the natural template for a column that already holds links: encoding
turns every legitimate `https://…` into `https%3A%2F%2F…`, so that column can never link at all. It
also makes FR-006 AC2's own worked example unreachable, since a `javascript:` cell would then fail
as "not a URL" rather than at the scheme check. Not encoding at all is the other wrong rule.

So the **leading** position substitutes raw and every later one is encoded, and the `https:`
allowlist — judged on the **resolved** URL, never the template — is what guards the leading case.
An allowlist rather than a blocklist, because the blocklist is the one that has to be complete.

The substitution is assembled part by part rather than with `String.replace`, whose replacement
string reads `$&`, `$'` and `` $` `` as patterns: a cell holding one would be expanded into
something other than itself *before* anything parsed it. Anchors carry `rel="noopener noreferrer"`
and `target="_blank"`; a refused scheme renders as plain text with its reason reachable.

**`isSafeInAppPath` is deliberately not used, and the call site records why.** That rule
(SPEC-061/167) governs IN-APP paths — it asks whether a link is a route inside this application and
answers by refusing anything not root-relative. Every URL here is external and absolute, so it
would reject all of them, and loosening it would have it answering a question it was never written
for. Reaching for a rule that sounds adjacent is how a confident category error ships.

## A rule's `scope` is a field the spec's model did not have

`ColourRule` carries `column?` — the spec read an absent column as "apply across the row", which
conflates what a rule TESTS with what it PAINTS and leaves the most ordinary rule inexpressible:
colour the whole row wherever `status` is `failed`. One optional `scope: 'cell' | 'row'` separates
them (SPEC-181's `valueKind` is the precedent), and an absent `column` keeps its own meaning — test
every cell in the row.

Precedence runs weakest to strongest — type tint, then band, then rules in order — and each layer
overrides only the **property** it sets. That is what makes "a later rule overrides an earlier one
on the same property" and "conditional rules win over both the type tint and the band" true without
a special case for either. **A NULL matches nothing, including `<>`**: NULL is the one value Athena
does not hand back as a string, and "is not 5" over a value that was never there would paint every
empty cell in the column.

## The raw value drives everything, and the transform lives at the cell

`transformCell` is called at the cell and nowhere upstream, so a filter, a colour rule, Calc and
copy all read the raw row — a transformed value reaching any of them is a silent wrong answer
rather than a visible one. The Calc assertion uses a **hex** transformer deliberately: `10` renders
as `3130`, which is itself a plain number, so a Calc reading the rendering would answer a wrong
number rather than fail visibly. NULL and the empty string are returned untransformed, because both
are absences the grid already names in words.

**The Text view stays raw** — no colours, no transformers. It is the drag-select-and-copy surface,
and its whole promise is that what is on screen is what is copied.

## A link in a grid is not a tab stop, and the app must not manufacture backtracking

Two review findings that generalise beyond this spec.

**`role="grid"` promises ONE tab stop**, which is why every cell but the cursor carries
`tabIndex={-1}` — so a URL transformer's anchor is `tabIndex={-1}` too, or a hundred rows put a
hundred stops inside the grid and Tab walks the column instead of leaving. The **Value panel
carries a focusable copy of the link**, which is what makes that cost a keyboard user nothing, and
the Record view — which already wraps every value in a button — renders the text without an anchor
at all, because an anchor inside a button is nested interactive content. No axe case had rendered a
transformed cell, which is how a `nested-interactive` violation reached review; the file now walks
both views, and the fix was verified by reverting it.

**A wildcard translated one for one manufactures catastrophic backtracking.** Mapping each `%` in a
`LIKE` pattern to its own `[\s\S]*` makes adjacent wildcards nested unbounded quantifiers:
`%%%%%%%%x` against a 60-character value measured at **31.7 s**, in a `useMemo` that runs once per
cell. A length cap bounds the input, not the runtime — and `%%%` is not a hostile regex, it is what
a user types believing it is a wildcard. Runs of `%` collapse to one: identical matches, 0 ms.

## A hidden column is still part of the row

Formatting is evaluated over EVERY column, not the visible ones. A rule reading `status` must keep
painting its row after `status` is hidden, and the dialogs are handed the same list, so what they
report as applicable is what the evaluator can actually see — judged over the visible columns, the
dialog called a rule fine while it silently did nothing, and striping turned itself off when every
chosen column was hidden. Formats for hidden columns are simply never looked up.

## A stored formatting block is discarded WHOLE

Unlike the field-by-field normalisation beside it, `formatting` is validated as a unit and replaced
with defaults if any part of it is wrong: a partially-applied colour set is a rule list the user
never built, and a rule that survived while the one meant to override it was dropped paints the
opposite of what was intended. The colours are validated against the **palette**, not merely
against `string` — a stored `#ff0000` would render verbatim as an inline style, and the contrast
the palette is measured for would no longer hold for it. A rule naming a column the current result
lacks is **kept and shown as inapplicable**: a grouping change replaces the column set wholesale, so
that is the ordinary case, and un-grouping brings the column back.

## Copy is the selection-shaped tool and export is the result-shaped one, and reusing the save path meant moving it (SPEC-185)

## The two ways out divide on the line the whole arc divides on

Copy takes the **cell selection**, which exists only in the browser: `renderCopy` is a pure function
over the rows already fetched, so copying — in any of six formats, with any options, however many
times — starts no execution and scans no bytes. Export copies the **execution's own results object**
with a server-side `CopyObject`, so what leaves is every row the statement returned rather than the
25 in the grid, again with no second query and no second bill.

That is why **exporting a selection is out of scope** rather than merely unbuilt. A partial export
would need either a second query — the one thing this feature spends ten specs avoiding — or a
client-side re-serialization of rows that are not all loaded, which is the scale lie the whole arc
was designed around. And it is why copy's formats are clipboard-only: the results object is Athena's
CSV, and converting it would mean reading it back through the browser.

Both surfaces say the asymmetry out loud, because it is not inferable. The advanced copy dialog
states that only the loaded page is copied and points at Export for the rest; the grid's status line
says `N cells selected on this page` every time it says anything, which is SPEC-182's rule for Calc
applied to the same fact.

## A NULL and an empty string stay apart in all six formats, and quoting is what disambiguates the WORD

FR-001 AC4 costs nothing in the three formats that have a null of their own — JSON emits `null`, SQL
emits the keyword, XML gets an explicit `null="true"` attribute rather than an empty element. The
delimited formats and Markdown have no such thing, so a NULL renders as the token `NULL` and an
empty string renders as nothing at all. Those two are always distinguishable.

What is **not** distinguishable in a delimited format is a NULL from a cell whose text is literally
`NULL`, and that is the honest limit rather than a defect: `quoteValues` is the answer, since a
quoted `"NULL"` is a value and a bare `NULL` is an absence. The dialog says so beside the control.

`quoteValues` is **inert** in JSON, SQL and XML, whose values are already delimited by the format —
so the checkbox is disabled there with its reason next to it, rather than offered as a control that
silently changes nothing. Two smaller rules fall out of the same reasoning: CSV still quotes what
the *format* requires (an unescaped comma is not ambiguous CSV, it is CSV with an extra column),
and a Markdown table keeps its header row with column names off, because a table without one renders
as a paragraph of pipes in every dialect.

## A discontiguous selection copies as a rectangle, and a SQL INSERT names a placeholder

A selection with gaps copies as its **bounding rectangle**, with the unselected cells blank. Packing
the selected cells together would silently move values into columns they were never in — a paste
that is wrong in a way nobody can see, where a hole is wrong in a way anybody can. It is stated in
the dialog rather than left to be discovered.

The `INSERT` names `"results"`, deliberately not the source table. These rows are what a filter, an
ordering and possibly a `GROUP BY` produced, so an INSERT naming the source would be valid, runnable
and wrong. Values go through `lib/sql.ts`'s `sqlLiteral` — the **Trino/DML** escaper that doubles
the quote, never `cpcommon.ddl.literal`'s backslash form (SPEC-178's rule; the wrong one fails
silently). XML puts the column name in an **attribute**: an Athena column name is not required to be
a valid XML name, and deriving element names from one produces documents that do not parse.

The copy reads the **raw row**, never `cellText` and never SPEC-184's `transformCell` — a
URL-transformed column pasted into a spreadsheet has to carry its value, not its link text. The test
that proves it uses a **hex** transformer on SPEC-182's precedent, because a URL transformer keeps
the raw value as its link text and the assertion could not have failed.

## Reuse required a MOVE, and the move closed a live flag defect

`useSaveResults` lived in `features/query/`, which `features/data-explorer/` may not import
(SPEC-176's sibling clause). "Reuse it unchanged" was therefore unreachable from where it sat, and
the two alternatives were a second implementation of a path with a collision round-trip in it, or the
move SPEC-176 and SPEC-177 already established. It went to `features/catalog/` — which owns the
Athena execution and results layer, and the results object is exactly that — with its body untouched,
`SaveResultsDialog` and `normalizeCsvName` with it, and `features/query/query.format.ts` deleted
because nothing else was in it.

**One thing about the hook did change, and it is why the move was worth more than the reuse.** It
built its own destination list from an unfiltered `useQuerySpaces()`, while every saved-query surface
beside it used a view-gated list — so with `sharedWorkspaces` off, the Query workspace's Save-results
dialog had been offering a colleague's space as a **write target**, unregistered and unnoticed since
SPEC-055. The destinations are now a **parameter** (SPEC-174's shape, and SPEC-177's), both views
hand it a gated list, and both instances have their own `GATED_SURFACES` row — SPEC-175's finding
that each selector instance needs one, applied to the instance that had been missing.

Export's refusal is judged on the **results location**, not on the grid: Athena reports it only for a
SUCCEEDED execution, so "nothing has finished running" and "there is nothing to export" are one fact
rather than two that can drift. A failed apply leaves the last good execution's rows on screen while
that field has already moved on, which is the case a rows-based test would get wrong.

## Every guide row before this spec lived in the section the Help page opens on

The walking test's guide recipe queried a guide card without selecting its owning section. That
worked for four rows by coincidence — all of them were in `files`, the default section — and would
have returned `null` in **both** flag states for a row anywhere else, which reads as "correctly
hidden" rather than as a recipe that cannot see its surface. The recipe now selects the section
first, and returns null only when the section itself is gone (the `files` shape, where a section row
and a guide row share one flag).

The Data Explorer gets **its own Help section** rather than guides folded into Query: it is a
primary nav destination with its own flag, and a user looking for it in Help should find it by name.
The section and each of its five guides get a registry row, on the `files` precedent — the section
row alone would suffice today and would go on passing if a later spec moved one guide into the Query
section, where it would then be visible with `dataExplorer` off.

The guides document only what is shipped and wired (SPEC-074 FR-005), which here means saying two
things plainly that the UI cannot: that **every filter and sort runs a real query against Athena and
scans data**, with the figures at the bottom as the cost signal; and that a saved exploration
**reopens in the Query workspace as SQL**, not back here as an exploration — SPEC-183 descoped the
loading half, so a guide promising otherwise would document a spec that has not been written.

---

## A default that an empty string can defeat is not a default (SPEC-186)

**Context.** A live-check session on 2026-08-14 discharged several long-owed checks and, in doing
so, found that a number of *other* owed checks could not be performed at all — not because the
behaviour was broken, but because the assertion they named was unreachable from any principal or
surface a human has. A check nobody can run is indistinguishable from a check that passes, which is
SPEC-138's "did not run is never clean" and SPEC-137's blind gates in a third place. The same
session found, by eye, that nine dialogs rendered at full viewport width.

## `??` does not fall back on `''`, and a helper returning `''` is a trap for every consumer

`cx()` returned `string` — never `undefined` — so `FormDialog`'s
`cx(scrollBody && '…', className)` handed `Modal` an **empty string** whenever its caller passed
neither prop, and `Modal`'s `className ?? 'max-w-md'` took that as a deliberate choice to have no
width. The panel's `w-full` then filled the viewport. **Nine dialogs**, one line: `New folder` and
`New shared connection` measured 1372px in a 1400px viewport with `max-width: none`, against
`Create table`'s correct 448px.

Fixed in the shared layer **twice**, deliberately: `cx` returns `undefined` when nothing is truthy
(so the trap is gone for the next `??` consumer anywhere in the app), and `Modal` uses `||` (so a
caller composing its own class string is still safe, which is what the AC's `className=""` test
requires). Widening `cx`'s return type to `string | undefined` type-checked at every call site with
no change — the two that wanted a string for `aria-describedby` already coerced with
`|| undefined`.

**Note the direction of the bypass.** The four dialogs that hand-roll their chrome pass an explicit
`max-w-lg` and were therefore *unaffected*; the nine that correctly used the abstraction were the
broken ones. That is an argument for fixing the shared layer, not for copying more.

## A refusal announced after the confirm is worse than no affordance at all

`fileBrowser.service.ts` always refused deleting `saved_queries/` — but only after the user read
*"Delete the folder "saved_queries" and everything inside it? … This can't be undone."* and pressed
Delete. The most alarming confirm in the app, shown for an action that was never possible.

`undeletableSelectionRefusal` feeds `Button.disabledReason` (SPEC-172's `aria-disabled` affordance),
and because `Button` swallows the click, **"no confirm is reachable" falls out of the mechanism**
rather than needing a second guard. `ConfirmDialog` gained `confirmDisabledReason` on the same
pattern for the refresh dialog's opt-in — `busy` still wins and stays natively `disabled`, because
an operation in flight is not a refusal.

The test asserts **`alertdialog`**, not `dialog`: the confirm carries the former, so querying for
the latter would have passed whatever happened. A negative assertion has to name the thing it is
denying.

## jsdom has no layout, so a containment property must be arithmetic

The suggestion listbox overhung the Add-members dialog by **97px** (3 of 8 options visible) because
its flip logic measured `window.innerHeight` — right for a combobox on a page, wrong for one inside
a dialog, where `Modal`'s panel is `overflow-y-auto` and is what actually clips it. The component
now walks to its nearest scrollable ancestor and caps the list to the room there is.

The AC asked for a numeric assertion (`listbox.bottom <= dialog.bottom`), and **jsdom reports every
rect as zero**, so the geometry moved into a pure `listPlacement()` and the test derives the list's
far edge from the returned placement — over the measured case and over a sweep of every field
position in a 600px dialog. The DOM test asserts only what the DOM can see: that the bound is a
*measurement* rather than the old fixed `max-h-60`.

The flip is deliberately **conservative** — it goes up only when below is cramped AND above is
roomier — because below is where the reading order expects the list.

## A procedure that cannot produce its claimed outcome invites a false bug report

Two live-check scripts described impossible procedures, and one of them was followed and read as a
defect until the code was checked.

**Schema inference samples exactly ONE object — the first key in listing order**
(`sample_by_format.setdefault(fmt, key)`, and S3 lists lexicographically). A column added in a file
that sorts *later* is invisible **by design** and the refresh correctly says `already up to date`.
The fixture must name a file that **sorts first**.

**Two UI submits cannot contend for SPEC-157's lock.** Two submits 2 s apart — the floor two
pre-armed tabs allow — both returned independently, because a small table's refresh completes inside
that window. The check needs an SQS double-send or a several-hundred-object folder.

**And SPEC-173's marker check was unrunnable as written**, which is the third instance: the portal
issues **zero** `DeleteObject` against the marker (hidden by basename, folder refused client-side),
so the bucket-policy Deny — the layer the check exists to prove — was never exercised. Split into
two separately-numbered checks, because neither layer's result says anything about the other's.

**Any procedure needing a raw ID token says so up front**, says where it is read from, and says it
must not be pasted into a shell command — it is a live credential and it lands in history.

---

## A persistent in-flight surface is NEW scope, with no precedent here (SPEC-190)

The three async planes already in the file browser — send, archive, restore — have **no in-flight
surface at all**. They push a toast and hand off to notifications, which is survivable for an action
the user chose to fire and forget. The upload queue is not the precedent it looks like either: its
provider is session-scoped at the shell so uploads survive navigation, but its list renders inside a
drawer that exists only while it is open.

This one is justified on its own merits, because these gestures **replaced synchronous ones**. A
user who copies a folder and watches nothing happen has no way to tell "accepted, running in the
background" from "the click missed" — where before, the listing simply updated. That is the
regression the surface exists to prevent, and it is the reason a citation would not have done.

It is session-scoped and **not persisted**. The notification is the durable channel; a stored queue
would be a second writer to state the plane owns, and it would outlive the only thing that can
settle it. Three bounds keep it from wedging the per-space submit gate: an entry settles when a
notification carrying its `requestId` arrives, every entry is user-dismissible, and every entry
expires at the machine's own `TimeoutSeconds` (mirrored in the browser and pinned to `locals.tf` by
a test). The dismiss is load-bearing rather than tidy — a request that dead-letters produces a
notification with no payload to correlate against, so it is the only thing that frees that space.

## There is no progress percentage, and there cannot be one (SPEC-190)

`onProgress` went with the browser's own copy loop: the plane reports outcomes at the END of a run
and nothing in between, so any percentage the browser drew would be invented. The surface says
**what** is running and **since when** instead. This is not a gap to fill later by polling the
execution — that would be a second read path to state the notification already reports, on a plane
whose whole point is that the browser stops watching.

## The kill switch is a flag key, and it is the sixth (SPEC-190)

Five flags are areas; `asyncFileOperations` is a switch over the file browser's copy/move/delete
routing. It earns a key rather than a build-time constant because its only other kill switch is
`files: false`, which removes the entire file browser — and because publishing a flag needs no app
build, which is what makes the largest user-visible change in the product survivable. Default **on**,
keeping the all-on fallback rule intact: an unreadable document must never change behaviour. Off,
every gesture keeps the browser's synchronous path exactly as it was.

Its two registry rows are the in-flight surface and the conflicts guide. **The conflict VIEW is
registered under `files` instead**, deliberately: throwing the switch must not strand a conflict
raised before it was thrown, and resolving one finishes work the plane already started rather than
beginning a new gesture — and it keeps the `Review conflicts` control already shipping on
notification rows from becoming a link to nothing. A row's `name` is its accessible name and
`RECIPES` keys are unique, so one control cannot hold a row under two flags; the choice had to be
made rather than hedged.

## Help is read where the work is, and a gated page's help is gated by derivation (SPEC-207)

The guides were good and in the wrong place: reading one meant leaving the page, and whatever was
half-filled-in there was a separate worry. The header control now opens a **panel over the current
route** — the shared `Drawer`, so Escape-by-depth, the focus trap, focus restoration and the mobile
full-height sheet all come for free — and the route beneath stays mounted. One `HELP_SURFACES`
registry maps a route path to a section id, and that is **all** it maps: no flag information, held
by a test that sweeps its import list.

**No control was added.** The one already in the bar is repointed, so the mobile header's width
budget is untouched, which is what lets a sibling spec spend that budget instead. The guard is
**route invariance** (the control count on a route with a row equals the count on a route without
one), never a pinned number, because a pinned number is exactly what a sibling spec adding a header
control legitimately breaks.

**A gated page's help is gated by derivation, and NOTHING declares it a second time.** With
`dataExplorer` off, the Data Explorer section is already filtered out of the visible set, so
`/explore` resolves to no section and the control falls back to navigating. `GATED_SURFACES` gains
no row — the registry's per-flag set-equality over row names would fail on one anyway, which is the
mechanism that keeps this honest.

**One row is an exception, and it is the one this spec introduced.** `/data-quality` maps to the
`files` section because that is where its two guides were authored, and there is no data-quality
section to filter out — so with the flag off the panel still opens, over the unavailable page. It
discloses nothing (the two guides are hidden with the flag, and the rest is Files content the user
has anyway), and closing it would mean declaring the gate a second time, which is the thing this
entry is against. Stated rather than left as a silent counterexample to the sentence above.

The two fences that would otherwise fork:

- **The panel reads the FLAG-FILTERED sections, never `HELP_SECTIONS`.** One extracted helper,
  `visibleHelpSections`, serves the page and the panel. A panel reading the raw content would show,
  with `asyncFileOperations` off, a guide `/help` hides — the fork the guide→flag registry exists to
  prevent, reintroduced one layer up.
- **The panel is not addressable and must not become so.** Only the full page is. Putting it in a
  search param would make every route's URL carry help state for no producer that needs it.

**Closing on a route change is adjusted during RENDER, not from an effect** — `react-hooks/set-state-in-effect`
forbids the effect form, and the render-time adjustment is the better shape anyway: the panel is
gone before the new route paints. Deriving `open` from the pathname instead does **not** work, and
the failure is narrow enough to name: open it on `/files`, go elsewhere, come back, and a
pathname-keyed state reopens it.

`/help` gained **guide-level** hashes (`/help#upload-files`) beside the section hashes it already
had. Section hashes are matched first and behave exactly as before. The guide's card is expanded by
carrying the addressed id in the card's React `key` — `HelpGuideCard` reads `defaultOpen` once into
state, so a hash change with the page still mounted would otherwise do nothing — and the page wraps
each card in an anchor `div` rather than changing that component. The scroll effect is declared
**after** the existing scroll-to-top: both run on a hash-driven mount, the later one wins, and
jsdom has no layout, so no test can catch a reordering.
## One split, two clamp domains, and the pair has to agree (SPEC-209)

The editor/results split is stored as a **fraction** and rendered as **pixels**, so it is clamped
twice: `splitBounds` gives the fraction bounds the separator reports as `aria-valuemin`/`max` and
that `Home`/`End` land on, and `clampEditorHeight` gives the pane's pixel height. Two clamps over one
value can describe **different splits**, and the divergence is silent — the pane looks right while
the value a screen reader announces is wrong. A swept test pins the agreement over a grid of
fractions and column heights, and it caught two real cases while it was being written.

What makes them agree is that the **pixel floors are the whole clamp on a measured column**. Mixing
the hard fraction bounds in — a 5% floor that is *looser* than 96px on a 1946px column, a 95% ceiling
that is *tighter* than the results floor on a 3000px one — is exactly what pulled them apart. Those
two constants describe an **unmeasured** column and nothing else: the column measures 0 on the first
render of every mount, `MIN_EDITOR_HEIGHT / 0` is `Infinity`, and axe rejects `"Infinity"` in a
`decimal`-typed `aria-value*`, so a bound that never divides by the measurement is not a nicety.

The divider's own **24px is inside the results cap**, not beside it. A cap that ignores the element
between the two panes is wrong by exactly its height, which is the kind of error that reads as a
rounding artefact and never gets found. It is one constant, applied as an inline style rather than a
Tailwind class, so the number the clamp uses and the number the browser lays out cannot drift.

## The divider needs a click path, because a drag is not an alternative to itself (SPEC-209)

The separator is a focusable widget with arrow/`Home`/`End` operation, so **2.1.1 Keyboard** holds,
and the step buttons are drawn at the **2.5.8 Target Size** minimum. That minimum is in **CSS px and
the app's root font-size is 14px**, so Tailwind's rem spacing lies about it: `h-6` is 21px, not 24,
and the buttons shipped that way until it was measured in a browser. They are sized in px now and the
band is tall enough to hold them. jsdom reports axe's `target-size` rule as a **pass** because it has
no layout, so the rule is enabled and carries no information — nothing in CI can catch this, and the
live guide asks for it to be measured instead. Be exact about what that rule is: it is not a
limitation, it is a **vacuous guard** — an enabled rule advertising coverage it cannot provide, which
is worse than a disabled one, because the suite reads as checking something it never checks.

Neither of those answers **2.5.7 Dragging
Movements**, which asks for a *single-pointer, non-dragging* alternative specifically — keyboard
support is not one, and no axe rule detects the absence, so nothing in CI would have said so.

**The retired `EditorLayoutControl` was that alternative:** three `onClick` buttons setting the split
three ways. So this surface met 2.5.7 before the spec, and a drag-only divider would have *caused* a
regression rather than inherited one. That distinction is the whole reason the divider carries a pair
of step buttons — they were added mid-build, on a user decision, and they are the only new product
surface in the spec.

**`ColumnResizeHandle` is the other case and stays open.** It has never offered a non-drag pointer
path, so the result grids are a standing gap this spec neither widens nor closes. Do not read the two
as one finding: one was a regression to prevent, the other is somebody else's spec.

**The buttons are the separator's SIBLINGS, not its descendants — and both of the obvious
alternatives fail in ways that look fine.** Nesting them inside is invalid: a focusable separator is
a widget, and a widget may not contain focusable content. Nothing about the rendered result says so;
axe's `nested-interactive` failing the route check is what caught it. Filtering instead — guarding
the separator's handlers with `e.target !== e.currentTarget` so a button click cannot start a drag —
is *worse* than invalid, because it is wrong at exactly the point users aim: the visible grip is a
**child** of the separator, so the guard ignores a grab on the grip while every test that grabs the
band still passes. Siblings in a plain wrapper band answer both at once, and need no filtering at
all.
