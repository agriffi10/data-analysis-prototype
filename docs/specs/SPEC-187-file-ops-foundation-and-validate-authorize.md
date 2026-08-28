# Spec: File Operations — the Plane, the Request Contract & validate-authorize

**ID:** SPEC-187
**Status:** Completed
**Last Updated:** 2026-08-17
**Depends On:** SPEC-164/165/166/167 (the file-send plane as the pattern), SPEC-107/125/156 (`cpcommon`), SPEC-126 (DLQ drain), SPEC-152 (`NotifyFailure` on every plane), SPEC-157 (the per-target lock, and why FIFO is not serialization), SPEC-160/161 (`cpcommon.transfer`), SPEC-168 (`mode`-branching one plane; a role that ships with no S3 grant), SPEC-169 (the commit gate, and the delete-Deny set), SPEC-150/172/173 (the protected-folder rules this plane must now enforce)

## Overview

Copying, moving and deleting a **folder** is the only thing this application does whose cost grows
with the number of objects, and it is the only such thing still done by the browser. `copyFolder`
issues one `CopyObject` per object in a strictly sequential loop; `moveFolder` does that and then
deletes; `deleteFolder` lists the whole subtree and batches the deletes. A user renaming a large
folder must keep the tab open while thousands of round trips run one at a time from their laptop,
and a closed tab leaves the operation half-done with no record that it ever started.

Every other bulk data operation in this product — shared-space lifecycle, table creation, table
share, data-quality checks, file send, and archive/restore — is a control plane: enqueue, expand,
copy through a Distributed Map, attribute the results, notify. This spec starts the **seventh**, for
the operations the file browser has been doing itself.

This spec builds the plane and its front door: the queue, the pipe, the state machine, the execution
role, the domain layer, the per-space lock, and the first real verb — **validate-authorize**, which
proves from the verified ID token that the caller may read the source and write the destination, and
that neither names a protected location. Nothing is expanded or copied yet; the machine ends in a
placeholder terminal.

## Scope

### In Scope

- `infra/modules/file-ops/`: a **FIFO** request queue + DLQ, an EventBridge Pipe, a **Standard**
  state machine, one shared execution role, and the `focommon` domain layer beside `cpcommon`.
- The **request contract** the browser enqueues, covering all three operations on one plane,
  including its conflict field (FR-008), and its FIFO `MessageGroupId` / dedup rules.
- **validate-authorize**: verify the ID token, take `username` from the verified claim, authorize the
  **source** and (for copy/move) the **destination**, enforce containment on both sides, refuse
  protected locations, and enforce the request-shape caps.
- **A per-space lock** (FR-009), on SPEC-157's precedent, because FIFO ordering does not serialize
  executions.
- A skeleton machine — validate-authorize → `AcquireLock` → `ChooseOperation` → placeholder states →
  terminal — carrying its `NotifyFailure` state before `Fail` on every failure path from day one,
  with **two** failure seeds (FR-010).
- Browser IAM and its wiring (FR-011); the bucket-policy allowlist entry (FR-012); the execution
  role's deliberately **empty** S3 grant (FR-013).
- **Deploy-role IAM expansion** as in-scope work — this adds new resource types, so
  `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split*
  are required reading before the first `.tf` line.
- Registering the new request DLQ with SPEC-126's drain sweep list, in all three places it lands
  (FR-012 AC4).

### Out of Scope

- Listing, expanding, planning or copying anything — SPEC-188.
- The transfer, the source deletion and the commit gate — SPEC-189.
- Any UI change, and any notification other than the SPEC-152 pre-verb failure path — SPEC-190/191.
- **Single-file operations.** A selection of exactly one *file* stays synchronous — see FR-002. So
  `copyObject`, `moveObject` and `deleteObject` keep their current call sites, as do `createFolder`,
  upload, download and every read: none of those is a selection the predicate ever sees.
- **Raising the 5 GiB single-object ceiling.** `copyObject` issues a plain `CopyObjectCommand`, whose
  S3 limit is 5 GiB, and FR-002 keeps a single file synchronous regardless of size — so a 10 GiB
  single-file copy keeps failing as it does today. Pre-existing, now enshrined by the boundary rule,
  and recorded here as an accepted residual rather than discovered later. `cpcommon.transfer` is the
  multipart path if a later spec wants it.
- Sending files to another user, sharing a table, or archiving — those planes exist and are unchanged.
- Any change to `cpcommon.transfer`. This plane is its fourth caller and must fit the engine as it is;
  a required change to the engine is an escalation, not a silent edit.
- Cross-space operations the browser cannot already express. `DestinationPicker`'s reach is the
  contract, and widening it is not this arc's business.

### What the browser does today, and which spec replaces it

The cheapest defence against a five-spec arc silently losing a behaviour.

| Behaviour today | Owner |
|---|---|
| Collision pre-flight + "Overwrite all / Cancel" | **REMOVED for enqueued gestures** (user decision, arc review). The plane's guard is the only collision authority; `overwrite` is reachable only through SPEC-190 FR-005's round trip |
| Rename collision → "overwrite **or type a new name**" | SPEC-190 |
| Same-folder copy auto-number `{name} (N)`, HEAD-probed | SPEC-190 |
| Into-itself guard | FR-005 — check (2) of the ordered three-step list |
| Same-key no-op returning **success** | FR-005 — check (1) of the ordered three-step list |
| `onProgress(processed, total)` percentage | SPEC-190 (in-flight state) |
| Per-key partial-failure list → `OperationSummaryBanner` | SPEC-189 (collection) → SPEC-191 (surfacing) |
| Selected `DO_NOT_DELETE.txt` refused | FR-006 — the marker AC |
| **Nested** marker excluded from the plan, never failing the folder | SPEC-188 |
| Client-side protected-folder refusals | Retained as the affordance; FR-006 adds enforcement |
| Folder **rename** (`useMove` passes the full new prefix, not the parent) | FR-005 via `item.targetName` |
| Same-folder copy auto-number `{name} (N)` | FR-005 via `item.targetName`; the probe stays in the browser |
| Zero-byte placeholders: an empty subfolder survives a move; an "empty" folder still deletes | Premise 4 below → SPEC-188 |
| Listing invalidation after every operation (`invalidateListing`) | SPEC-190 — it becomes reconciliation, not invalidation |
| Copy is **not** gated by `writeLockReason` — copying *out of* `archive/` works | FR-006 AC3's rule extended: write-lock is a delete/move-source rule, never a copy-source one |
| "Refresh access" recovery on a shared-space `AccessDenied` | **UNCHANGED — this row was wrong.** The trigger is a *listing* error and the listing stays browser-side; nothing in this arc moves it. SPEC-190 pins that it still works |

### Premises SPEC-188 and SPEC-189 must honour

Stated here because those specs are not yet written and each of these is a decision, not a detail.

1. **The source deletion removes exactly the keys that were CONFIRMED COPIED — the plan's keys for
   items that fully succeeded, and never a prefix listing.** Both halves are load-bearing.
   *Never a prefix listing* **diverges deliberately from SPEC-169**, whose archive rollback lists the
   prefix precisely so it catches objects a batch copied before it died: here the same technique loses
   data, because an object written into the source folder between expansion and commit — by an upload,
   a single-file operation, or another plane, none of which take FR-009's lock — was never copied, and
   a prefix-listing delete would remove it silently and unrecoverably with versioning off. The
   accepted cost is an **orphan**: it survives, stranded in a folder the user believes moved, which is
   visible and recoverable where the alternative is neither.
   **What "never a prefix listing" forbids, precisely (clarified by SPEC-189 FR-006):** it forbids
   *listing the source prefix at deletion time*. It does **not** forbid the deleting verb re-reading
   the PLAN from S3 — which is how the keys actually arrive, because the transfer engine reports
   counts and never keys (a failed-key list is the unbounded term that breaches the state limit on the
   Map). Per-item gating makes "the plan keys of a fully-succeeded item" and "the keys confirmed
   copied" the same set, so the plan re-read satisfies this Premise rather than violating it.
   *Confirmed-copied rather than blanket-planned* follows from the per-item decision below. Before per-item
   outcomes the two sets were identical, which is why SPEC-169's gate could be all-or-nothing. **A
   skipped item is planned and not copied** — so deleting plan keys would remove the user's source
   file while the destination still holds the colliding object that displaced it: a direct,
   unrecoverable substitution. This needs its own `decisions/` entry against SPEC-169's.
2. **The commit gate is therefore PER ITEM.** SPEC-169's gate is one boolean over the whole run —
   every object confirmed copied, or nothing is deleted. That cannot express "these three items
   copied, this one collided", so the gate becomes per selected item: an item's source is deleted only
   when that item's own objects are all confirmed copied. Premise 3 below is the same rule at the
   object level.
3. **The source deletion is CONDITIONAL on the bytes that were copied** — `IfMatch` on the ETag **the
   PLAN recorded** (amended by SPEC-189 FR-006 AC8; it originally said "the ETag the copy recorded",
   which names an epoch nothing produces — the copy is issued unconditioned and records no ETag). Premise 1 covers objects that were never in the plan; it does not cover a **planned
   object whose bytes changed after the plane copied it**. A single-file upload (which FR-002
   deliberately keeps synchronous and unlocked) can overwrite `alice/reports/q4.csv` after the
   transfer and before the deletion — leaving the destination holding the *old* bytes while the delete
   removes the *new* ones. A failed condition is a per-item failure, not a silent skip.
4. **Zero-byte folder placeholders are KEPT.** The two existing expanders disagree — file-send drops
   them (an empty subfolder does not survive a send) and archive keeps them — so silence here would
   be resolved by whichever was copied. Keeping them matches today: `copyFolder`/`moveFolder` carry
   placeholders so an empty subfolder survives a move, and `deleteFolder`'s recursive listing returns
   the folder's own marker so an "empty" folder still disappears.
5. **Per-item outcomes travel all the way through.** FR-006 and FR-008 make protected-location and
   conflict refusals per item; the expansion, the transfer's result collection and the notification
   producer each have to carry that, or the partial execution `OperationSummaryBanner` reports today
   is lost between specs.

---

## Functional Requirements

### FR-001: The plane

#### Description:

The infrastructure, following the shared control-plane pattern.

#### Acceptance Criteria:

- [ ] A FIFO request queue and FIFO DLQ exist, with content-based dedup **off** (the request supplies
      an explicit `MessageDeduplicationId`), and a redrive policy onto the DLQ.
- [ ] An EventBridge Pipe delivers to a **Standard** state machine; `REQUEST_RESPONSE` is not used
      (impossible for a Standard machine — settled in SPEC-157).
- [ ] One execution role serves every verb; a `focommon` layer holds this plane's wording and key
      layout, with `cpcommon` supplying every algorithm — no algorithm is forked into `focommon`
      (SPEC-156). A test asserts `focommon` defines no CAS loop, no SQS parser, no message resolver
      and no transfer primitive.
- [ ] **The ceiling set here is PROVISIONAL and SPEC-189 owns its final value.** This machine does no
      work, so the number can only be guessed — yet FR-009's `STALE_LOCK_SECONDS` and give-up bound
      are both derived from it. SPEC-189 re-derives all three together once the makespan is known.
- [ ] **The joint budget is one constraint, not four independent bounds:**
      `giveUp + (2 x guard sweep) + serial verbs + transfer makespan + deletion <= TimeoutSeconds`.
      Each bound reads as satisfied alone while the sum overruns — the wrong-quantity trap SPEC-161
      records four times.
- [ ] `TimeoutSeconds` is set **top-level** on the machine, shipping together with its EventBridge
      `TIMED_OUT` rule and the second door into `NotifyFailure` — never `FAILED`, or every caught
      failure double-notifies (SPEC-161/166). The ceiling is also what makes FR-009's stale-lock
      steal meaningful; the two ship together or neither works.
- [ ] **The door reads the execution input back with `states:DescribeExecution` on the Lambda role.**
      EventBridge drops an input this plane's own cap allows to approach 200 KB, and FR-007 measures
      that cap against `StartExecution`'s 256 KB exactly as file-send's does — so this plane inherits
      file-send's problem, not table-share's exemption. Inheriting table-share's shape here is
      recorded as having left an FR half-delivered.
- [ ] `lambdas/test_deploy_matrix.py` covers every new function: the deploy matrix and what each
      function imports agree.

### FR-002: What belongs on this plane, and what does not

#### Description:

The boundary between a synchronous operation and an enqueued one, stated once so every later FR and
the browser both read the same rule.

#### Acceptance Criteria:

- [ ] An operation stays synchronous **if and only if the selection is exactly one item and that item
      is a file**. Everything else — any folder, and any multi-item selection — is enqueued.
- [ ] The predicate is consulted only for a **non-empty** selection; an empty selection never reaches
      it, and an empty `source.items` is a request-shape refusal in FR-007. Without this, "not exactly
      one item" routes a zero-item selection to the plane.
- [ ] The rule is a property of the **selection**, never of the operation name: the same selection
      routes the same way for copy, move and delete.
- [ ] A **single folder** is enqueued, including a folder **rename**. This is forced rather than
      chosen: a folder rename is one `CopyObject` per contained object, so it cannot be bounded
      without listing. A test names rename explicitly, because it is the case a reader assumes is
      synchronous.
- [ ] The rule is expressed **once**, in a single exported TypeScript predicate in the browser. The
      plane does **not** re-implement it — it processes whatever it is handed, and a request the rule
      would have kept synchronous is still valid. Enforced by a **single call site**, asserted by an
      import test: exactly one module imports `requiresControlPlane`. An AST sweep is *not* used here
      — SPEC-165's precedent forbids a second *key builder*, which has a recognisable syntactic
      signature, where a boolean over `kind` and `length` does not and would fire on every legitimate
      branch in the file browser.

### FR-003: The request contract

#### Description:

One envelope for all three operations, validated before anything else runs.

#### Acceptance Criteria:

- [ ] The message carries `requestId`, `actor` (**the raw ID token, at the top level**), `operation`
      (`copy` | `move` | `delete`), `source` (a `space` object plus `items`), and — for `copy`/`move`
      only — `destination`, `onConflict` and `submittedAt` (FR-008). Unknown top-level fields are
      rejected, not ignored.
- [ ] `source.space` and `destination.space` are **nested objects** matching SPEC-164's envelope
      (`{space: {kind, name}, …}`), not flattened — the four existing planes share this shape and
      `fscommon.authz.authorize_source(username, space)` takes that dict. Divergence would need an
      adapter for no gain.
- [ ] `actor` is **flat**, for SPEC-164's recorded reasons: SPEC-126's shared DLQ drain reads that
      field flatly and hands it to `verified_username_ignoring_expiry`, and `_redacted` replaces
      top-level keys only — a nested token would both fail to notify on a dead-letter and write the
      JWT to CloudWatch verbatim.
- [ ] `MessageGroupId` is the **SHA-256 hex digest** of `{bucket}/{sourceSpaceRoot}` — a hash, never
      the raw path (SQS caps the group id at 128 characters while S3 keys reach 1024). It orders
      **delivery** per space and provides throughput isolation between spaces. **It does not
      serialize executions** — the Pipe starts the machine `FIRE_AND_FORGET` and returns, which is
      the finding SPEC-157 exists to record. Serialization is FR-009's lock, and no AC anywhere may
      claim otherwise.
- [ ] `MessageDeduplicationId` is `requestId`; content dedup is off on the queue, so that id is the
      only double-submit guard. The `requestId` is minted per **submit**, never reused across a
      retry — reusing it makes a retry a silent no-op (SPEC-167 FR-003's amendment).
- [ ] `destination` is **absent** for `delete` and **required** for `copy`/`move`; the wrong shape for
      the operation is a refusal, not a coerced default. Every `Choice` comparison on `operation`
      guards with `IsPresent` first — a `Choice` on an absent path raises uncatchable
      `States.Runtime`, and `Default` does not cover it (SPEC-143).
- [ ] Keys are **absolute** — `item.key` and `destination.prefix` are full S3 keys including the space
      root, matching what the browser already holds and what every other plane sends. A
      space-relative key is a refusal, detected by the containment check in FR-005 rather than by a
      separate rule.
- [ ] A malformed or unparseable body fails before any AWS call and reaches `NotifyFailure`.
- [ ] Nothing from the untrusted body is used to identify the caller.

### FR-004: Source and destination authorization

#### Description:

Prove the caller may read what they name and write where they are sending it, from the verified
claim and never from the request.

#### Acceptance Criteria:

- [ ] `username` comes from the **verified** ID token claim; the request's own space fields are
      validated against it, never trusted.
- [ ] A **personal** space authorizes only when its name equals the verified username.
- [ ] A **shared** space authorizes on the space's `is_active_member` status, never on the member's
      join chip — the other reading reverses SPEC-073 (SPEC-164's recorded rule).
- [ ] For `copy`/`move`, the destination is authorized **independently and by the same rules**.
- [ ] The destination refusal message is **byte-identical whether or not the source space exists**,
      and vice versa — no existence oracle (SPEC-113's rule). Asserted by rendering both messages and
      comparing, not by inspection.
- [ ] An unreachable space is refused identically to a non-existent one.

### FR-005: Containment

#### Description:

The one place a path bug becomes a cross-tenant read or write. Both sides, not just the source.

#### Acceptance Criteria:

- [ ] Every `source.items[].key` is validated against the **trailing-slash-normalised resolved source
      root**, so `alice2/` never passes as inside `alice/` (SPEC-164 FR-005).
- [ ] **`destination.prefix` is validated against the trailing-slash-normalised resolved destination
      root**, by the same function. FR-004 authorizes the destination *space*; without this AC
      nothing constrains the *prefix* within it, and a request naming an authorized shared space with
      another member's prefix would be a privileged cross-tenant write.
- [ ] `.` and `..` **segments** are refused on both sides — segments, not substrings.
- [ ] A folder key is normalised to a trailing slash before any comparison, and the destination
      prefix likewise.
- [ ] **Both guards below compare the DERIVED per-item destination key, never `destination.prefix`,
      and are evaluated PER ITEM.** `destination.prefix` is the folder items are copied *into*; the
      real destination is `destination.prefix + itemName`, **re-normalised to a trailing slash when
      the item is a folder**. That re-normalisation is load-bearing and is the whole AC: the borrowed
      helper is `fscommon.paths.item_name`, which **strips** a folder's trailing slash, so
      `"alice/" + "reports"` yields `alice/reports` against a source AC4 normalised to
      `alice/reports/` — unequal, the same-key no-op never fires, and the move deletes the source.
      (Borrow `item_name`, **not** `destination_key` — the latter prepends `shared_files/{sender}/`.)
- [ ] **The name used in that derivation is `item.targetName ?? item_name(item.key)`.** Without the
      per-item name a **rename is inexpressible**, and `useMove` has *two* call sites that differ:
      a multi-item move passes the containing folder (`` `${destPrefix}${leaf}/` ``) while a **rename
      passes the full new prefix** (`` `${parent}${newName}/` ``). Deriving from the key alone breaks
      rename both ways — send the parent and the derived destination equals the source, so the
      same-key rule reports *success having renamed nothing*; send the new prefix and it **nests**
      inside itself. Same-folder auto-numbered copy (`report (1)`) has the identical shape. FR-003
      rejects unknown top-level fields, so a later spec could not add this without a mid-arc contract
      change — which is the outcome FR-008's own rationale exists to prevent. The browser
      already compares final locations — `useMove` passes `` `${destPrefix}${leaf}/` `` into
      `moveFolder`. Comparing the containing folder instead accepts `move alice/reports/ → alice/`,
      whose derived destination **is** `alice/reports/`: every object is copied onto itself and then
      the source is deleted, unrecoverably with versioning off. An AC that names the wrong comparison
      is worse than a vague one, because it is implemented confidently.
- [ ] The three checks run in this order, per item, and the order is itself the AC:
      **(1) same-key** — derived destination equals the source key in the same bucket ⇒ **success, a
      no-op**, matching `moveFolder`/`copyFolder` today;
      **(2) into-itself** — derived destination is inside the source subtree ⇒ refusal, a prefix
      comparison on normalised keys, within one bucket only (across buckets the same prefix string is
      a different location);
      **(3) conflict** — FR-008's evaluation.
      Same-key must precede *both*: it precedes (2) because the into-itself comparison matches the
      equal case and would turn rename-to-the-same-name into an error, and it precedes (3) because
      under `overwrite` S3 rejects a `CopyObject` whose source and destination are identical.
- [ ] **`targetName` is validated by the same leaf rule the browser applies** — non-empty after
      trimming, no `/`, no control characters, no `.` or `..`, and a length cap — mirroring
      `validateLeafName`, which drives `RenameDialog` and the same-folder copy prompt today and is
      simply not carried onto a plane that accepts hand-crafted envelopes. Unvalidated it is the
      arc's sharpest hole: **`targetName: ""`** derives to `destination.prefix` itself, which merges a
      folder's *contents* into the destination and then deletes the source — and it defeats FR-005's
      own worked example, since `move alice/reports/ → alice/` then derives `alice/` rather than
      `alice/reports/` and the same-key rule stays silent. A name containing `/` or dot segments is
      not covered by AC3, which governs `items[].key` and `destination.prefix` — a *name* is neither —
      and S3 does not normalise, so the result is a real object no listing renders and the browser can
      never reach or delete.
- [ ] **Two selected items whose DERIVED destination keys collide with each other are refused**
      (`alice/a/x.csv` and `alice/b/x.csv` both into `alice/c/`). SPEC-165 made exactly this a named
      refusal for file-send, whose pattern this plane follows. Today's browser catches it only by
      accident — the second item's HEAD finds the first item's freshly-written object — so under
      `onConflict: 'overwrite'` one file would be lost and the request would report full success.
      This is a **request-shape** refusal, evaluated before anything is listed, and it is
      whole-request rather than per-item because neither of the two colliding items is the wrong one.
- [ ] Containment is re-checked in SPEC-188 against every key returned by `ListObjectsV2`, never
      assumed from this request-time check.

### FR-006: Protected locations are refused HERE, not only in the browser

#### Description:

Today `undeletableRootFolderRefusal`, `PICKER_LOCKED_FOLDERS`, `isWriteLockedPrefix` and the
marker-basename rule are client-side. A control plane makes them server-side for the first time.

**The three lists differ on purpose and must not be unioned** — `protectedFolders.ts` carries the
note, and `fscommon.authz`'s docstring records the same warning. The rule is therefore stated per
(side × operation), enumerated against the actual constants.

#### Acceptance Criteria:

- [ ] **As a destination**, refuse every folder in `PICKER_LOCKED_FOLDERS` — including
      `_data-quality-reports/` and `shared_tables/`, which a folder-name list omits and whose absence
      would let the plane accept a destination the browser's own picker refuses.
- [ ] **As a delete or move source**, refuse every folder in `UNDELETABLE_ROOT_FOLDERS` — including
      `archive/` and `saved_queries/`, the folders themselves.
- [ ] **"The folder itself, never its contents" is true for `saved_queries/` ONLY.** Its contents are
      deliberately ordinary — visible, deletable, a pasteable destination. But a delete or move of a
      file **inside** `athenaresults/` or `archive/` is refused: the role policy's `ResultsNoDelete`
      denies `s3:DeleteObject` beneath the former and IAM denies `Put`/`Delete` beneath the latter —
      and FR-013 has SPEC-189 adding exactly those Denies to this plane's own role. Without this the
      plane accepts requests its own IAM refuses **mid-operation**, the mismatch AC4 invokes to
      justify writing the `user_settings/` rule by hand.
- [ ] **That source rule carries the SAME bucket asymmetry as AC10's destination rule** — root-anchored
      in a personal space, any depth in a shared one — because it is the same predicate
      (`isWriteLockedPrefix`) asked from the other side. Do not simplify it to "at any depth" for
      both: in the personal bucket the prefix **is** the principal tag, so `alice/backups/archive/x`
      and `alice/reports/athenaresults/x` are ordinary user files IAM permits deleting.
      `useDelete` records exactly this trap as the reason `rootPrefix` is a required parameter rather
      than a defaulted one. Averaging the two buckets removes working capability, which is the same
      error as unioning the three folder lists.
- [ ] **These refusals are PER ITEM, not whole-request.** A protected item fails alone and every other
      item proceeds — matching `useDelete` today, and matching `undeletableSelectionRefusal`, which
      refuses the gesture only when **every** selected item is protected. A whole-request refusal
      would turn a select-all delete at a space root, which today deletes everything it may and
      reports the three protected folders, into a refusal that deletes nothing. Contrast FR-005, whose
      containment violations **are** whole-request: those are security failures about the request
      itself, not per-item outcomes.
- [ ] **Copying *out of* `athenaresults/` stays allowed.** It is in the picker-locked and undeletable
      lists and deliberately in neither copy-source rule; `copyFolder` calls
      `undeletableRootFolderRefusal` nowhere. A refusal here would silently remove a working
      capability, and doing it by folder name is exactly the union the source file forbids.
- [ ] **A source naming `{root}user_settings/`, for any operation, is refused** — stated as this
      plane's own rule rather than by list membership, because `user_settings` is in
      `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` but deliberately **not** in
      `UNDELETABLE_ROOT_FOLDERS`, so AC2 does not reach it. Hiding is not enforcement, and this plane
      accepts a hand-crafted envelope. Without it, SPEC-169's IAM Deny set (which names
      `user_settings/`) would refuse mid-operation what the code-side rule permitted — the mismatch
      `assert_deletable` exists to prevent.
- [ ] **An explicitly selected item whose basename is `DO_NOT_DELETE.txt` is refused at request
      time**, by basename at any depth — which is what both bucket policies deny and what
      `isMarkerName` matches. A **nested** marker discovered during SPEC-188's expansion is
      **excluded from the plan, never a refusal**: `deleteObjects` partitions the root marker out as a
      *per-key error* today and deletes everything else, and `saved_queries/` ships its own marker, so
      failing a whole folder delete on a nested marker is a regression the browser never had.
- [ ] No separate rule is written for the bucket-root `_config/` and `_directory/` documents. They
      live outside every user prefix and FR-005's containment already makes them unreachable. This is
      **not** an exemption from AC1: a shared space may legitimately contain `marketing/_config/`, the
      picker rule is anchored at the **space** root in whichever bucket, and AC1's by-reference form
      correctly refuses it as a destination.
- [ ] `archive/` is refused as a **destination** at any depth in a shared space and root-anchored in a
      personal one, mirroring each bucket's own Deny rather than averaging them (SPEC-172 FR-004). A
      test runs both rules over the same keys.
- [ ] Each refusal names the folder in operator text and maps to a **distinct reason code**, so
      SPEC-191's producer can word it without re-deriving the cause.
- [ ] **The browser's own refusals stay** — they are the affordance (SPEC-186 FR-002: refuse before
      the destructive confirm, through `Button.disabledReason`); these are the enforcement. Verified
      by **deliberate violation** on SPEC-163's precedent: a Python test submits a request the
      browser would never send and asserts the plane refuses it, and a TypeScript test asserts the
      browser's refusal is raised without any network call. Neither test can pass by accident because
      neither runtime can reach the other's rule.

### FR-006b: What validate-authorize EMITS

#### Description:

Added at arc review: this spec shipped a verb whose output shape was specified one spec later, and the
outcome vocabulary it must produce lived in SPEC-188.

#### Acceptance Criteria:

- [ ] **`focommon/outcomes.py` ships HERE**, with the closed outcome set and the `outcome`/`reason`
      split — because this verb is the first producer (`noop`, and every protected-location refusal).
      SPEC-188 extends it; it does not create it.
- [ ] The verb's output shape is stated: the resolved `source` (bucket + root) and `destination`
      (bucket + prefix), the verified `actor`, `operation`, `onConflict`, `submittedAt`, and the
      **created outcome list**. Every later verb's input is this shape plus its own additions.
- [ ] **The `ResultPath` layout is fixed here, once.** A verb's result replaces the path it is merged
      into (SPEC-188 FR-006), so the fields that must survive every hop — `operation`, the resolved
      roots, `onConflict`, `submittedAt`, `actor` — are named and their location on the state pinned
      by a test over the rendered ASL.
- [ ] Refusal wording renders through the `cpcommon` `Resolver` as a **whole sentence** (SPEC-156).

### FR-007: Request-shape caps

#### Description:

Bound what one request may ask for, before anything is listed.

#### Acceptance Criteria:

- [ ] A cap on the number of **selected items**, and a cap on the **serialised size of the
      selection**, measured on the request as submitted.
- [ ] The byte cap is measured against the **escaped** form, through the Pipe's re-escaping into
      `StartExecution`'s own 256 KB limit — SPEC-164 FR-004's PR3 amendment: S3 keys are arbitrary
      UTF-8, JSON escaping expands `"` to two bytes and a control character to six, so the same 200
      items measure 216 KB of ASCII keys and 1.2 MB of `\x01` ones. A per-key length cap may be added
      **as well** but may never replace this one.
- [ ] Every cap is **computed by a test against the budget that sized it**, never asserted as a
      literal, and the test names the schedulable unit it measures (SPEC-161's rule).
- [ ] The object-count and byte caps bounding the *expansion* are **not** in this spec — they cannot
      be known before listing and belong to SPEC-188. A `hasattr` tripwire is not a substitute for a
      computed bound and must not be introduced.

### FR-008: Conflict semantics

#### Description:

The browser's collision pre-flight becomes advisory the moment the work is async, so the envelope
must carry the user's answer and the plane must re-check.

#### Acceptance Criteria:

- [ ] The envelope carries `onConflict: 'refuse' | 'overwrite'`, required for `copy`/`move` and
      **rejected** for `delete`.
- [ ] **A FIRST submit always sends `onConflict: 'refuse'`.** The browser's pre-flight is removed for
      enqueued gestures — it was a full recursive listing of the destination inside
      `moveFolder`/`copyFolder`, exactly the object-count work this arc exists to move — so there is
      no confirm to drive before submitting, and the plane's guard is the single collision authority.
- [ ] `overwrite` is reachable **only** from the conflict round trip (SPEC-190 FR-005), where the user
      has been shown what collided. A test asserts a first submit can never carry it.
- [ ] The **plane re-checks** the destination immediately before copying (SPEC-188/189), regardless of
      any browser pre-flight. A pre-flight performed seconds or minutes earlier cannot bind a
      decision taken now — the finding SPEC-171 recorded one plane over, where a re-created file
      between the guard and the copy would have been silently overwritten.
- [ ] Under `overwrite`, the buckets have versioning **off**, so an overwrite is unrecoverable. The
      reason code and the operator text say so, and SPEC-191's wording is required to reach the user.
- [ ] **A conflict is a PER-ITEM outcome, not a whole-request refusal.** Under `refuse`, a colliding
      item is skipped and reported while every non-colliding item proceeds — matching the browser,
      where the batch prompt's **Cancel** finalises with the already-moved items kept
      (`useCopy`/`useMove`). A whole-request refusal would discard work already done and would remove
      the partial execution that `OperationSummaryBanner` exists to report.
- [ ] **"Item" here means the SELECTED item, never an expanded object.** A folder whose subtree
      contains any collision is skipped **whole**, matching `moveFolder`/`copyFolder`, which refuse
      the entire folder on any collision and report a count. The per-object reading would produce a
      **half-moved folder** — some objects at the destination, the colliding ones left behind, the
      source folder still present — a state the browser has never produced, and one no existing
      summary or notification can describe. The browser behaviour AC5 cites is per *selected* item
      too.
- [ ] The refusal **names a bounded sample** of the colliding keys relative to the space root and says
      there may be more (SPEC-170's short-circuit precedent) — never an unbounded list on the state.
- [ ] **`overwrite` is bounded by a PREDICATE, never by a carried key set.** The flag is decided at
      submit and the write happens minutes later, so an object created at the destination *after* the
      confirmation (another tab, an upload, file-send, table-share) was never part of what the user
      agreed to. The plane therefore overwrites a colliding object **only when its `LastModified`
      precedes the request's `submittedAt`**; anything newer is refused per item even under
      `overwrite`.
- [ ] The predicate is what makes this buildable, and the obvious alternative is not: carrying the
      colliding keys on the request contradicts AC6's bounded-sample rule, needs a field FR-003's
      unknown-field rejection would have to be amended for, and **the browser cannot produce the set
      anyway** — `moveFolder`/`copyFolder` compute collisions by listing the whole destination prefix
      and return only a **count**. Producing a key list would mean a full recursive destination
      listing in the browser, which is the round-trip class this arc exists to remove, and for a large
      folder it would blow FR-007's byte cap.
- [ ] `submittedAt` is validated: present for `copy`/`move`, an ISO-8601 UTC instant, and **not in the
      future** — a future timestamp would make every collision overwritable.

### FR-009: The per-space lock

#### Description:

FIFO orders delivery, not execution. Two operations in one space must not run concurrently — a
delete removing objects a concurrent move has already relocated is silent, unrecoverable data loss
with versioning off.

#### Acceptance Criteria:

- [ ] An admin-bucket object under `locks/file-ops/`, **keyed by the SHA-256 digest of
      `{bucket}/{spaceRoot}`** — the same derivation `MessageGroupId` uses, computed once and shared,
      not restated — and claimed under **ETag CAS** (`cpcommon.cas`, never a second implementation).
- [ ] The lock **body shape is defined** — at minimum `holder` (the execution ARN, `null` when free)
      and `acquiredAt` (an ISO-8601 UTC instant) — and the acquire is a **three-way branch**: absent ⇒
      `IfNoneMatch: "*"`; present with `holder: null` ⇒ `IfMatch` on the read ETag; present with a
      live holder ⇒ refused. Without this, AC12's staleness rule references an `acquiredAt` field no
      AC defines.
- [ ] A CAS failure is recognised from **both** `PreconditionFailed`/412 **and**
      `ConditionalRequestConflict`/409 and mapped to "someone else holds it" (SPEC-157). The 409 is
      the non-obvious one and an implementation handling only 412 fails open under contention.
- [ ] **A steal is never silent**: it emits a `warning` event naming the target lock and the age of
      the body it replaced (SPEC-157). The steal path carries a test matrix including the
      load-bearing case — **two simultaneous steals, only one of which may win the CAS**.
- [ ] **A copy or move into a DIFFERENT space takes TWO locks — source and destination — acquired in
      digest-sorted order.** Keying only on the source (as `MessageGroupId` does) leaves the
      destination unserialized: A moves `alice/reports/` into `marketing/` while B deletes
      `marketing/reports/`, different source digests, both run — which is this FR's own failure mode
      on the other side. Cross-space copy/move is a shipped capability (`DestinationPicker`,
      `moveItems(items, destPrefix, destBucket)`), so this is not hypothetical. Sorted order is what
      makes two locks safe: unordered acquisition deadlocks when two requests cross in opposite
      directions.
- [ ] The holder is the **execution ARN** — a request id identifies the *message*, and Pipes delivery
      is at-least-once (SPEC-157).
- [ ] The ARN is stamped by a **Pass** state, not read in the task's own `Parameters` — reading `$$`
      there wraps the payload, and every notify path reads the request at the top level (SPEC-157).
- [ ] The lock **releases by overwriting**, never by deleting — so that a release is idempotent and a
      stolen lock is detectable by CAS. (SPEC-157's own justification was its role's
      `Deny s3:DeleteObject`; FR-013 ships this role with no such Deny yet, so that reasoning does not
      hold here and must not be copied.)
- [ ] **A release that loses its CAS is logged and NOT retried.** Losing it means the lock was stolen,
      and re-writing would clobber the new holder — reintroducing the concurrency this FR exists to
      prevent, from its own cleanup (SPEC-157 FR-001).
- [ ] **A release never fails the request.** A failed release is logged at `error` and the state
      proceeds; a request that did its work and then reported failure because of its own bookkeeping
      would be worse (SPEC-157 FR-002).
- [ ] The release carries **each acquire's ETag** — plural, because AC2 may take two — and the
      `Choice` reading them is guarded by `IsPresent`: on the pre-lock failure path there is none, and
      a `Choice` on an absent path raises uncatchable `States.Runtime` (SPEC-143). An absent ETag is a
      no-op release, not an error.
- [ ] **A request that acquires the first lock and loses the second releases the first before
      refusing.** Partial acquisition is the failure mode two locks introduce, and without this AC the
      losing request wedges a space it never operated on until the steal fires. The graph walk (AC17)
      covers the refusal terminal only if the release understands both ETags.
- [ ] **The lock is NOT taken for a request `validate-authorize` rejects** — an unauthorized request
      must not be able to touch another user's lock at all (SPEC-157 FR-002).
- [ ] **The loser WAITS and retries; it is not refused.** This diverges deliberately from SPEC-157,
      whose loser is refused: that lock is per **table** and a contended refresh is a genuine
      conflict, where this lock is per **space** and covers all three operations — so deleting a
      folder in `alice/a/` and then copying one in `alice/b/`, disjoint and entirely safe, would
      otherwise produce a reliable out-of-band refusal after the UI had already accepted the request.
      A `Wait` → re-acquire loop, with a **bounded** give-up that then refuses with a notification, so
      a wedged holder cannot make a request wait forever.
- [ ] **The waiter STEALS a stale lock itself** — the staleness check (AC16) runs on every re-acquire,
      not only on the first. This is what makes the give-up bound independent of the steal threshold.
- [ ] **The give-up bound is strictly LESS than the machine's `TimeoutSeconds`, and a test asserts the
      strict inequality.** The naive chain is unsatisfiable and must not be re-derived: requiring
      give-up ≥ the steal threshold, with the steal threshold > `TimeoutSeconds` (AC15), forces
      give-up > `TimeoutSeconds` — and the waiter is a state *inside* the machine, so the ceiling
      kills it before its give-up can fire, surfacing as a bare `TIMED_OUT` rather than the refusal
      AC13 promises. The waiter does not need to outlast a steal because it performs the steal.
- [ ] **A waiter that already holds one lock and is killed by the top-level ceiling cannot release
      it** — no state runs (AC17) — so lock #1 is wedged until it goes stale and the next arrival
      steals it. This is why AC16's staleness rule is the universal recovery rather than a corner
      case, and why the give-up bound must sit well below the ceiling: the shorter the wait, the
      narrower this window.
- [ ] **Waiters are unordered, and that is accepted.** The Pipe starts executions `FIRE_AND_FORGET`,
      so N submissions against one space become N concurrent waiters polling one key with no queue
      discipline; an early submission can lose repeatedly to later arrivals. Recorded rather than
      solved — ordering would need a real queue, and the browser's own `isBusy` gate already makes
      this rare from a single session.
- [ ] **`STALE_LOCK_SECONDS` is the machine `TimeoutSeconds` plus a stated margin, and a test asserts
      it is strictly greater than the ceiling.** A threshold below the ceiling steals a *running*
      execution's lock. Asserting only that the ceiling "exists" is satisfied by any threshold, which
      is how this ships broken (SPEC-157 FR-004).
- [ ] **A lock whose body is unreadable, malformed, or carries a future-dated `acquiredAt` is treated
      as STALE and stolen.** A body nobody can read is not evidence that an operation is running, and
      the alternative is a space whose file operations can never run again (SPEC-157 FR-004).
- [ ] The lock is released on every terminal path the *graph* can reach, proved by an ASL walk —
      **explicitly excepting the top-level `TimeoutSeconds` expiry, which terminates the execution
      outright so no state runs at all.** The walk asserts that exception rather than silently not
      covering it, and the steal (above) is the named recovery. **The `TIMED_OUT` door must NOT
      release**: by the time it fires the lock may already have been stolen, and releasing would
      clobber the new holder.

### FR-010: The failure paths

#### Description:

Two seeds, because this machine has states after `validate-authorize`.

#### Acceptance Criteria:

- [ ] The machine carries a `NotifyFailure` state before `Fail`, reached on **every** failure path,
      decoding the raw `{Error, Cause}` through `cpcommon.errors.failure_reason` — the SPEC-152 fleet
      test covers the new machine with no exemption.
- [ ] The **pre-identity** seed reads the request from `$$.Execution.Input` — the catch on
      `validate-authorize` receives the Pipe's JSON *array* and has no object to merge into
      (SPEC-164 FR-001, settled by measurement; do not re-derive it).
- [ ] A **post-identity** seed exists for the states after `validate-authorize`, and it **takes the
      actor from `$.actor`** — the verified username the validator already produced — rather than
      recovering it from a token. Two byte-identical seeds satisfy "a second seed exists" while
      delivering nothing; the difference is the AC. SPEC-165 records that a post-identity catch routed
      straight to **`RecordFailure`** raises uncatchable `States.Runtime`, because that state reads
      `$.raw` unconditionally and no post-validate state carries it.
- [ ] **Every catch carries `ResultPath`** so the verified actor is not discarded (the shared-space
      defect SPEC-152 fixed), except the one on `validate-authorize`, which cannot.
- [ ] The plane carries **its own ASL graph walk**, deriving from the machine what is left on the
      state at each catch. SPEC-165 records that the fleet guard identifies a seed structurally by
      `error.$ == "$"` and misses the `ResultPath` shape — so the fleet test passing proves nothing
      here, and this plane's own walk is what must fail on a mutation.

### FR-011: Browser IAM and wiring

#### Description:

The browser's only new privilege, and the deploy wiring a `VITE_*` variable needs.

#### Acceptance Criteria:

- [ ] The portal role gains `sqs:SendMessage` on the new queue **only**; the rendered policy carries
      no `Resource: "*"` (SPEC-139's scan covers it).
- [ ] `VITE_FILE_OPS_QUEUE_URL` is added to `.env.example`, to `env.ts`'s **optional** list, to
      `deploy-app.yml`'s build env, **and** set as a GitHub Actions repository variable — a var the
      app reads without all four ships `undefined` to production, and correct IAM will not save it.
- [ ] A row is added to `lib/support.test.ts`'s registry of every `notConfiguredMessage` and the env
      var whose absence produces it.

### FR-012: Bucket policy and the DLQ drain

#### Description:

Two hand-maintained lists that fail silently when a plane is added without them.

#### Acceptance Criteria:

- [ ] The new execution role is added to the **user-space bucket policy's** principal allowlist, in
      `infra/modules/data/policies/`, threaded as a variable through the three-part change SPEC-164
      FR-006 documents. An explicit Deny beats an identity Allow, and a missing plane half-works.
- [ ] **The shared-space bucket has no bucket policy** and needs no change — stated here because
      "both buckets" is the natural assumption and there is no file to edit.
- [ ] A test fails when the plane's role is absent from the allowlist, so the omission fails the
      *test* rather than failing at runtime (SPEC-164 FR-006).
- [ ] The DLQ registration lands in **all three** places: a `Source(...)` entry in
      `lambdas/control-plane-dlq-drain/dlq_drain.py` matched by `_source_for` on the queue-name
      substring, the drain's IAM, and its queue-URL wiring. A test asserts the new DLQ is swept.

### FR-013: The execution role ships with no S3 grant

#### Description:

This role will eventually hold `DeleteObject` across the user-space bucket. It does not get it here.

#### Acceptance Criteria:

- [ ] The execution role created by this spec holds **no S3 grant on any data bucket** — only its
      logging, the lock prefix in the admin bucket, what the lock's CAS needs, **and
      `sqs:SendMessage` on the notifications queue**. That last is not an exception: FR-010 ships
      `NotifyFailure` from day one and that verb enqueues a notification, so a role without it cannot
      run this spec's own first failure path. Every other plane passes `notifications_queue_arn` into
      its execution role for exactly this verb. SPEC-168 shipped
      the archive role this way deliberately and recorded it.
- [ ] SPEC-189 adds the data-bucket grants **grants-first**, together with the explicit Deny set
      SPEC-169 established — `athenaresults/`, `user_settings/`, `archive/` and any
      `DO_NOT_DELETE.txt` — and an `assert_deletable` refusing the whole list before issuing anything.
- [ ] A test asserts the role's rendered policy names no data bucket in this spec, so the grant cannot
      arrive early and unreviewed.

---

## Data Model

```ts
// apps/portal/src/features/file-browser/fileOps.types.ts

export type FileOpKind = 'copy' | 'move' | 'delete';

/** A selected item. `key` is an ABSOLUTE S3 key; folders carry a trailing slash. */
export type FileOpItem = {
  kind: 'file' | 'folder';
  key: string;
  /**
   * The item's name at the destination. Defaults to the item's own leaf name.
   * This is what makes RENAME and same-folder auto-numbered COPY expressible:
   * both send `destination.prefix` = the containing folder and a different name.
   */
  targetName?: string;
};

export type FileOpSpace = {
  kind: 'personal' | 'shared';
  name: string;
};

/** The enqueued envelope. `actor` is added by the service, never by a component. */
export type FileOpRequest = {
  requestId: string;
  operation: FileOpKind;
  source: {space: FileOpSpace; items: FileOpItem[]};
  /** Required for copy/move, rejected for delete. */
  destination?: {space: FileOpSpace; prefix: string};
  /** Required for copy/move, rejected for delete. */
  onConflict?: 'refuse' | 'overwrite';
  /**
   * ISO-8601 UTC. Required for copy/move. Bounds `overwrite` to objects that
   * already existed when the user confirmed — see FR-008.
   */
  submittedAt?: string;
};
```

```python
# lambdas/file-ops-common/focommon/config.py  (shape only; values are computed by tests)

FILE_OPS_MAX_ITEMS: int              # selected items in one request
FILE_OPS_MAX_SELECTION_BYTES: int    # ESCAPED serialised selection, through the Pipe
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/file-browser/fileOps.service.ts

/** Enqueues one file operation. Success means ENQUEUED, never completed. */
export async function submitFileOperation(request: FileOpRequest): Promise<ServiceResult<void>>;

// apps/portal/src/features/file-browser/fileOpRouting.ts

/** FR-002's single predicate. False only for a selection of exactly one file. */
export function requiresControlPlane(items: FileOpItem[]): boolean;
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
VITE_FILE_OPS_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account>/<name>.fifo
```

Optional in `lib/env.ts`. Note its degraded path only becomes user-visible in SPEC-190, when the
browser starts routing through the plane — in this spec nothing calls the service.

## File & Folder Structure

```
infra/modules/file-ops/
├── iam.tf
├── lambda.tf
├── locals.tf
├── outputs.tf
├── pipe.tf
├── policies/
├── sqs.tf
├── state-machine.asl.json.tftpl
├── stepfunction.tf
└── variables.tf

lambdas/
├── file-ops-common/
│   ├── focommon/
│   │   ├── __init__.py
│   │   ├── authz.py
│   │   ├── config.py
│   │   ├── lock.py
│   │   ├── messages.py
│   │   ├── paths.py
│   │   └── protected.py
│   └── test_*_focommon.py
├── file-ops-validate-authorize/
├── file-ops-acquire-lock/
├── file-ops-release-lock/
└── file-ops-notify-failure/

apps/portal/src/features/file-browser/
├── fileOps.service.ts
├── fileOps.service.test.ts
├── fileOps.types.ts
├── fileOpRouting.ts
└── fileOpRouting.test.ts
```

## Implementation Phases

### Phase 1: The domain layer, the routing rule and the caps

- `focommon` skeleton: `paths`, `protected`, `messages`, `config`, `lock`.
- FR-002's predicate (browser only) and the lint rule forbidding a second implementation.
- FR-006's per-(side × operation) rules, enumerated against the real constants.
- FR-007's computed-cap tests, measuring the escaped form.

### Phase 2: The plane's infrastructure

- `infra/modules/file-ops/`: queue, DLQ, Pipe, Standard machine, execution role with **no** data-bucket grant.
- `TimeoutSeconds` plus its `TIMED_OUT` rule and the second door.
- Deploy-role IAM expansion; the user-space bucket-policy allowlist entry.
- SPEC-126 drain registration in all three places.

### Phase 3: validate-authorize, the lock and the failure paths

- Token verification, both-sided authorization, both-sided containment, protected-location refusals,
  conflict-field validation, request-shape caps.
- `AcquireLock` / `ReleaseLock` and the graph walk proving no terminal skips the release.
- Both failure seeds, `ResultPath` on every catch, and this plane's own ASL graph walk.

### Phase 4: The browser's enqueue path

- `fileOps.service.ts` over `enqueueFifo`; `VITE_FILE_OPS_QUEUE_URL` through all four wiring points;
  the `support.test.ts` registry row.
- Browser IAM: `sqs:SendMessage` on the new queue only.
- No UI change — the existing synchronous paths still run. SPEC-190 switches the browser over.

### Phase 5: Verification

A shared layer's import-time failure only shows at **cold start** (PR #196), and SPEC-137 shipped
instrumented code whose layer attachment was missing while every offline gate passed. These are real
invocations, written as a runnable script under `docs/testing/`.

- One hand-crafted valid request reaching the placeholder terminal.
- One unauthorized-source request notifying the actor.
- One request refused by each protected-location rule.
- Two overlapping requests in one space. **Name the technique, because the obvious one does not
  work**: CLAUDE.md records SPEC-157's equivalent check as unrunnable from the UI — two submits 2 s
  apart both returned independently, because the work finished inside the window. Here it is strictly
  worse: this spec's machine does no work at all, so the window is milliseconds. Use **one
  `send-message-batch` carrying two messages with the same `MessageGroupId` and distinct
  `MessageDeduplicationId`s**, or add a temporary `Wait` to the skeleton for the duration of the
  check. The load-bearing assertion is the **negative** one, stated as SPEC-170's is: while the first
  holds the lock there is **no second execution operating on the space** — the loser is waiting, and
  it proceeds only after the first releases.
- One request against a deliberately wedged lock, confirming the give-up bound fires and refuses
  rather than waiting forever.
- A cross-space move, confirming **both** locks are taken and both released.
- All of the above appearing in `logs/service=file-ops/` with `env` and `version` populated.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc.
- (The `architecture.md` → *Control Planes* section and the six → seven correction are **SPEC-191's**,
  as the arc closer — not repeated here.)
- A `decisions/` entry for the FR-002 boundary, the FR-009 lock (including why its loser **waits**
  where SPEC-157's is refused), and Premise 1's **divergence from SPEC-169** — confirmed-copied-keys-only
  deletion, and the orphan accepted as its cost. Then one line each in CLAUDE.md's Key Decisions.
- A note in SPEC-190's brief covering four things this spec discovered but does not own: FR-002's
  predicate needs a **single call site**, and the browser has four (`confirmDelete`, `confirmMove`,
  `confirmCopy`, `confirmRename`), so the branch has to move rather than be consulted four times;
  listing **reconciliation** replaces `invalidateListing`; the shared-space "Refresh access" recovery
  needs a new trigger; and **the overwrite retry is now a second submit**. That last one is a real
  interaction change: today a collision raises a prompt whose *Overwrite all* re-runs the collided
  items inside the same gesture, where on the plane a conflict is a final per-item outcome delivered
  by notification minutes later. The retry needs a fresh `submittedAt`, or FR-008's predicate will
  refuse the very objects the user just agreed to overwrite.
- A one-line row in `apps/portal/info/component-inventory/file-browser-feature.md` for `fileOps.service.ts` and
  `fileOpRouting.ts` — the area file matching their path, never the router.
- The `ARCS.md` arc entry updated with what this spec actually found (it is written ahead of the
  build, and the arc file is where a later reader looks for how the five specs compose).
- The Help sweep: **nothing user-facing changes in this spec** — the browser still runs its existing
  synchronous paths — so record that explicitly and skip, rather than leaving it ambiguous. SPEC-190
  and 191 own the user-visible change.
