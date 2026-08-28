# Spec: File Operations — the Browser's Async Model & In-Flight State

**ID:** SPEC-190
**Status:** Completed
**Last Updated:** 2026-08-23
**Build order note:** this spec lands **after SPEC-191**, not before — it consumes 191's wire shape and
its producer, and without them a folder move would acknowledge "you'll get a notification" that never
arrives, with in-flight entries that never settle.

**Depends On:** SPEC-187 (the request contract, `targetName`, `onConflict`, `submittedAt`, FR-002's routing predicate, FR-009's waiting lock), SPEC-188 (the per-item outcome vocabulary), SPEC-189 (the terminals), SPEC-191 (the extended notification wire shape this spec's conflict view reads), SPEC-155 (`OperationFeedback`, `useFileBrowserDialogs`), SPEC-186 (`Button.disabledReason`)

## Overview

The file browser's copy, move, delete and rename have always been synchronous: click, watch a
progress bar, see the listing update. This spec is where that stops being true for everything except
a single file. The plane accepts a request in milliseconds and finishes minutes later, so the browser
needs three things it has never had — a way to route a gesture to the plane, a way to show work in
flight, and a way to catch up on a listing it can no longer refresh on completion.

This is the largest user-visible change in the arc and the one with the most ways to be quietly worse
than what it replaces. The guiding rule is that **nothing the user could do before becomes
impossible**; several things become slower to confirm, and that is the accepted cost.

## Scope

### In Scope

- **The routing decision**, consulted at one place above **five** submission points.
- **Enqueueing** through `fileOps.service.ts`, including the fields the browser alone can compute.
- **In-flight state**: what the user sees between submit and outcome.
- **Listing catch-up** on window focus plus a visible manual refresh, with the latency stated.
- The **conflict round trip**, durable through SPEC-191's extended notification.
- Preserving the **single-file synchronous paths** exactly as they are.
- Feature-flag registry rows for anything newly gated.

### Out of Scope

- The notification wire-shape change itself — **SPEC-191 FR-001**. This spec consumes it.

> **INHERITED FROM SPEC-191 (2026-08-23): its FR-005, Help & guides, is IN SCOPE HERE.** 191 was
> built first, and nothing else it ships is user-reachable — the browser does not enqueue until this
> spec. Help is the exception: it deploys immediately, and a guide saying folder operations "run in
> the background and report by notification" is false until this spec lands. SPEC-074 FR-005 forbids
> documenting what is not wired end to end, so the guide work travels with the behaviour. The
> criteria are in SPEC-191 FR-005, unchanged; in summary:
>
> - **ONE guide covers these operations** — `rename-move-copy-delete` — not four. It says folder and
>   multi-item operations now run in the background and report by notification.
> - Its warning callout ("Deleting is forever…") is the line that most needs changing, because a
>   delete now succeeds **partially**. `send-files` and `archive-files` carry good precedents in the
>   same file.
> - A guide covers the **conflict round trip**: what a refusal means, and that re-submitting with
>   overwrite is unrecoverable.
> - **A guide row costs THREE edits or the suite fails**: the `GATED_SURFACES` row, a `RECIPES` entry
>   keyed by the exact accessible name, and a line in the transcribed contract table.
> - SPEC-185's guide-recipe trap does **not** bite: the guide lands in `files`, the section the Help
>   page opens on.
- Notifications' wording and links — SPEC-191.
- Any change to the plane's contract. If the browser needs a field the contract lacks, that is an
  escalation to SPEC-187, not a browser workaround.
- A real-time progress percentage — FR-003.
- Cancelling an in-flight operation. There is no cancel verb, and inventing one is a later spec.

---

## Functional Requirements

### FR-001: Routing, at one place above five submission points

#### Description:

The gestures are **not** four and they are not symmetric. Getting this list wrong is how the
same-folder copy silently keeps its synchronous path.

#### Acceptance Criteria:

- [ ] `requiresControlPlane(items)` is consulted at **one** call site, above **five** submission
      points: `confirmDelete`, `confirmMove`, `confirmCopy`, `confirmRename` — and
      **`sameFolderPrompt.onConfirm`**, which is wired in a different module and is where a
      same-folder copy actually runs.
- [ ] **The same-folder probe resolves BEFORE the routing decision.** `startSameFolderCopy` HEAD-probes
      for the first free `{name} (N)` and opens an interactive prompt; its output **is** the
      `targetName`, so the dispatcher cannot be consulted at `confirmCopy` for this path.
- [ ] **`sameFolderPrompt.onConfirm` MOVES into the dispatcher's module.** It is wired today in
      `FileBrowserDialogs.tsx`, a different module from the other four — and SPEC-187 FR-002 AC5
      permits exactly one module to import the predicate. Its two composed callbacks
      (`finishSameFolderCopy` / `abandonSameFolderCopy`) move with it.
- [ ] **After the prompt resolves, the dispatcher forks on the item kind**: a single **file** takes the
      synchronous same-folder copy; a single **folder** is enqueued with the probed name as
      `targetName`. "Then one request is built" would be false half the time — the probe serves both
      paths, because it keys a folder candidate with a trailing slash.
- [ ] **The probe runs once.** `useCopy.copyItems` has its own same-folder branch; once the prompt is
      lifted out, that branch must not be reached a second time. A test asserts one probe sequence per
      gesture.
- [ ] The dispatcher **normalises four different item sources**: `confirmRename` takes its item from
      `renaming` state, not the selection; the others take the selection.
- [ ] `confirmDelete` is **`async` and awaited by its dialog** where the other three are
      fire-and-forget. The dispatcher preserves the dialog's close-and-clear timing, or the delete
      dialog closes before the enqueue resolves.
- [ ] A selection of **exactly one file** takes the existing synchronous path, byte for byte —
      asserted by the synchronous service being called, not merely by the operation succeeding.
- [ ] Everything else enqueues, including a **single folder**, a **folder rename**, and a
      **same-folder copy of a folder**.

### FR-002: Building the request

#### Acceptance Criteria:

- [ ] A **rename** sends `destination.prefix` = the item's containing folder and
      `items[0].targetName` = the new name. A **same-folder copy** sends the same shape with the
      auto-numbered name. Neither sends a full new prefix as `destination.prefix` — `useMove`'s two
      call sites differ exactly here and SPEC-187 FR-005 records it.
- [ ] A **multi-item move or copy** sends `destination.prefix` = the chosen destination and no
      `targetName`.
- [ ] **A `delete` request carries NO `destination`, NO `onConflict` and NO `submittedAt`.** SPEC-187
      FR-003 rejects unknown top-level fields and FR-008 rejects `onConflict` on a delete, so sending
      them unconditionally means **every delete is refused at the front door**. A test asserts all
      three fields are absent from the built body — which is also the cheapest guard against the
      unknown-field rule.
- [ ] `submittedAt` is stamped at submit for `copy`/`move` and is **fresh on every submit**, including
      a re-submit after a conflict — a stale one makes SPEC-187 FR-008's `LastModified < submittedAt`
      predicate refuse the very objects the user just agreed to overwrite.
- [ ] `requestId` is minted per **submit**, and travels as the `MessageDeduplicationId`.
- [ ] **`MessageGroupId` is the SHA-256 hex digest of `{bucket}/{sourceSpaceRoot}`**, computed in the
      browser — it is the only sender. `crypto.subtle.digest` is **async**, which shapes the submit
      path, and no other spec assigns this.
- [ ] `onConflict` defaults to `refuse` for `copy`/`move`; it is `overwrite` only after an explicit
      confirmation in this interaction. A test drives the confirm and asserts the flip; one without it
      asserts no flip.
- [ ] With `VITE_FILE_OPS_QUEUE_URL` unset the user gets the mapped not-configured message rather than
      a silent no-op — the whole feature is otherwise a control that does nothing (SPEC-187 FR-011).

### FR-003: In-flight state

#### Acceptance Criteria:

- [ ] A successful enqueue is acknowledged **immediately, as acceptance rather than completion**. The
      established wording for this component's three existing async submitters is the precedent —
      `useFileSend` and `useArchive` both say "…you'll get a notification". "Moved" is a false
      statement at this point.
- [ ] **A persistent in-flight surface is NEW scope with no precedent in this repo, and is justified on
      its merits rather than by citation.** The upload queue is *not* that precedent: its provider is
      session-scoped at the shell so the work survives navigation, but its surface renders inside a
      drawer that only mounts when opened. The three async planes in this component have no in-flight
      surface at all — they toast and hand off to notifications.
- [ ] In-flight entries are session-scoped and do **not** survive a reload. They are a convenience;
      SPEC-191's notifications are the durable channel, and a persisted queue would be a second writer
      to state the plane owns.
- [ ] There is **no progress percentage**. `onProgress` is gone with the browser's loop and the plane
      reports outcomes only at the end. The surface says *what* is running and *since when*.
- [ ] **A give-up refusal has its own in-flight state.** SPEC-187 FR-009's bounded give-up means an
      accepted operation can be refused out of band minutes later; the surface must be able to show
      that, not just success or silence.
- [ ] **An in-flight entry is SETTLED when a notification carrying its `requestId` arrives.** Without
      this nothing ever clears an entry: FR-004 deliberately makes the notification *not* the listing
      mechanism, so taking that half alone would leave the surface showing a finished move forever —
      and, with the gate below, **the space unusable until reload**, which is a worse regression than
      the `isBusy` gate it replaced and which FR-003 forbids fixing by persisting the store. This is
      correlation for the **entry**, not notification-driven listing invalidation; SPEC-191 FR-001 puts
      `requestId` on the row anyway and the header bell polls on every page.
- [ ] **Two belt-and-braces bounds**, so a lost or delayed notification cannot wedge the gate: an entry
      is user-dismissible, and it expires at the machine's `TimeoutSeconds`.
- [ ] **A per-space submit gate is KEPT.** SPEC-187 FR-009 accepts unordered lock waiters explicitly
      *because* "the browser's own `isBusy` gate already makes this rare from a single session" —
      removing it invalidates a stated acceptance in another spec. The gate blocks a second submit for
      the **same space** while one is in flight in this session; it does not block other spaces, and it
      is not a correctness mechanism (two tabs defeat it).

### FR-004: Listing catch-up

#### Description:

Notification-driven invalidation is not the mechanism, and the reason is measurable.

#### Acceptance Criteria:

- [ ] The listing is refreshed **on window focus**, plus a **visible manual refresh** the user can
      reach. This is the mechanism; the notification is not.
- [ ] **The latency is stated as an accepted cost.** The notification poll is 60 s, is paused while
      the tab is hidden, and is **disabled entirely on the notifications page** — the only
      always-mounted poller is the header bell. So notification-driven reconciliation would be up to a
      minute late and would never fire on a backgrounded tab, which is precisely when a long operation
      finishes.
- [ ] Invalidation reuses `fileBrowserKeys` and `invalidateListing` — no second key-building path
      (SPEC-155's layering rule).
- [ ] A stale listing must not produce a dead end. Opening details for a deleted **file** already
      surfaces the mapped message (`getObjectMetadata` returns `NotFound`); a regression test pins it.
- [ ] **The folder details panel is the gap.** `FolderDetailsPanel` renders **synchronously from the
      listing** with no fetch, so a folder the plane has deleted shows a details panel with live
      actions and **no error at all**. This spec gives it a path to discover the folder is gone.

### FR-005: The conflict round trip

#### Acceptance Criteria:

- [ ] The conflict view is reachable **from the notification**, not only from the submitting tab —
      which is why SPEC-191 FR-001 extends the wire shape. A user who closed the tab must still be
      able to act, or the arc reproduces the problem it exists to solve.
- [ ] It presents which items conflicted, a **bounded** sample of colliding keys (SPEC-187 FR-008 AC6
      — never an unbounded list), and a control that re-submits **those items only** with `overwrite`
      and a fresh `submittedAt`.
- [ ] The re-submit is a new request with a new `requestId`; never a redrive.
- [ ] The overwrite confirmation states plainly that overwriting is **unrecoverable** — versioning is
      off — and that wording reaches the user, not merely a reason code.
- [ ] Rename's "overwrite **or type a new name**" survives: a new name re-submits with a different
      `targetName` and `onConflict: 'refuse'`, which is strictly safer and is what most users mean.
- [ ] Items that did not conflict are **not** re-submitted — they already happened, and re-sending
      them would copy them twice.

### FR-006: What must not regress

#### Acceptance Criteria:

- [~] **PARTIALLY DELIVERED — see the delivery doc.** The banner's outcome-grouped body is general
      over `FileOpItemResult[]`, but the plane's notification payload is capped at 1 KiB and carries
      no per-item field beyond the conflicts, so `"3 cleared, 1 noop, 1 protected, 1 conflict"` is
      not expressible on that channel; the run's other outcomes are told in the message beside it.
      Widening the payload is a change to a shipped plane's contract and was declined here.
      **Partial outcomes are surfaced**, and `OperationSummaryBanner` is **extended** to do it — it is
      not already the right shape. Today it renders `{count, errors[]}` with a success/warning binary
      chosen by `errors.length === 0`, and a title of the form `${pastVerb} ${count} items.` That
      cannot express "3 cleared, 1 noop, 1 protected, 1 conflict" — a `noop` is neither success nor
      error — and its title is a completion claim of exactly the kind FR-003 forbids. This spec adds
      an outcome-grouped body, a neutral variant, and names the adapter from `FileOpItemResult`.
- [ ] **The client-side refusals stay** as the affordance, refusing before the destructive confirm
      through `Button.disabledReason` so no confirm is reachable for a protected selection (SPEC-186).
- [ ] **The shared-space access-recovery trigger is UNCHANGED, and a test pins that.** It is driven by
      a **listing** error, and nothing in this arc moves the listing off the browser — so a user just
      added to a space still gets `AccessDenied` on `ListObjectsV2` exactly as today. (SPEC-187's
      replacement table carries this correction in place.) **Arc-scoped:** the next arc's SPEC-198 moves
      the listing behind the API, at which point this pin is re-derived rather than kept. Separately, a file operation
      refused because the plane could not authorize the space surfaces the mapped message.
- [ ] **The `isBusy` change is scoped by name.** The toolbar's gate is
      `del || move || copy || downloadingKey !== null` and it disables **six** controls, three
      belonging to other planes — *Check quality*, *Send to…*, *Archive* — plus Copy/Move/Delete; a
      separate upload `isBusy` gates *New folder*. This spec says which of those it changes and which
      it leaves, and it does **not** drop the in-flight **download** gate.
- [ ] **The async switchover ships behind a feature flag.** It is the largest user-visible change in
      the product and its only other kill switch is `files: false`, which removes the whole file
      browser. A flag key lands in six places, two of them Python, and publishing needs no app build —
      the cheapest insurance the arc can buy, and what makes landing this spec survivable.
- [ ] Every gated surface added or moved has a `GATED_SURFACES` row exercised in **both** flag states,
      rendering the real page rather than re-implementing the gate (SPEC-163).
- [ ] Axe passes on every new surface, asserted against the **driven** container so the closed state is
      not what gets checked.

---

## Data Model

```ts
// apps/portal/src/features/file-browser/fileOps.types.ts (extending SPEC-187's)

export type FileOpOutcome =
  | 'cleared' | 'conflict' | 'noop' | 'source_missing' | 'source_empty'
  | 'protected' | 'copy_failed' | 'duplicate'
  | 'moved' | 'copied' | 'deleted';
// NOTE: 'cleared' is a GATE verdict. SPEC-189 FR-008 forbids it at a terminal, so it never
// reaches the browser — it is in the union only because the in-flight store never sees one.

export type FileOpItemResult = {
  itemKey: string;
  label: string;
  outcome: FileOpOutcome;
  reason?: string;
  sample?: string[];
  more?: boolean;
};

/** One in-flight operation, session-scoped. Not persisted. */
export type InFlightOperation = {
  requestId: string;
  operation: FileOpKind;
  itemCount: number;
  sourcePrefix: string;
  destinationPrefix?: string;
  submittedAt: string;
  state: 'submitted' | 'settled' | 'refused' | 'expired';
};
```

## Implementation Phases

### Phase 1: The dispatcher and the request builders

- The single call site above five submission points; relocating the same-folder prompt so the probe
  resolves first; the four item sources; the awaited-delete timing; the per-operation field rules; the
  async `MessageGroupId` digest; the not-configured path.

### Phase 2: In-flight state

- The session store and its surface; acceptance wording on the existing precedent; the give-up refused
  state; the per-space submit gate.

### Phase 3: Catch-up and the stale-listing paths

- Focus refresh and the manual control; the stated latency; the folder-details gap; the file-details
  regression test.

### Phase 4: The conflict round trip and the no-regression list

- The notification-reachable conflict view over SPEC-191's wire shape; the re-submit; then FR-006 item
  by item, including the `isBusy` scoping and the pinned access-recovery test.
- **SPEC-191's FR-005 Help work**, inherited above — it becomes true in this phase, not before.
  Note the row that already exists: `Review conflicts on a notification` is registered under `files`
  and points at `/files?…&requestId=…`, which is the entry point this phase has to answer.

### Phase 5: Verification

- Integration tests through `renderWithProviders`, mocking only the service boundary: a folder rename
  enqueues with `targetName`; a single-file rename does **not** enqueue; a same-folder folder copy
  enqueues with the probed name; a `delete` body carries none of the three copy/move fields; a
  mixed-outcome terminal renders all outcomes; a conflict re-submit sends only the conflicted items
  with a fresh `submittedAt`.
- Axe on each new surface, against the driven container.
- **Live check (owed):** a folder move in the deployed app — accepted immediately, in-flight visible
  across navigation, listing correct after focus, and Safari at 400px for the CSS list.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, component-inventory rows for the dispatcher, the in-flight store and its
  surface, and the extended banner.
- `decisions/` entries for **the persistent in-flight surface** (new, no precedent) and **no progress
  percentage**. *Not* for acknowledging acceptance over completion — that is already this component's
  established pattern across three async planes.
