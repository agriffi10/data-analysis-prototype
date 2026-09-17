# Archive — control plane

Moves a user's files into a separate `GLACIER` vault the browser has no relationship with, and
brings them back. **This is the only place in the portal where a mistake is unrecoverable**, and the
machine is shaped around that fact rather than around the happy path.

"Put this away": move a file or folder out of a user's space into a separate bucket at the `GLACIER`
storage class, delete the original, and leave behind a plain-text receipt. Reversible only through a
restore request that takes **hours**, not a click.

A restore is `RestoreObject` + a 3–5 hour wait + a copy. Both modes — archive and restore — run
through the *same* state machine, routed by `ChooseMode`. **One plane serves both**, on the
create/refresh branch's precedent, rather than a sixth module. The `Choice` guards every comparison
with **`IsPresent`**: a `Choice` on an absent path raises an uncatchable `States.Runtime`, and
`Default` does not cover it.

## Why GLACIER, and what that costs

**The storage class is the whole design.** `GLACIER` (Flexible Retrieval) is not readable, and a
`CopyObject` whose source is in it fails `InvalidObjectState` — which is what forces the
`Wait`/poll loop no other plane here has.

`GLACIER_IR` was rejected because it is readable in real time: it deletes the restore machinery, but
it makes "archive" mean "moved to a cheaper bucket". `DEEP_ARCHIVE` was rejected too — 12 to 48
hours, and a 180-day minimum.

The **90-day minimum duration is surfaced to the user** in the confirm dialog: archive on Monday,
restore next week, and you are still billed for 90 days.

**Retention is a CEILING, not a floor.** A 7-year expiry lifecycle, deliberately **bucket-wide with
no prefix filter** — the inverse of the admin bucket's prefix-scoped rule, which exists only because
that bucket mixes retained and expiring content. Object Lock is out of scope: it needs versioning,
and in compliance mode it would make the vault cleanup impossible.

## The bucket the browser cannot see

**The archive bucket is the first bucket the browser has no relationship with at all** — no CORS,
absent from the CSP `connect-src`, and the portal role holds **zero** statements naming it. What the
browser does get is a **Deny**: `PutObject`, `DeleteObject` and `AbortMultipartUpload` under
`archive/` in **both** space buckets, so a receipt cannot be forged or deleted by the user it
describes. `lambdas/test_archive_bucket_isolation.py` pins the IAM half and
`lambdas/test_api_module.py` pins `connect-src`'s exact term set, because it is a NEGATIVE claim and
those rot silently.

**The delete grant is the one this role could not inherit.** Every other plane's execution role
carries a blanket `Deny s3:DeleteObject` from its first apply; this one cannot, so the property that
replaces it is written out: `DeleteObject` on the two SPACE buckets only, plus an explicit **Deny**
under `athenaresults/`, `user_settings/` and `archive/`, and on any `DO_NOT_DELETE.txt` at any depth.
IAM is the second line — the first is the commit gate, and `arcommon.delete.assert_deletable` refuses
the whole list **before issuing anything**, so a key the policy would refuse fails the run rather
than stopping a deletion half way through.

**`ARCHIVE_BUCKET` is NOT a `cpcommon.config` required var.** That set is a fleet-wide contract every
plane's Lambda environment must satisfy; a variable only this plane sets belongs in
`arcommon.config.archive_bucket()` — a *function*, so the layer stays import-safe.

## The key layout

**The archived key encodes its own origin.** `personal/alice/archive/{uuid}/reports/q1.csv` came from
`alice/reports/q1.csv`, so every restore destination is rebuilt from a `ListObjectsV2` over the
archive prefix. **The receipt is a report, not a record** — the same posture as judging a table by
its shape rather than by the marker it also writes.

**The leading `personal/` / `shared/` segment is not cosmetic.** Nothing anywhere checks a proposed
shared-space name against the User Pool, so a user `alice` and a space `alice` can both exist. Flat,
they would share one archive prefix — and since restore authorizes by *space* and then reads whatever
sits there, a member of space `alice` could restore user `alice`'s files. Receipts need no such
segment: they live in each space's own bucket.

**Containment lives in `cpcommon.paths`, not in `arcommon`.** Archive is the third plane to ask "is
this key inside the root I authorized?", and it is the one place a second copy is a cross-tenant
read. `fscommon.paths` re-exports the three names.

## The machine

`infra/modules/archive/state-machine.asl.json.tftpl` — the largest in the repo, because the restore
branch is a wait loop with two guards.

**Archive:** `ValidateAuthorize → ChooseMode → InspectSource → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → CommitOrRollback → WriteManifest → DeleteSource →
WriteReceipt → NotifyArchived`

**Restore:** `ValidateAuthorize → ChooseMode → InspectArchive → CheckDestinationClear →
BuildRestoreManifest → MarkRestoreRequested → RetrieveObjects (Map) → NotifyRestoreStarted →
WaitForRetrieval ⇄ PollRestore → ReCheckDestinationClear → CopyBackObjects (Map) →
CollectRestoreResults → DeleteArchived → UpdateReceipt → NotifyRestored`

## The fences

- **The destination guard is ABSOLUTE, and it runs TWICE.** Any occupied destination refuses the
  *whole* restore, and a **403 counts as occupied**. The second pass (`ReCheckDestinationClear`) is
  the spec correcting itself: the billed 3–5 hours are spent telling the user a restore is in
  flight, so re-creating a file meanwhile is the ordinary case — and the copy-back would otherwise
  have overwritten it, reported success, and swept the vault. **It is absolute at the check, not yet
  at every write**: the copy-back is unconditional, and two restores of one archive can run at once
  because the Pipe starts executions `FIRE_AND_FORGET` —
  [the register](../../../docs/decisions/archive-and-restore.md#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)
  says what that does.
- **Retrieval is the point of no return.** `RetrieveObjects` tolerates **no** failure, where
  `CopyBackObjects` tolerates 100% — a fault there means nothing was copied and the archive is
  untouched. What makes that free is that `archive-initiate-restore` tolerates two codes,
  `RestoreAlreadyInProgress` and `InvalidObjectState`, which is also what keeps the path
  unconditional on the storage class. **Do not "harden" the verb by removing them.**
- **The source is deleted only when EVERY object is confirmed copied**, and the gate is a *state*:
  the rollback arm cannot reach `DeleteSource`. That is asserted by walking the ASL graph, and an
  unrecognisable verdict fails closed.
- `archive-delete-archived` is the one deletion allowed to fail quietly — it sweeps the vault after
  a successful restore, and a leftover object costs storage, not data. **The vault sweep may fail
  quietly and the source deletion may not**, on the same algorithm with opposite consequences: a
  half-deleted source means a user told their archive completed while their files are half there,
  where a half-swept vault costs storage the 7-year expiry reclaims. So it is a `cleanupIncomplete`
  flag on a SUCCESSFUL run. Deleting inside the 90-day minimum is an early-deletion fee, not a defect.
- **THE COMMIT GATE IS THE MACHINE'S SHAPE.** `collect-transfer-results` returns one boolean — every
  object copied, or not — and `CommitOrRollback` branches on it. Three ways to be short collapse into
  one verdict: a reported item failure, an export accounting for fewer items than the manifest, and a
  manifest disagreeing with the plan. **"Copied 900 of 1000, deleted 1000" is the failure this
  feature must never have.**
- **The rollback deletes by LISTING the archive prefix**, never from a collector-supplied key list.
  Keys are the unbounded term, and the prefix is this request's alone — so the listing also catches
  objects a batch copied before it died and never reported, which a list could not. A rollback that
  itself fails partially does **not** change the outcome: the residue is billed at the GLACIER 90-day
  minimum, is unreachable by the user, and is swept by the 7-year expiry.
- **Most durable to least:** `_manifest.json` into the vault, then the source deletion, then the
  receipt into the user's own space. A receipt therefore only ever exists for an archive that
  completed — and its write failing **fails the run** even though the data is safe, because a user
  with no receipt has no id and no route to a restore. The message says the data IS archived, and
  names the id.
- **The receipt is REWRITTEN, never re-rendered.** The archive lines record the archive run, and its
  start time is the one field no restore can recompute, so a fresh render would blank it on the only
  durable record the user has. Keyed on the two LABELS, every other line verbatim. A **proven** 404
  composes a fresh document; a 403 raises rather than overwriting a receipt this plane merely failed
  to read.
- **THE RESTORE'S GATE IS THE COMMIT GATE'S MIRROR IMAGE, not its twin.** Archiving's gate protects
  the SOURCE; this one protects the ARCHIVE, and the reason runs the other way — a partial restore
  cannot be rolled back, because the user's space already holds some of their own data. So the
  failure arm deletes **nothing**, and the archive it keeps is the only complete copy left.
  `restore_incomplete` says all three things: how many came back, that the archive is intact under
  the same id, and that re-requesting will report the files that DID land.
- **Completion is the `Restore` HEADER, and an absent header is a FAILURE.** Nothing about an
  archived object changes when its retrieval finishes — it stays `GLACIER`, and what appears beside
  it is a temporary copy the header describes — so "no header" on a Glacier object means nobody ever
  asked, not "not yet". Read as pending, it would burn every iteration and then report a timeout
  naming the wrong cause. The poll SAMPLES: progress is an S3 pointer beside the plan, and one
  invocation sweeps as far as complete pages allow rather than one page per `Wait`.
- **The copy IS what changes the storage class**, so `STANDARD` is stated and never omitted. The
  engine treats an absent class as "do not pass the argument", so relying on S3's default would be
  invisible in the code and would land every restored object back in `GLACIER` — looking like a
  success until it expired to unreadable.
- **A restore takes its SPACE from the request and its ARCHIVE from a pasted id**, so authorization
  is a question about *that* space, and an archive belonging to another one simply is not found:
  `archive_not_found` never distinguishes "never existed" from "not yours". The id is matched against
  `arcommon.paths`' one UUID rule **before** it is concatenated into a key, and the root is then built
  by the same `archive_root` that wrote it. `requestId` ≠ `archiveId` is enforced — the run and the
  archive are different things, or a refused restore could not be re-submitted.
- **The front door serves both modes and returns the SAME five keys.** `ChooseMode` sits downstream
  of validate-authorize and reads `$.mode` off the parsed request, because in the raw Pipe record that
  field is inside an escaped JSON string ASL cannot look into — so a separate restore validator is not
  possible, and one shared `Validated` Pass means a key present in one mode and absent in the other
  would raise an uncatchable `States.Runtime`. `source` is therefore the authorized SPACE in both: the
  archive's source in one, the restore's destination in the other.
- **One body table, two prefixes, and the failure path carries `mode`.** The codes only one mode can
  reach are unambiguous; the ones BOTH reach — `forbidden`, `malformed_event`, `invalid_request` — are
  exactly the ones a single "Couldn't archive that" prefix gets wrong. Every failure seed supplies
  `mode`, a literal `null` on the pre-identity one, whose input is the raw error. One code has no
  body at all: `request_id_reused`, refused in `InspectSource` when the archive prefix already holds
  objects, is told to nobody, because the run that archived under that id is the one that reports
  ([the decision](../../../docs/decisions/control-planes.md#a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is-the-one-that-reports-data-quality-file-operations-archive)).

## The two budgets

**`TimeoutSeconds` is top-level and ships WITH its EventBridge `TIMED_OUT` rule** — notify-failure's
second door, and its 15s → 60s raise. Catchers do not cover a top-level execution failure. It is
sized by a **makespan** (`MAP_MAX_CONCURRENCY` × `CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s),
never an aggregate; a test adds the copy, the per-child overhead and the seven serial verbs, and
reads the ceiling out of `locals.tf`.

It was raised from 10,800 to 43,200, and not because the data grew: the restore arm's long pole is a
*wait*, and a 3-hour ceiling would have killed healthy restores before S3 finished with them. It is
one field on one machine, so the archive arm's backstop rose with it — a wedged archive is now
reported after twelve hours rather than three, which is accepted and pinned by a test asserting the
archive arm still clears the ceiling by more than 4×.

**The retrieval budget has deliberate headroom:** 7 hours against a tier whose worst case is 5.
Giving up on a retrieval that was going to finish makes the user pay for a SECOND billed one, while
waiting costs an invocation every five minutes.

**`RESTORE_HEAD_CONCURRENCY` is bounded by botocore's CONNECTION POOL, not by the thread count.**
"Workers × timeout / latency" says to widen the pool until the arithmetic fits, but
`boto3.client("s3")` takes the default `max_pool_connections` of 10 — threads past that contend, and
urllib3 discards sockets rather than reusing them, so a wider pool buys throughput the client cannot
deliver while every bound computed from it reads as satisfied. Eight workers; the guard's 600-second
**timeout** is what pays for 20,000 heads. A test reads the ceiling off botocore.

## The layer — `archive-common/arcommon/`

| Module | Holds |
|---|---|
| `authz` | source authorization for the plane |
| `config` | domain configuration |
| `delete` | batched deletion, refusing over the **whole** list (unlike `focommon.delete`, which is per item) |
| `guard` | the destination guard — nothing a restore would write over may already exist |
| `manifest` | `_manifest.json`, the integrity record written before anything is deleted |
| `messages` | user-facing archive and restore wording |
| `notify` | best-effort outcome notifications |
| `paths` | the archive key layout, and the inverse that survives a lost record |
| `plan` | the copy plan, expanded once and passed by pointer |
| `receipt` | the receipt — the one artifact of an archive the user can see |
| `restore` | the restore request contract, and the archive it names |
| `retrieval` | Glacier retrieval: asking for the bytes back, and knowing when they are there |

The verbs are listed in [`../INDEX.md`](../INDEX.md). The UI's one refusal — the archive dialog never says "this can't be
undone" — is in `CLAUDE.md` → *The browser*.
