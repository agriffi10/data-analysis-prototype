# Completed Spec — SPEC-175: Saved Queries — Saving into a Chosen Space

## What was completed?

Saving a query now starts with the same question loading does — *which space?* — and writes a
`.sql` file there. A shared space's `saved_queries/` folder can finally contain something, which is
what the arc existed for.

- **`SaveQueryDialog`** — a destination control above the name field (SPEC-174's
  `SavedQuerySpaceSelect`, unchanged), the inline error, the busy lock, and the no-writable-space
  banner. Name validation moved to **submit**; `submitDisabled` no longer stands in for a refusal.
- **`useSaveQuery`** — the whole save path lifted out of `QueryWorkspace`: validation, the folder
  marker for the chosen space, the write, the `Collision` round-trip, the toast, and the `pending`
  request that survives a trip through the Replace confirm.
- **`isLinkedSavedQuery(link, space, name)`** in the store — the one rule behind two behaviours that
  must agree: the dialog's "replacing the file this tab was opened from" and the host's `overwrite`.
- **`QueryDialogs`** — takes the hook result whole (as it already does for share/refresh/saveResults)
  instead of nine hand-wired props; the Replace confirm names the space.
- **`QueryWorkspace`** — wires the hook, and updates the **one** space memory on success.
- **A `GATED_SURFACES.sharedWorkspaces` row** for the dialog's destination control, and the
  rewritten `save-query` guide.
- **No `infra/` change anywhere in the diff.** The store needed almost nothing: SPEC-173 already
  shipped the HEAD-on-the-exact-key `Collision` and `savedQueryName`. Its one correction — the
  lowercased typed extension — is below.

## One memory, and the destination is judged by the key

FR-001's "the space I am working in" is deliberately **one** value, shared with the load surface:
`useSavedQuerySpace`'s. A save writes to it on success, so the next save and the next load both open
where the user last was. Two memories would be free to disagree, and the user has no model of a
saving-space distinct from a loading-space.

Everything that turns on "is this the same file?" — the sentence in the dialog, the `overwrite` on
the write, and therefore whether a second confirm is raised — goes through `isLinkedSavedQuery`, and
it judges the **key**, not the space. A different name in the tab's own space is a different file; so
is the same name in another space. Had either half computed its own predicate, the dialog could
promise an in-place replace while the host wrote a new object, or vice versa.

## What changed for the user

- **A write failure keeps the dialog open**, with the typed name and the chosen space intact, and
  renders the mapped message **inline on the field**. It was a toast over a closed dialog — which
  discarded the destination the user had just chosen, in the one failure (revoked shared-space
  membership) whose whole point is that they need to choose another.
- **A linked tab's Save is prompted, and confirmed once.** Submitting the pre-filled name and space
  writes with `overwrite` and raises no Replace confirm: the file being replaced is the one whose
  name the user is looking at. Change either half and FR-003's HEAD-and-confirm applies.
- **Saving into another space is a copy, not a move.** One `PutObject` into the new space, no
  delete anywhere, and the tab re-links to the new file. The original stands — a saved query a
  colleague may be running does not disappear because someone copied it elsewhere.
- **`Report` and `report` are two saved queries** (SPEC-173's key-based collision, now reachable
  through a destination choice, and pinned by a test as the deliberate change it is). **`report.SQL`
  and `report.sql` are not** — see below.
- **The toast names the space**: `Saved “Quarterly” to teamspace.`

## A typed `.sql` extension is now lowercased, and that is a change to SPEC-173's store

FR-002 AC4 asks that `report`, `report.sql` and `report.SQL` "all produce exactly one key ending
`.sql`". SPEC-173's `basenameFor` only skipped **appending** — so `report.SQL` was a *second*
object, and because `savedQueryName` strips the extension **case-insensitively**, both rendered as
`report` in the load list, on the tab and in the Replace confirm. Two rows a user cannot tell apart
is bad; the reachable failure is worse. A tab linked to `…/report.SQL` pre-fills `report`, which
resolves to `…/report.sql` — so `isLinkedSavedQuery` correctly says "not your file", the HEAD finds
the *other* one, and the confirm offers to replace `report`. Confirming clobbers a file the user
never opened while the one they did is silently orphaned.

`basenameFor` therefore lowercases a **typed** extension. The **stem is untouched**: `REPORT` and
`report` remain two visibly different names, which is the case-sensitivity FR-003 deliberately
keeps. A `.SQL` object already in a bucket still lists and opens unchanged — only the save path
normalises, so re-saving a tab linked to one writes a `.sql` sibling: a visible Save-as rather than
a silent clobber. Approved as an in-scope correction to an out-of-scope file, because FR-002 AC4 is
this spec's own criterion and nothing else could make it true.

## What the review changed

A fresh-context review against the acceptance criteria found eight things. All are fixed in the
branch, and the three that turned on "can this test fail?" were settled by **mutation**, not by
argument:

- **FR-001 AC2 and AC3 were covered by tests that could not fail.** Every existing case had the
  remembered space and the linked space *agreeing* — `onSaved` calls `selectSpace` and keeps them in
  lockstep — so `pending?.space ?? linkedSpace ?? defaultSpace` passed with **either** operand
  deleted (measured: 514/514 both times). The live bug behind it: with `teamspace` remembered, a tab
  linked to a personal query would default to `teamspace`, writing a **copy into the shared space**
  and re-linking the tab there, with every visible cue consistent. Three hook tests now discriminate
  the fork; each mutation reddens it.
- **Enter on the space control would submit the dialog in a real browser.** `FormDialog` bailed on
  any non-`HTMLInputElement`, and jsdom implements no implicit form submission — so the test
  asserting "Enter on the select does not submit" held whatever the handler did (measured: deleting
  the guard entirely left it green). `FormDialog` now intercepts `<select>` too, and the test asserts
  **`defaultPrevented`**, which does redden. This also closes the same gap in `DestinationPicker`,
  the only other `FormDialog` caller with a real `<select>`.
- **FR-003 AC4's "does not list the folder" assertion could not catch its own regression.** The
  SPEC-043 behaviour it guards against scans the **already-loaded array** and issues no listing, so
  a call counter would not move. A new test makes the in-memory list and S3 disagree in *both*
  directions — a name in the loaded list but absent from S3 (must not prompt) and one absent from
  the list but present in S3 (must prompt) — which no list-scanning implementation can pass.
- **A thrown write would have stranded the dialog forever.** `busy` locks both buttons *and*
  `Modal`'s dismissal, so a breach of the service's no-throw contract left the buffer with no exit
  at all. The write now has the `.catch` the folder call beside it already had, through
  `toServiceError` so the failure carries a code (the repo-wide contract test caught the first
  version, which did not).
- **`isLinkedSavedQuery` had no test of its own** — the one predicate whose `true` skips the HEAD
  and authorises a clobber. It now has a describe block covering the cross-bucket, different-name,
  different-space, no-link and empty-name edges.
- **The FR-007 test leaked an empty bucket into the rest of the file.** The env restore was the last
  statement rather than a `finally`, and this file's stubs run once at collection — measured: one
  injected failure became **18**. Now in a `finally`.
- **A stale write failure survived typing.** The dialog cannot clear a prop it does not own, so it
  stops rendering the host's message once the name or the destination changes — the message named a
  destination the user had already abandoned.

The review also confirmed clean: no wrong-bucket write path, no success-on-failure, SPEC-106 holds,
the folder cache is keyed per space, `pending` does not leak across opens, the new registry row
drives the real page, and the axe passes are against driven containers.

## Deliberate deviations

- **`GATED_SURFACES` gains one row, not zero** (FR-008 AC3 read strictly says "no *duplicate* row").
  The dialog's destination control is a **second instance** of the `sharedWorkspaces` choice, and
  SPEC-167's precedent is explicit: the existing row renders the *drawer*, so nothing would notice
  if this control stopped being gated — and this failure is the worse of the two, because it offers
  a colleague's space as a **write** target. The row was **verified against a deliberate violation**
  (passing `allSpaces` instead of `savedSpaces` reddens exactly that row, measured), not trusted.
- **`onLinked` became `onSaved(query, sql)`.** The caller needs the written buffer for the
  dirty-marker snapshot as well as the link, the relabel, the list refresh and the space memory —
  one event, one callback, rather than two that can be wired half-way.
- **`useSaveQuery`'s signature differs from the spec's contract block**: no `username` (nothing on
  this path needs it), and it returns `spaces` / `linked` / `initialName` / `initialSpace` so
  `QueryDialogs` can take the hook result whole. `SaveQueryRequest` carries `{space, name}` and
  **not** `overwrite` — the host decides that from `isLinkedSavedQuery`, so the dialog cannot ask
  for a silent clobber.
- **The dialog validates on submit as well as the hook.** The hook's guard is what makes "no S3
  request" true for every caller; the dialog's is what makes the message immediate.

## Verification

`npm run format:check`, `lint`, the full portal suite (**2032 tests, 82 files, exit 0**) and
`npm run build` green locally.

**Nothing live is owed by this spec beyond what the arc already owes.** Its only new AWS interaction
is a `PutObject` into a shared space's `saved_queries/` prefix, which the arc's outstanding check
already covers: SPEC-173's marker-delete refusal, personal **and shared**, with a save→see-the-file
pass folded in. Do the shared half of that pass **as a save into the shared space** and it discharges
this spec's cross-bucket write at the same time. Not verified in a browser here: the workspace needs
a signed-in Cognito user, and the dev-unauth path has no username and therefore no writable space —
it can only reach FR-007's banner.
