# Completed Spec — SPEC-237: A Restore Never Copies Over a File, and One Archive Id Is One Run

## What was completed?

Three windows on the archive plane, all of which needed two runs overlapping — which the FIFO queue
was believed to prevent and does not, because the Pipe starts a Standard machine fire-and-forget.

- **A restore never writes where something already is.** Every line
  `archive-build-restore-manifest` writes carries `ifAbsent`, and `cpcommon.transfer.copy.copy_one`
  turns that into `IfNoneMatch: "*"` — on `CopyObject` for a single copy, and on
  `CompleteMultipartUpload` alone for a multipart one, because S3 accepts it on neither the create
  nor the part copies. The destination guard still refuses the whole restore up front; what this
  adds is the rule holding at every WRITE, for the hours the copy-back Map runs.
- **A refused write is resolved, never reported as a collision.** `_already_copied` heads both
  objects and compares ETag, length, content type and user metadata. Without it a batch retrying
  after one item's transient fault would meet its own earlier writes and report the files it had
  just restored as being in the way. `DestinationOccupied` and `copy_batch`'s new `occupied_reason`
  carry the other outcome through as a distinct per-item reason.
- **`cpcommon.cas` tells the two conditional-write codes apart.** `is_precondition_failed` (412, a
  fact about the object) and `is_conditional_conflict` (409, a fact about the race);
  `is_precondition` is now their union and behaves exactly as before.
- **One archive id is one run.** `arcommon.plan.claim_archive_id` takes a create-only write on
  `archive/{requestId}/claim.json` after `assert_archive_unused` and before anything else is
  written, so S3 decides between two runs that race past the listing together. `StampExecution`
  moved to the head of the archive arm so inspect-source has the execution to claim with.
- **No restore message can be followed into losing the only copy.** Two rules over every body the
  restore resolver can render (`arcommon.messages._BODIES` less `ARCHIVE_ONLY`) and every line
  `arcommon.receipt` writes on a restore: no destructive instruction, and no claim about the
  archive's present condition. `cpcommon.messages.register` gained a `suffix` so the safety
  sentence belongs to the resolver rather than to each body. `restore.archive_is_intact` counts the
  vault, and `restore_archive_cleared` / `restore_incomplete_occupied` are what the count selects.
- **The image build proves its own runtime.** A `RUN python -c` step fails the build on a botocore
  whose S3 model does not accept `IfNoneMatch`, because the alternative is a restore failing its
  copy-back after three to five billed hours.

### Deliberate deviations

- **The comparison reads four fields, not the eight a multipart copy carries.** The spec's
  decision 2 said "everything the copy carries"; that sentence is corrected in the spec. Comparing
  content encoding, disposition, language, cache control, expiry or a website redirect would risk a
  false collision whenever S3 renders one back differently — and a false collision is a file the
  user is wrongly told to move. The residual is in the register entry.
- **Rule 2 is enforced as a phrase list**, so `destination_occupied_after_retrieval`'s "will stay
  ready for a few days" is not caught. It invites no deletion, so it is one more misleading report
  rather than the unrecoverable case; recorded in the Fences.
- **The claim EXPIRES**, where data quality's deliberately never does. It lives under the prefix the
  plane's grant and lifecycle rule already cover; a test reads the queue retentions and the
  machine's ceiling and fails when the margin closes.

## What changed from earlier specs?

- **`cpcommon.transfer.copy` is the shared engine** for archive, file-ops, file-send and
  table-share. `copy_one` gained `if_absent` and `copy_batch` gained `occupied_reason`, both
  defaulting off: a line with no `ifAbsent` issues a byte-identical request, asserted on the
  argument set for all four callers on both copy paths.
- **`transferOutcome` gained `occupied`** on both arms of the archive plane's collector.
- **SPEC-169's state order changed** — `StampExecution` runs before `InspectSource`. Marked in
  place in that spec's delivery doc, and now pinned by a test; nothing held it before.
- **SPEC-171's `restore_incomplete` is reworded and has two siblings.** The receipt's incomplete
  line no longer says "The archive is intact" under any circumstances.
- The in-app Help guide's restore paragraph said "Move, rename or delete them" — the same
  instruction FR-007 removes from the notifications.

## Verification

Formatter, both linters, both suites, mypy, `npm run build`, `tofu fmt`/`validate`,
`validate_docs.py` and its corpus, the app-managed and feature-flag validators, the contract
regeneration diff and the three PR-queue corpora, all green by exit code — CI runs none of those,
so the local run is their only gate.

**The Dockerfile's new assertion is gated by CI, not by that local run.** `lambda-image.yml` builds
the real image from `lambdas/Dockerfile` on every pull request touching `lambdas/**`, before the
merge, so a malformed step fails the PR rather than `main`. Worth stating because the opposite was
believed while this was being built: "CI runs none of the gates" is true of the suites and the
linters and was wrongly generalised to the image, from reading `ci.yml` without enumerating
`.github/workflows/`.

Mutation-tested: the 412 resolution in both directions, the claim's removal, the retention bound
four ways, the absent-field guard, every member of the partial-outcome exemption set, and the
stamp's ordering.

**Owed:** every test of the conditional write drives a fake. The deployed behaviour is a row in
[`owed.md`](../testing/owed.md) — no signed-in session can invoke a verb directly. The message
wording IS clickable and is folded into [`e2e.md`](../testing/e2e.md) §4.11.
