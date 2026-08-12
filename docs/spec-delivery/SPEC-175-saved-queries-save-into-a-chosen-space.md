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
- **No `infra/` change anywhere in the diff**, and no change to the store's write path: SPEC-173
  already shipped the HEAD-on-the-exact-key `Collision`, the `.sql` suffix rule and `savedQueryName`.

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
  through a destination choice, and pinned by a test as the deliberate change it is).
- **The toast names the space**: `Saved “Quarterly” to teamspace.`

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

`npm run format:check`, `lint`, the full portal suite (**2021 tests, 82 files, exit 0**) and
`npm run build` green locally.

**Nothing live is owed by this spec beyond what the arc already owes.** Its only new AWS interaction
is a `PutObject` into a shared space's `saved_queries/` prefix, which the arc's outstanding check
already covers: SPEC-173's marker-delete refusal, personal **and shared**, with a save→see-the-file
pass folded in. Do the shared half of that pass **as a save into the shared space** and it discharges
this spec's cross-bucket write at the same time. Not verified in a browser here: the workspace needs
a signed-in Cognito user, and the dev-unauth path has no username and therefore no writable space —
it can only reach FR-007's banner.
