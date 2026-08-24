# Completed Spec — SPEC-190: File Operations — the Browser's Async Model & In-Flight State

## What was completed?

The file browser hands copy, move, delete and rename to the control plane for **everything except
a selection of exactly one file**. This is the arc's last spec and the first one a user can see.

- **The dispatcher.** `useFileBrowserDialogs` is now the only module importing
  `requiresControlPlane` and consults it at ONE call site above five submission points — the four
  confirms and `sameFolderPrompt.onConfirm`, which moved here out of `FileBrowserDialogs.tsx`.
- **The request builders** — `fileOps.request.ts` (`toFileOpItems`, `containingFolder`,
  `itemLabel`, `buildFileOpRequest`, `buildResubmitRequest`) and `useFileOpSubmit.ts`, which
  gates, enqueues, records and acknowledges.
- **In-flight state** — `FileOpsInFlightProvider` + `fileOpsInFlightContext` + the
  `InFlightOperations` surface, mounted at the app shell beside the upload queue.
- **Listing catch-up** — `refetchOnWindowFocus` on the listing, a *Refresh this folder* control,
  and `folderExists` + `fileBrowserKeys.exists` so a folder details panel can discover the folder
  is gone.
- **The conflict round trip** — `useFileOpConflicts` + `FileOpConflictsDialog`, reached at
  `/files?requestId=…` from the control SPEC-191 put on a notification row, with
  `OperationOutcomeBanner` (an outcome-grouped body and a neutral variant) and
  `fileOps.outcomes.ts`.
- **The `asyncFileOperations` flag**, on by default, in the usual six places plus two registry rows.
- **Help & guides**, inherited from SPEC-191 FR-005: `rename-move-copy-delete` rewritten, and a new
  `resolve-file-operation-conflicts` guide.

### Deliberate deviations

- **FR-006 AC1 is delivered against what the wire actually carries, and that is a partial
  delivery.** The banner's outcome-grouped body is general over `FileOpItemResult[]`, but the only
  production feed is `payload.conflicts` — the plane's notification payload is capped at 1 KiB and
  carries no other per-item field, so `"3 cleared, 1 noop, 1 protected, 1 conflict"` is not
  something that channel can express. Widening it is a change to a shipped plane's contract and
  was declined here rather than smuggled in. The run's other outcomes are told in the
  notification's own message.
- **The conflict VIEW is gated by `files`, not by `asyncFileOperations`.** Throwing the kill switch
  must not strand a conflict raised before it was thrown, and resolving one finishes work the plane
  already started rather than beginning a new gesture. It also keeps the `Review conflicts` control
  already shipping on notification rows from becoming a link to nothing. (A registry row's `name`
  is its accessible name and `RECIPES` keys are unique, so one control cannot carry a row under two
  flags — the choice had to be made rather than hedged.)
- **`isBusy` is left exactly as it was, and the per-space gate is a separate reason.** It covers
  Copy, Move, Delete **and Archive** — the four that write into this space — and deliberately not
  *Check quality* or *Send to…*, which read. Named because leaving the toolbar untouched would
  itself have been a change: with async on, `del/move/copy.isBusy` are false for the minutes a plane
  run takes, so those three controls became clickable during an operation where they used to be
  disabled. **The gate is answered per SELECTION, not per space**: a selection that would stay in
  the browser is never refused, because refusing a single-file delete the plane never sees would
  take away something the user could do before. `spaceBusyReasonFor` asks through the same private
  `routesToPlane` the dispatcher does, so the two cannot disagree.
- **FR-006 AC3's second sentence has no code here, and that is the right answer.** "A file
  operation refused because the plane could not authorize the space surfaces the mapped message" —
  an authorization refusal arrives as a *notification*, minutes later, worded by
  `focommon.messages`; it is not an enqueue error and there is nothing for the browser to map. What
  the browser does map is the enqueue's own failures (`NotConfigured`, `SelectionTooLarge`), and
  those are tested.

## What changed from earlier specs?

- **`useCopy` lost its source-prefix parameter and its same-folder branch.** `copyItems` no longer
  recognises "the destination is where these items already are"; the caller answers that BEFORE
  calling anything, because the probed name is what the routing decision is made with.
  `sameFolderPrompt` is now data only (`{kind, proposedName, validate}`) and the hook exposes
  `startSameFolderCopy`, `runSameFolderCopy` and `clearSameFolderPrompt` instead. Owning the
  callbacks there would have meant deciding sync-vs-async before the probe resolved.
- **`fileOpRouting.test.ts`'s sweep rose from "at most one importer" to "exactly one, and it is the
  dispatcher"**, plus a second assertion that the predicate is *called* once — one module reaching
  it five times satisfies the first and defeats the point of it.
- **`useFileBrowser` opts into `refetchOnWindowFocus`**, against the app-wide default. The named
  cost: this is an infinite query, so a focus refetch re-reads every loaded page.
- **`FolderDetailsPanel` now issues one request.** It renders inside the provider stack, so its
  tests moved onto `renderWithProviders`.
- **`OperationSummaryBanner.tsx` gained a second export**; the existing `{count, errors}` component
  is untouched.
- **`NotificationPayload` and `NotificationConflict` are exported from the notifications barrel.**

## What a reader would not expect

**The settled/refused distinction is read off the payload's SHAPE.** `outcome_payload` always
carries `operation`; the whole-request failure path's `request_payload` carries `requestId` alone.
Both states behave identically in the surface — dismissible, gate released — so a mis-inference
costs a word on a card, which is what makes the coupling acceptable.

**Some runs settle by neither route.** `request_payload` returns nothing in the pre-identity window
and the DLQ drain writes no payload, so a dead-lettered request is never correlated. That is what
the two belt-and-braces bounds are for, and the gate's own refusal sentence names the dismiss
affordance for exactly this case.

**A re-submit takes both spaces from the payload, never from the mount.** `reviewHref` falls back to
a bare `/files` when the row carries no usable prefix, and that page resolves the reader's
*personal* space — so a source taken from the browser would hash to the wrong FIFO group, take the
wrong per-space lock, and be refused for a space the items were never in. This is the case FR-005
AC1 exists for, so it is the case that had to work.

**A gesture whose chosen destination resolves to no known space runs in the BROWSER.** The builder
would otherwise throw and the user would get a generic failure for a request the browser could
simply have made. Same rule for a refused enqueue: the dialogs clear on the way out, before the
request resolves — the timing the synchronous paths always had — so a refusal puts the selection
back rather than costing the user every tick they made.

**The folder-existence probe reads a RAW, unfiltered key.** Reusing the browser's own listing was
the obvious design and it was wrong: `listFiles` drops a prefix's own marker object and
`useFileBrowser` filters every `DO_NOT_DELETE.txt`, so an empty "New folder" — and a
`saved_queries/` holding only its marker — would have been declared deleted.

**The per-space gate answers for the DESTINATION space too.** A cross-space copy or move takes two
locks; a gate keyed on the source alone leaves the destination open to a second submit from the
same session, which is the collision the plane's acceptance of unordered waiters leans on the
browser to make rare.

**`FILE_OPS_MACHINE_TIMEOUT_SECONDS` is pinned to Terraform by a test.** The browser mirrors the
machine's ceiling as its expiry bound; `lambdas/test_file_ops_browser_mirrors.py` reads
`state_machine_timeout_seconds` back out of `infra/modules/file-ops/locals.tf`, because an entry
expiring early tells a user an operation is over while it is still running.

**One guide could not be gated, and the cost is stated rather than hidden.**
`rename-move-copy-delete` is the single guide covering all four verbs, which work in either flag
state — gating it would leave the core of the Files section undocumented whenever the kill switch is
thrown. So the conflicts guide follows `asyncFileOperations` (its round trip exists only while the
routing does) and that one does not, which means its background-operation paragraph overstates for
as long as the switch is off. Recorded in `helpContent.ts`'s own maintenance note.

## Verification

`npm run format:check`, `lint`, `test` (2,857 passing, exit 0; coverage 92.80/89.03/92.38/94.74
against 91/86/89/93) and `build`; `pytest lambdas/` (4,467 passing, 97.48% against 95), `ruff check
lambdas/`, `mypy`; `scripts/validate_docs.py`; `scripts/validate_feature_flags.py`. No IaC changed.

Two fresh-context reviews. The plan's found two blockers and nine should-fixes; the diff's found
fifteen more, and every one is fixed. The three that mattered: the synchronous delete had stopped
being awaited (so the confirm's busy state was never seen); the in-flight surface was behind the
flag while the gate it releases was not (throwing the kill switch mid-session would have held a
space for three hours with no card to dismiss); and a destination that resolved to no known space
reached the builder's throw instead of running in the browser.

**Live checks are OWED, not run.** One row in `docs/testing/owed.md`: a real folder move in the
deployed app, in Safari at 400 px — accepted immediately, in flight across navigation, listing
correct after focus, and the notification settling the entry.
