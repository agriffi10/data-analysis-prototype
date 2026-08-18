# SPEC-172 — Archive & Restore: the UI, the read-only mirror and the notifications

**Completed:** 2026-08-12
**Spec:** `docs/specs/SPEC-172-archive-restore-ui-and-notifications.md`

## What shipped

Four specs of privileged machinery get their entry points, and the plane learns to say what it did.

**A new feature area — `apps/portal/src/features/archive/`**

- `archive.service.ts` — `enqueueArchive` / `enqueueRestore` on `lib/enqueueFifo`, the two group-id
  derivations, the request-shape caps mirrored from `arcommon/config.py`.
- `useArchive.ts` — `useArchive` (dialog + enqueue for the archive), `useRestoreArchive` (the same
  for the restore), and `isArchiveId`, the client-side UUID rule.
- `ArchiveButton` — one component, two placements: the selection toolbar and both details panels.
- `ArchiveDialog` — the confirm, built on `ConfirmDialog` **because** `FormDialog` has the
  Enter-to-submit affordance this dialog must not have.
- `RestoreArchiveButton` / `RestoreArchiveDialog` — the pasted id, validated on submit.
- `archiveSelection.ts` — `ARCHIVE_RESERVED_ROOTS` and `archiveRefusal`, mirroring the plane's own
  `assert_not_reserved` including its **third** case (an ancestor that CONTAINS a reserved folder).

**`features/file-browser/` — the read-only mirror**

- `writeLockedPrefix.ts` — `isWriteLockedPrefix` / `writeLockRefusal`, the app's **first
  prefix-based write gate**. Upload, New folder, Rename, Move and Delete all carry its reason.
- `protectedFolders.ts` — `archive` joins `PICKER_LOCKED_FOLDERS` and `UNDELETABLE_ROOT_FOLDERS`,
  and joins neither of the other two lists: the folder must stay VISIBLE, because the folder names
  **are** the archive ids.

**`components/Button.tsx`** — a `disabledReason` prop: `aria-disabled` rather than `disabled`, the
reason as the accessible description, the click swallowed. A `disabled` control is skipped by the
tab order, which is how "it's greyed out and I can't find out why" happens.

**Lambdas — one new verb, the plane's seventeenth**

- `archive-notify` — the plane's only SUCCESS producer, invoked from **three** states.
- `arcommon.messages` — `archived_message`, `restore_started_message`, `restored_message`.
- `arcommon.notify` — `emit_archived`, `emit_restore_started`, `emit_restored`,
  `archive_folder_link`, `space_link`.

**ASL** — three states (`NotifyArchived`, `NotifyRestoreStarted`, `NotifyRestored`), each with
`ResultPath: null` and a Catch that leads **onward**.

**Registry + Help** — four `GATED_SURFACES.files` rows and an "Archive and restore guide".

## Only three of the nine outcomes needed a producer

FR-006 names nine. Six of them — `archive_not_found`, `archive_incomplete`, `destination_occupied`,
`restore_incomplete`, `restore_timed_out` and every other refusal — were already reason codes in
`arcommon.messages`, emitted **once** by `notifies_on_failure` on the verb that raised, or by the
machine's own `NotifyFailure`. Adding a second producer for them would have been precisely the
duplicate SPEC-114's one-token-per-OUTCOME rule exists to prevent. What was missing was the three a
failure table cannot carry, and `restore_started` is the one that had to be invented: it is the only
"started" notification in this application, and it exists because three to five **billed** hours of
silence is indistinguishable from a request that was dropped.

## Two deviations from the specs, and why

**The restore's FIFO group id hashes the archive ROOT, not `{archiveBucket}/{archiveRoot}`**
(SPEC-170 FR-001). The browser deliberately does not know that bucket's name — SPEC-168 put zero
portal-role statements on it, kept it out of the CSP, and
`test_archive_bucket_isolation.py::test_the_archive_module_passes_no_bucket_name_to_the_spa_or_the_app_module`
enforces the absence from the SPA's build env. The bucket would also add no discrimination: it is
one constant across every restore this app can make, while the archive root's own
`personal/`/`shared/` segment already makes it globally unique — which is the property the group id
actually needs. Pinned by `test_the_browser_builds_the_restore_group_id_without_the_archive_bucket`,
which names the decision to re-open if it ever fails.
**`docs/testing/e2e.md` was corrected to match**, so the hand-crafted SPEC-170 check
exercises the rule the browser reproduces.

**The write gate is per SPACE KIND.** FR-004's last AC wants the UI gate and the IAM Deny to agree,
and the two buckets are denied differently: the personal Deny is
`{bucket}/${aws:PrincipalTag/username}/archive/*` — anchored at the caller's own root, because in
that bucket the prefix IS the principal tag — while the shared one is `{bucket}/*/archive/*`, where
the wildcard is the space slot and **matches `/`**, so it reaches an `archive` folder at any depth.
Anchoring both at the root would offer writes into a nested shared `archive/` that IAM refuses;
applying the any-depth rule to both would refuse writes into a user's own `alice/backups/archive/`
that IAM permits. `archiveWriteLock.test.ts` turns each Deny into a key matcher and runs the app's
own predicate over the same keys — **measured**: deleting the shared branch reddens it.

## Things worth carrying

- **The archive confirm is the only dialog in the app where the confirm is not focused and Enter
  does not submit.** Both hold by construction rather than by discipline, because it is built on
  `ConfirmDialog` (not a form) rather than on `FormDialog`. `RestoreArchiveDialog` makes the
  opposite call for the opposite reason: one field, and Enter submits from it.
- **The archive dialog does NOT say "This can't be undone."** It can be undone — that is what a
  restore is — and the dialog says how long one takes instead. Borrowing the delete confirm's line
  would have been the one sentence in it that is false.
- **`ArchiveDialog` and the restore dialog import nothing from another feature** (FR-005 AC5), which
  is why the archive's own `describe`/`relativeToRoot` helpers exist rather than reaching into
  `features/file-browser`. They take different input types, so they are not a duplicate of the
  delete confirm's.
- **The details-panel entry point is labelled "Archive this item", not "Archive {name}"** — a
  static accessible name, because `GATED_SURFACES` rows and the walking test query by exact name.
  The drawer's own title already announces which item it is.
- **The restore's link is the SPACE ROOT.** A restore puts every object back where it came from,
  which for any selection of more than one folder is several places at once; picking the first would
  send the user to a folder holding part of what they asked for.
- **Two existing test fixtures used a folder literally named `archive`** (`destinationDialogs`,
  `fileBrowser.a11y`) and started failing the moment it became picker-locked. Renamed to `backups`,
  which is the same signal in miniature: a name that used to be ordinary is not any more.

## What the fresh-context review changed

Five findings were real and all five are fixed in the same branch. They are recorded because each
one is a shape rather than a slip.

- **The file details panel offered Archive on a file inside a reserved root, with no refusal.** The
  folder panel had the guard; the file panel had no prop for it, and the `archiveRefusalFor(key,
  'file')` branch was dead code. `athenaresults/` and `shared_tables/` are VISIBLE, so a file inside
  one is reachable, selectable and openable — and the plane would have refused it as
  `reserved_folder` hours of confusion later. **This is exactly the failure FR-001 AC5's
  list-equality test exists to prevent, arriving through the one entry point that test does not
  walk.** A journey test now performs it.
- **`restored` claimed "The archive has been cleaned up" on the route where it had not been.**
  SPEC-171 made a failed vault sweep a flag on a *successful* run, and `DeleteArchived`'s Catch
  reaches the same terminal through `CleanupIncomplete` — where the flag reached the execution
  output and nothing a user can see. The sentence is now conditional, the ASL threads
  `$.cleanup` (the whole block, because an absent Parameters path raises an uncatchable
  `States.Runtime`), and the unswept wording deliberately asks the user to do nothing: the residue
  is billed at the 90-day minimum and swept by the bucket's expiry.
- **Restore Archived Data disappeared inside `archive/`** — the one folder the dialog itself tells
  the user to go and look in. It had inherited the archive's `!writeLockReason` gate, and a restore
  writes into the space root, never into the folder being browsed.
- **The refusal was hover-only.** `title` is the accessible description, so a screen reader got it —
  but at 400px in Safari, which is this feature's own live-check width, the greyed controls said
  nothing at all. The reason now renders as a visible note for the folder, once, beside them.
- **Two of the three success bodies had no discriminator, and the plane passes no dedup token.**
  `restore_started` names a count and nothing else, so two restores of one folder started together
  would have collapsed into a single inbox row inside the queue's five-minute window. The three
  success outcomes now pass `dedup_id(requestId, outcome)` — SPEC-114's rule read literally, keeping
  the retry-safety content dedup was providing. **The failure emitters are unchanged**: their bodies
  name a reason and usually a count or a file.

Two tests **could not fail** and were measured as such: one asserted the restore id is lowercased
against a fixture of digits and hyphens, where `toUpperCase()` is a no-op — and the real
normalising, in the hook, was untested in both places; the other asserted the write lock where it
claimed to assert visibility, and passed with `archive` added to `HIDDEN_BROWSER_FOLDERS`. Both are
fixed against fixtures that can distinguish.

A third gap was a **missing guard rather than a bug**: these are the only three Tasks on this
machine that NAME their JSONPaths instead of passing `"Payload.$": "$"`, and the fleet's seed check
covers Pass states only — so pointing one at a path no state carries left all 3,608 tests green.
The paths are now pinned as exact sets, held against what the verb reads, and `$.cleanup`'s two
producer routes are asserted. The failure that guard really exists for is `"$.actor"` in place of
`"$.actor.username"`: a dict reaches `MessageGroupId`, throws inside SQS, is swallowed by
`emit_notification`, and loses the notification silently.

## Live check owed

The whole flow, in Safari, at 400px and desktop — appended to
`docs/testing/e2e.md` §4.11. It is the arc's fourth owed check and the only
one that exercises the browser at all.
