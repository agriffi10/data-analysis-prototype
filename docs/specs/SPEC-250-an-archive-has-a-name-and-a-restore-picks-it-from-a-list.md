# Spec: An Archive Has a Name, and a Restore Picks It From a List

**ID:** SPEC-250
**Status:** Draft
**Last Updated:** 2026-09-28
**Depends On:** SPEC-168/170/172 (the archive plane, its restore arm and both dialogs), SPEC-246 (the `archive` kill switch, which still gates both entry points)

## Overview

Outside reviewers asked us to make archive and restore easier to follow: where archived data goes,
where a restore puts it back, and how an archive is labelled so it can be found again. Today the
archive confirmation says only that the files go to "long-term storage", and says nothing about
where a restore puts them or what stops it. An archive has no name, only a generated id, and to
restore one a user has to find that id in a folder of receipts and paste it into a text field.

This spec does three things. The archive confirmation explains where the data goes, that a restore
puts every file back exactly where it was and will not overwrite anything, that a restore takes
hours, and how to find the archive later. A user can give an archive a name when they create it.
And the restore dialog stops asking for a pasted id: it lists the space's archives by name, date
and contents, and the user picks one. Typing an id stays available behind a link, for the one
archive the list cannot show — one whose receipt failed to write, whose failure notification tells
the user to keep its id.

Nothing about how an archive is stored, restored or deleted changes. The restore guard, the commit
gate and every other fence in `docs/decisions/archive-and-restore.md` stand as they are. What
changes is what the user is told, one optional field on the archive request, one line on the
receipt, and a per-space index that exists to label the list.

## Scope

### In Scope

- The archive confirmation's explanatory copy (FR-001), including the 90-day minimum storage charge.
  The register already records that decision as shown in this dialog, and it is not shown.
- An optional archive name: the field in the dialog, the wire contract, the plane's validation, and
  a `Name` line on the receipt (FR-002).
- A per-space archive index written by the plane: one entry per archive, updated by each restore
  stage. It is there to label the list and nothing depends on it (FR-003).
- The restore dialog's archive list and picker (FR-004), and the collapsed fallback for restoring by
  id (FR-005).
- The archived notification, the Help guide `archive-files`, the archive plane's page, the register
  and the component inventory, all brought into line (FR-006).

### Out of Scope

- **Auto-archive and "expand archiving"**, which the reviewers deferred.
- **Renaming an archive after it is created.** The name is set once, when the archive is created.
- **Naming the archive in notifications.** The archived notification changes one instruction
  (FR-006) and names no archive. Restore notifications do not change at all.
- **Any change to what is archived, how, or where**: vault, storage class, key layout, machine
  shape, guard, commit gate, retention. The restore request's wire contract is unchanged too: a
  restore still sends `{requestId, space, archiveId}`.
- **A backfill of the index for archives made before this ships.** The list still shows them, from
  their receipt folders (FR-004), without a name or details.
- **Deleting an index entry or a receipt.** Both are kept for good, as receipts already are.
- **New infrastructure or IAM.** The execution role already reads (`SourceDataRead`) and writes
  (`SpaceDataWrite`) anywhere under a space root except the folders `NeverOverwritePortalManagedObjects`
  denies, and those do not include `system_settings/archive/`. The browser already lists and reads
  that folder through `objects.list` and `objects.readContent`. No API route is added.

---

## Functional Requirements

### FR-001: The archive confirmation says where the data goes and how it comes back

#### Description:

`ArchiveDialog` replaces its two consequence sentences with a short explanation, in the order a user
needs it. Every sentence below is required; the exact wording may be tightened in review, provided
each fact still appears:

1. **Where it goes:** the selection is moved out of this space into separate long-term archive
   storage, where it cannot be opened until it is restored.
2. **Where a restore puts it:** a restore puts every file back in this space, in the same folder
   and under the same name it has now.
3. **What stops a restore:** a restore overwrites nothing. If any of those files exists again,
   nothing is restored until the user moves or renames what is in the way. The remedy is "move
   or rename" and never a deletion, per the restore-message fence.
4. **How long:** a restore takes several hours.
5. **What it costs:** long-term storage is charged for at least 90 days, even when the archive is
   restored sooner.
6. **How to find it later:** choose **Restore Archived Data** in this space and pick the archive
   from the list, by the name given below.

#### Acceptance Criteria:

- [ ] The rendered dialog contains each of the six facts. A test asserts each one by its own
      distinguishing phrase: "long-term archive storage", "same folder", "overwrites nothing" and
      "move or rename", "several hours", "90 days", and "Restore Archived Data".
- [ ] The words "can't be undone" and "cannot be undone" do not appear. The dialog's existing
      refusal of that sentence is kept and asserted.
- [ ] The remedy sentence says "move or rename", and no sentence in the dialog contains "delete",
      "trash", "overwrite it" or "replace". A test sweeps the dialog's whole text content for those
      words.
- [ ] Focus still lands on Cancel, and Enter still does not confirm. The existing tests stay green
      unchanged.
- [ ] The dialog has no horizontal scroll at 375px wide with a 200-item selection and a 100-character
      name. Checked live, with the result recorded in the PR.

### FR-002: An archive can be given a name

#### Description:

`ArchiveDialog` gains an optional **Name** field below the selection list, with the hint "Helps you
find this archive when you restore it." One rule decides what a name may be, stated once per side
and held equal by a mirror test:

- **Normalised** by collapsing every run of whitespace to one space and trimming both ends. An
  empty result means "no name" and the request carries no `name` field.
- **At most `ARCHIVE_NAME_MAX_CHARS` = 100 code points** after normalisation.
- **Refused if it contains a control or bidirectional-formatting character**: U+0000–U+001F,
  U+007F–U+009F, U+200E, U+200F, U+2028, U+2029, U+202A–U+202E and U+2066–U+2069. The first
  groups would inject a line into the receipt. The bidi controls would let a name in a shared
  space display as something it is not.

The browser normalises and checks the name when the user clicks **Archive**. A refused name shows
an inline error on the field, and nothing is enqueued. The field has `maxLength={100}`, so the
browser can never send a name longer than the server allows.

On the wire, `ArchiveEnqueueRequest` gains `name: NotRequired[str]`, with a `Bound` row in
`apicommon.bounds` whose owner is `arcommon.config`. `archive-validate-authorize` adds `name` to the
archive mode's allowed fields (and not the restore mode's). It refuses the whole request with a
new terminal reason, `invalid_name`, when the value is not a string, is not already normalised, is
empty, is too long, or contains a refused character. That happens before anything is listed, copied
or deleted. A valid name rides on the state as `archive.name`, and `null` when absent. A nested
field needs no change to the `Validated` Pass.

The receipt gains a first line, `Name:`, rendered from `archive.name` or as `-` when there is none.
`receipt.rewrite` keeps working because it keys on the two restore labels, and a name cannot contain
a newline.

#### Acceptance Criteria:

- [ ] A name typed with surrounding and doubled spaces is sent normalised, and a whitespace-only
      name sends no `name` field. `archive.service.test.ts` asserts the request body in both
      cases.
- [ ] A name containing U+202E, or a pasted tab, shows the field's error on **Archive** and makes
      no `archive.archive` call. A test asserts the call count is zero *and* that the error names
      the reason, not merely that it appears.
- [ ] `validate-authorize` accepts a valid name and returns it as `archive.name`. It returns
      `archive.name: None` when the field is absent. For each of these it raises
      `TerminalError("invalid_name")`, asserted by reason: a non-string, an un-normalised string
      (leading space), an empty string, 101 code points, and a string containing U+0007. In each
      refusal case no S3 client call is made.
- [ ] A restore request carrying `name` is refused as `malformed_event` (an unknown restore field).
- [ ] `invalid_name` has an archive-mode body in `arcommon.messages`, and the existing
      every-reason-has-a-body test covers it.
- [ ] `test_request_size_chain.py` builds the archive worst case with a name at its bound and stays
      green. The bound row exists, which the contract's "every field has a bound" guard requires.
- [ ] `receipt.render` puts `Name:              Q1 reports` first when named, and `Name:` followed by
      `-` when not. `receipt.rewrite` over a named receipt changes only the two restore lines. A
      test asserts every other line byte-for-byte.
- [ ] The Python mirror test reads `ARCHIVE_NAME_MAX_CHARS` and the refused-character ranges out of
      the browser module and asserts they equal `arcommon.config`'s. It is mutation-checked: change
      one range bound on one side and watch it go red.

### FR-003: The plane keeps a per-space archive index

#### Description:

A new layer module, `arcommon.index_store`, maintains
`{root}system_settings/archive/index.json` in the space's own bucket. The key comes from
`arcommon.paths.index_key(name)`, and validate-authorize resolves it once as `archive.indexKey` in
**both** modes (`restore.validate` builds the restore mode's `archive` block). The document is
`{"version": 1, "archives": [...]}`, newest last, capped at `ARCHIVE_INDEX_MAX_ENTRIES` = 500 with
the oldest dropped. Entries are keyed on `archiveId`, so a retried verb replaces its own row rather
than adding a second. Every write is a compare-and-swap through `cpcommon.cas`, because two archives
of one space can finish at the same moment.

- **`write-receipt`** records the archive **after** the receipt write succeeds. The entry is built
  from the state: `archive.name`, the execution's `startedAt` (the receipt's `Requested` time),
  the actor, the first three items of `source.items` as paths relative to the space root (each cut
  to 200 characters with a trailing `…`), the selection's item count, the file count from
  `counts.file_count` and `totalBytes`. `restore` is `null`.
- **`update-receipt`** sets `restore: {status, at}` on the archive's entry at each of its three
  stages (`requested`, `restored`, `incomplete`), with `at` taken from `restore.requestedAt`.
  - At `requested`, it runs only after the receipt write succeeded. A failure there fails the run
    before anything is billed, and the index must not claim a restore that never started.
  - At `restored` and `incomplete`, it runs whether or not the receipt write succeeded, because
    the outcome it records has happened either way. At `incomplete` it runs before the verb's
    deliberate raise.
  - If the archive has no entry (it was made before this ships, or was trimmed), nothing is
    written. Rows are never created from the restore side.

**The index is a convenience and never a dependency**, the same stance as
`dqcommon.index_store`. Every failure is logged and swallowed: a read or write fault, CAS attempts
running out, or an unparseable or newer-version document, which is left untouched rather than
overwritten. None of these changes a verb's return value, its raise, or the run's outcome. **The
receipt folder, not the index, says which archives exist** (FR-004), which is what makes losing an
index row cost a label and never a route to a restore.

#### Acceptance Criteria:

- [ ] With the fake S3 used by the archive verb tests, `write-receipt` leaves one entry with all the
      fields above. Run twice with the same request, it still leaves one entry.
- [ ] Two `record_archive` calls racing on one index (the second write's `IfMatch` fails once) both
      survive. This is driven through the CAS loop, not asserted on a mock's call list.
- [ ] 501 recorded archives leave 500 entries, and the oldest is the one dropped.
- [ ] `update-receipt` at `requested`, then at `restored`, leaves `restore.status == "restored"`
      with the requested time. On an index with no entry for the archive, it makes no `PutObject`
      call to the index key.
- [ ] With the index write made to raise `AccessDenied`, and separately with CAS attempts exhausted,
      `write-receipt` still returns `receiptKey` and `update-receipt`'s return and raise behaviour
      is unchanged. These tests assert the verb's actual return value, not merely that no
      exception escaped.
- [ ] An index document whose `version` is 2, or which is not JSON, is not overwritten: no
      `PutObject` to the index key is issued.
- [ ] `archive.indexKey` is `{root}system_settings/archive/index.json` in both modes. The existing
      `Validated` cross-check test still passes, because the key is nested inside `archive`.
- [ ] A test builds the worst-case entry, with every field at its bound and the escape-worst fill,
      and asserts that `ARCHIVE_INDEX_MAX_ENTRIES` of them serialize under the API's
      `MAX_DOCUMENT_BYTES`. The measurement is taken the way `objects.readContent` measures a read,
      so the whole index is always readable. The cap stays below that bound with headroom, and the
      test says why.
- [ ] At `requested`, a receipt write that fails leaves the index untouched.

### FR-004: The restore dialog lists the space's archives to pick from

#### Description:

`RestoreArchiveDialog` opens on a list of the current space's archives. A new service,
`listArchives(space)` in `archive.service.ts`, builds the list from two sources:

1. **The receipt folder is the authority for what exists.** It pages `objects.list` over
   `appManagedPrefix(root, ARCHIVE_FOLDER)`, following `nextToken`, with a runaway cap of 100
   pages. Every folder row whose name passes `isArchiveId` is an archive, and anything else there
   (`index.json` included) is ignored. A space past the cap shows the rows it loaded, and the
   id fallback (FR-005) still reaches the rest.
2. **The index supplies the labels.** It reads `index.json` through `readJsonDocument`. A missing,
   unparseable or newer-version index, or a failed read, gives every archive an id-only row. None
   of these is an error.

An index entry with no receipt folder is dropped. A receipt folder with no index entry becomes an
id-only row.

Each row is a native radio input in a `fieldset` whose legend is "Archive to restore". A row shows:

- **Title:** the name. Without one, the contents summary. With neither (an id-only row),
  "Archive " followed by the first 8 characters of the id.
- **Details:** "Archived {date}", then the contents ("reports/, q1.csv and 1 more"), then "{n}
  files, {size}", with the size rendered by `lib/format`'s `formatBytes` and the date by
  `formatAbsoluteDate`. In a shared space, "by
  {username}" is added. An id-only row reads "Details unavailable" and shows the full id.
- **Status:**
  - `restored`: "Restored {date}". The radio is **disabled**, because a completed restore has
    already swept the vault.
  - `requested`: "Restore requested {date}". The row stays selectable, because this status is also
    what a restore that died before its last write leaves behind, and a disabled row would be a
    dead end.
  - `incomplete`: "Last restore did not finish". The row stays selectable.

  No status text calls the archive intact, complete, safe or gone, per the restore-message fence.

Rows sort by archive date, newest first. Id-only rows go last, ordered by id. Restored rows sort
among the others by date. The list scrolls inside the dialog (`scrollBody`), and nothing is
selected at first. Clicking **Restore** with nothing selected shows "Choose an archive to
restore." and enqueues nothing. `submitDisabled` is not used, because a disabled control is not a
refusal. With an archive selected, **Restore** enqueues through the existing `useRestoreArchive`
submit with that archive's id. Enter does not submit from a radio: the dialog passes no
`submitOnEnterRef` in list mode. On open, focus does not land on a radio. `FormDialog`'s own
guidance names a radio group as the case where arrow keys would then make a choice the user never
made, and the plan picks the focus target.

The dialog also has these states:

- **Loading:** "Loading archives…" in a `role="status"` region.
- **Empty:** "This space has no archives yet."
- **Error** (the folder listing itself fails): "Couldn't load this space's archives." with a
  **Try again** button that refetches.

The fallback link (FR-005) is present in every state. The list is a TanStack Query keyed per space
in `queryKeys`, fetched when the dialog opens. It is not refetched on window focus while the dialog
is open, and it is invalidated after a successful restore enqueue.

The sentence naming the destination ("Everything in the archive is restored to {space}, back where
it came from.") and the several-hours sentence stay as they are.

#### Acceptance Criteria:

- [ ] Given two receipt folders (one indexed with a name, one not indexed) and an index entry for a
      third id with no folder, the dialog shows exactly two rows. The named one comes first by
      date, and the id-only row reads "Details unavailable" and shows the full id.
- [ ] A folder listing that spans two pages yields the rows from both. The test asserts the second
      `objects.list` call carried the first page's `nextToken` unmodified.
- [ ] A `restored` row's radio is disabled. A `requested` row's and an `incomplete` row's are
      enabled.
- [ ] Clicking **Restore** with no selection shows "Choose an archive to restore." and makes no
      `archive.restore` call.
- [ ] Selecting a row and clicking **Restore** sends `archive.restore` with that row's `archiveId`
      and a fresh `requestId` that differs from it.
- [ ] An index read answering 500, and separately an index body that is not JSON, still render
      every folder as an id-only row, with no error banner.
- [ ] A folder listing answering 500 shows "Couldn't load this space's archives." and a **Try
      again** that refetches. On success the rows appear.
- [ ] A shared space's rows carry "by {username}". A personal space's rows do not.
- [ ] On open, `document.activeElement` is not a radio input.
- [ ] No status string contains "intact", "safe", "complete" or "gone". A test sweeps every status
      string.
- [ ] `vitest-axe` reports no violations for the list state, run against the driven container.
- [ ] At 375px wide, with a 100-character name and a 200-character item path, the dialog has no
      horizontal scroll and every row's radio is reachable. Checked live, with the result recorded
      in the PR.

### FR-005: Restoring by id stays available, behind a link

#### Description:

Under the list, in every state, a link-styled button reads **Restore by archive id instead**. It
switches the dialog to today's id field: the same `Input`, validation, error sentence and
placeholder, and the existing where-to-find-it hint (the receipt folder under `system_settings` →
`archive`). In id mode, Enter submits from the field as it does today (`submitOnEnterRef`), and a
**Back to the list** button returns to the list. The selection made in list mode is kept when
switching back. Submitting in id mode sends the typed id, and the list selection is ignored.

#### Acceptance Criteria:

- [ ] The link is present in the loading, empty, error and list states.
- [ ] In id mode, an invalid id shows today's error sentence on **Restore** and makes no call. A
      valid id sends `archive.restore` with it, lowercased and trimmed as today.
- [ ] In id mode, Enter in the field submits. In list mode, Enter on a focused radio sends nothing.
- [ ] **Back to the list** restores list mode with the earlier selection still checked.
- [ ] The existing `RestoreArchiveDialog` id-validation tests are kept, driven through the link.

### FR-006: The notification, Help and the record point to the list

#### Description:

- **The archived notification** (`arcommon.messages.archived_message`) keeps naming the archive id.
  Its instruction changes from "... and enter this id" to "... and pick it from the list". The
  shared-space variant keeps naming the space.
- **Help `archive-files`**: the steps describe the Name field, the list (name, date, contents,
  status), the **Restore by archive id instead** fallback, and where the id is found. The callout
  keeps the overwrite-nothing and "move or rename" rules. The subtitle keeps the "restore them to
  where they were" sense, which a peer's test in `help.test.tsx` pins.
- **The record**:
  - `lambdas/info/planes/archive.md` gains the index in *The key layout* and a line in the layer
    table. Its fence bullet about the archive coming "from a pasted id" is marked in place: the id
    is now picked from a list or pasted, and the server treats it the same.
  - `docs/decisions/archive-and-restore.md` gains one entry: the receipt folder is the authority,
    the index is a label that may be lost, the name rule, and why a `requested` row stays
    selectable.
  - The 90-day entry's claim that the dialog shows the charge becomes true again.
  - `apps/portal/info/component-inventory/archive-feature.md` updates the rows for both dialogs and
    adds `listArchives`.

#### Acceptance Criteria:

- [ ] `archived_message` for a personal and for a shared archive contains the id and "pick it from
      the list", and no longer contains "enter this id". The messages module's existing
      denylist/plant corpus stays green.
- [ ] The `archive-files` guide mentions "Name", "Restore by archive id instead" and "system_settings".
      A `help.test.tsx` assertion covers the first two.
- [ ] `scripts/validate_docs.py` passes, including its no-spec-number-in-comments rule over every
      touched `.ts`, `.tsx` and `.py` file.

---

## Data Model

```ts
// apps/portal/src/types/archive.types.ts

/** An archive request, as the browser enqueues it. `name` is absent when the user gave none. */
export type ArchiveRequest = {
  requestId: string;
  space: ArchiveSpace;
  items: ArchiveItem[];
  name?: string;
};

/** One index entry, exactly as `arcommon.index_store` writes it. */
export type ArchiveIndexEntry = {
  archiveId: string;
  name: string | null;
  archivedAt: string;            // ISO-8601, the execution start
  archivedBy: string;            // username
  items: {kind: 'file' | 'folder'; path: string}[]; // at most 3, relative to the space root
  itemCount: number;             // how many were selected
  fileCount: number;
  totalBytes: number;
  restore: null | {status: 'requested' | 'restored' | 'incomplete'; at: string};
};

/** `{root}system_settings/archive/index.json`. */
export type ArchiveIndexDocument = {version: 1; archives: ArchiveIndexEntry[]};

/** One row of the restore picker. `details` is null for an archive the index does not label. */
export type ArchiveListing = {
  archiveId: string;
  details: Omit<ArchiveIndexEntry, 'archiveId'> | null;
};
```

```python
# lambdas/archive-common/arcommon/config.py
ARCHIVE_NAME_MAX_CHARS = 100
ARCHIVE_NAME_REFUSED_RANGES = ((0x00, 0x1F), (0x7F, 0x9F), (0x200E, 0x200F),
                               (0x2028, 0x202E), (0x2066, 0x2069))
ARCHIVE_INDEX_MAX_ENTRIES = 500
ARCHIVE_INDEX_NAME = "index.json"
```

## API / Interface Contract

```ts
// archive.service.ts
enqueueArchive(req: ArchiveRequest): Promise<ServiceResult<void>>; // sends `name` only when present
listArchives(space: ArchiveSpace): Promise<ServiceResult<ArchiveListing[]>>; // sorted as FR-004 says

// archiveName.ts — the one browser-side statement of the name rule
export const ARCHIVE_NAME_MAX_CHARS = 100;
normalizeArchiveName(raw: string): string;
archiveNameRefusal(normalized: string): string | null; // the user-facing reason, or null

// useArchive.ts
useArchive(space, notify).submit(name: string): Promise<boolean>;
useArchiveList(space: ArchiveSpace | null, enabled: boolean): UseQueryResult<ArchiveListing[]>;
```

```python
# arcommon/index_store.py
def record_archive(bucket: str, key: str, entry: dict) -> bool: ...   # never raises
def record_restore(bucket: str, key: str, archive_id: str, status: str, at: str) -> bool: ...  # never raises
# arcommon/paths.py
def index_key(name: str) -> str: ...
```

## File & Folder Structure

```
apps/portal/src/
├── features/archive/
│   ├── ArchiveDialog.tsx / .test.tsx          (copy, Name field)
│   ├── RestoreArchiveDialog.tsx / .test.tsx   (list, picker, id fallback)
│   ├── ArchiveList.tsx / .test.tsx            (the radio list and its states)
│   ├── archiveName.ts / .test.ts              (the name rule)
│   ├── archive.service.ts / .test.ts          (name on the wire, listArchives)
│   └── useArchive.ts / .test.ts               (submit(name), useArchiveList)
├── lib/queryKeys.ts                           (archive list key)
└── types/archive.types.ts
lambdas/
├── archive-common/arcommon/{config,paths,receipt,messages,restore,index_store}.py
├── archive-validate-authorize/   (name, indexKey)
├── archive-write-receipt/        (Name line, record_archive)
├── archive-update-receipt/       (record_restore)
├── api/apicommon/{contract,bounds}.py
└── test_archive_name_browser_mirror.py
```

## Implementation Phases

### Phase 1: The plane learns names and keeps the index (FR-002 server half, FR-003)

- `arcommon.config` constants, `paths.index_key`, and the name rule with `invalid_name` and its
  message.
- validate-authorize: the allowed field, `archive.name` and `archive.indexKey` in both modes
  (`restore.validate` for the restore mode).
- `receipt.render`'s `Name` line.
- `index_store` on `cpcommon.cas`, called from write-receipt and update-receipt, with every failure
  swallowed.
- Contract `name: NotRequired[str]`, the `Bound` row, the regenerated TS contract, and the size
  chain.
- The archived message's instruction (FR-006, server half).

### Phase 2: The browser (FR-001, FR-002 browser half, FR-004, FR-005)

- `archiveName.ts` and its Python mirror test.
- The `ArchiveDialog` copy and Name field.
- `listArchives` and `useArchiveList`.
- `ArchiveList`, and `RestoreArchiveDialog`'s list and id modes.

### Phase 3: The record (FR-006)

- Help `archive-files`, the plane page, the register entry, the inventory, and the live checks
  folded into `docs/testing/e2e.md`.

**Landing order:** Phase 1 must deploy before a browser sends `name`. Validate-authorize rejects
unknown fields, so a browser that ships first has every named archive refused as
`malformed_event`. The Lambdas and the SPA image deploy from separate workflows, so they go in
separate PRs, the plane first.
