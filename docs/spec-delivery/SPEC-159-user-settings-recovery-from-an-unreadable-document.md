# Completed Spec — SPEC-159: `user_settings/` Recovery from an Unreadable Document

## What was completed?

A write path that could not read the live document used to refuse **forever** — `user_settings/`
denies `s3:DeleteObject`, the bucket is unversioned, and there is no admin UI, so one bad body
permanently disabled saving queries and recording history for that user. It now **quarantines and
proceeds**, and it tells a *newer* document apart from a corrupt one. **No IAM change**: `GetObject`
+ `PutObject` inside the user's own prefix, both already granted; no `.tftpl` was touched.

- **`classifyDocument({body, version, empty, isReadable})`** (`lib/s3Json.ts`) — the three-way parse:
  `readable` / `newer` / `unparseable`. Written once for both documents, which had byte-identical
  parsers differing only in the array field's name. The version check runs **before** the shape
  check, so a newer document is newer whatever else it contains.
- **`quarantineDocument({bucket, key, now?})`** (`lib/s3Json.ts`) — a server-side `CopyObject` to
  `{key}.unreadable-{ISO-8601 basic UTC}-{token}.json`. The bytes never enter the browser. Issues
  the command itself and imports nothing from `features/`.
- **`WriteOutcome<T>`** — `ServiceResult<T> & {recovered?: boolean}`, so a *successful* write can
  still report that the previous document was set aside.
- **Both write paths** (`savedQueries.service.ts`, `queryHistory.service.ts`) resolve their document
  through one `storeForWrite`/`historyForWrite`: readable is used as-is, `newer` is refused
  untouched, `unparseable` is copied aside and the write proceeds from the empty document — **only
  if the copy succeeded**.
- **Six error codes** in `lib/errorMessages.ts` replacing `SavedQueriesUnreadable` /
  `QueryHistoryUnreadable`, which no longer describe a terminal state.
- **The Query screen speaks all three outcomes** for saved queries; query-history writes stay silent
  per the existing `logBackgroundFailure` calibration, and still recover.

### The random token in the quarantine key is load-bearing

`CopyObject` copies whatever is **live at copy time**, and nothing ties the copy to the body the
caller classified. With a key derived only from a clock, two tabs that both find the same corrupt
document in the same second would collide: the first copies the corrupt bytes aside and repairs the
document; the second copies the now-**repaired** document over the first one's quarantine object,
destroying the only surviving copy of what the user actually had — on a folder that denies delete,
in a bucket with no versioning. A per-call token makes the loser write a redundant object instead.
Found by the fresh-context review, and it is the reason FR-002 AC3's "unique per event" is now
tested at the **same** timestamp rather than one second apart.

This leaves the ordinary last-writer-wins race on the document itself alone. That one is accepted
(`writeJsonDocument`), and conditional writes are explicitly out of this spec's scope.

### Deliberate deviations

- **The primitive's tests live in `lib/clientAdapters.test.ts`, not a new `lib/s3Json.test.ts`.**
  The spec's file tree assumed `s3Json.ts` had no suite; it does — SPEC-155 put `readJsonDocument` /
  `writeJsonDocument` in `clientAdapters.test.ts`. A second file would have split one module's
  coverage across two. The spec's File & Folder Structure was corrected in place.
- **`classifyDocument` is a shared classifier, not a per-document parser.** The spec's Data Model
  listed only the two types. Both documents' write parsers were twins, and a tightened classifier
  reaching one and not the other is exactly the drift the repo discharges elsewhere.
- **`removeSavedQuery` and `updateQueryHistoryEntry` forfeit their unknown-id no-op shortcut after a
  recovery.** Not spelled out in the spec, but required by FR-003 AC1: against a recovered (empty)
  document the filter/patch changes nothing, so the early return would take the quarantine copy and
  then leave the unreadable document exactly as broken as it was found — and now silently.
- **The recovery reaches the screen on the mutation's success value.** `ServiceResult`'s success
  branch has no message field, so `upsertSavedQuery` resolves `WriteOutcome`, `useSavedQueries`
  resolves `SavedQueriesWrite = {store, recovered}`, and `QueryWorkspace` toasts on the flag.
  Widening `ServiceResult` repo-wide for one signal was the larger change.
- **The recovery toast is `info`, the two refusals stay `danger`.** The write succeeded, so `danger`
  would be wrong — and `info` is the one variant that does not auto-dismiss after four seconds. The
  host is single-toast, so a later push still replaces it: this buys attention, not a guarantee.
- **`SavedQueriesRecovered` is worded for the WRITE, not for the save.** Delete reaches the same
  toast, and FR-004 AC1's "this query was saved" would be a plain lie there. Both halves of AC1 that
  matter — the copy was kept, the earlier queries are not in the list — are said. The review caught
  this by driving the real Delete flow; there is now a test that does the same.
- **Three of the six codes cannot reach a user, by FR-004 AC6's own design.**
  `QueryHistoryNewerVersion` / `QueryHistoryQuarantineFailed` are produced but only ever reach
  `logBackgroundFailure` (dev-only), and `QueryHistoryRecovered` is not produced as a *code* at all —
  history recovery is a `recovered: true` flag that `useQueryHistory` deliberately drops. The
  spec's code table and its "stay silent" criterion disagree; the criterion won, and the wording is
  kept so a future surface has it. Their coverage is `toUserMessage` directly, which for the
  saved-queries trio would not have been acceptable.

## What changed from earlier specs?

- **`SavedQueriesUnreadable` / `QueryHistoryUnreadable` are gone.** They named a terminal state that
  no longer exists. The nearest replacement is `…QuarantineFailed` — same wording ("nothing was
  changed"), now reached only when the document could not be read *and* could not be copied aside.
- **A `version: 2` document is no longer "unreadable".** SPEC-155-era tests classified it alongside
  syntax errors; it is now `newer`, refused untouched, and answered with "reload the page" instead
  of "Contact the Administrator".
- **`useSavedQueries`'s mutations resolve `{store, recovered}`**, not a bare `SavedQueriesStore`.

## Docs sweep

- **Help & guides: nothing.** This is an error path, not a flow — SPEC-074 documents shipped flows,
  and the spec puts a Help entry out of scope.
- **Component inventory:** `foundations.md` — rows for `classifyDocument` and `quarantineDocument`;
  the `readJsonDocument`/`writeJsonDocument` row now points write paths at the classifier.
- **`decisions/`:** *An unreadable settings document is quarantined, never deleted and never
  overwritten* — with the two consequences FR-005 AC3/AC4 require be recorded.

## Verification

`format:check`, `lint`, `build` and `test` (1731 passed) clean locally.

A fresh-context review walked all five FRs criterion by criterion and mutation-tested seven
load-bearing claims — including inverting the newer/unparseable classification, letting the write
proceed on a failed quarantine, removing both no-op forfeits, and deleting the recovery toast.
**All seven broke a test**, and the tests that matter assert *ordering*
(`['Get','Copy','Put']`) and *absence* (`commands === ['Get']`) rather than mere success. It also
re-derived the no-IAM-change premise from the policy templates rather than from the empty diff:
`portal-role-permissions.json.tftpl` grants unconditioned `GetObject`/`PutObject` on
`${aws:PrincipalTag/username}/*` (exactly what `CopyObject` needs on both ends), and
`portal-role-analytics.json.tftpl` denies delete across the whole `user_settings/*` subtree.

Its three substantive findings — the quarantine-key collision, the delete path's save wording, and
FR-005's unrecorded criteria — are fixed above rather than carried.

**Nothing is owed live.** The recovery path needs a genuinely corrupt document to reach, which
cannot be staged from the browser: the folder denies delete, and every document the app writes it
serialized itself. The `CopyObject` is inside the user's own prefix under grants SPEC-011 made and
SPEC-013 already exercises on every upload.
