# File send — control plane

Sends a user's files to other users: "send these files to Bob". A received file lands in
`shared_files/{sender}/` in the recipient's own space. The browser cannot write into another user's
prefix — that is the isolation model working — so this needs a privileged path for the same reason
table share does.

**Its own plane, not a mode of table share.** The two share an *algorithm* (`cpcommon.transfer`) and
nothing else: a different request contract, a different authorization question, a different failure
vocabulary. One queue and one DLQ under two unrelated features would have the DLQ drain, which names
the feature by the DLQ, report a dead-lettered send as a share.

## The machine

`infra/modules/file-send/state-machine.asl.json.tftpl`

`ValidateAuthorize → Validated → InspectSource → GuardRecipients (Map) → BuildTransferManifest →
HasTransferItems → TransferObjects (Map) → CollectTransferResults → ShapeSummary → NotifyOutcomes`

Two Maps: one guards each recipient's inbox for collisions, one moves the bytes.
`ValidateFailureSeed`/`RequestFailureSeed → RecordFailure → NotifyFailure → Failed` has been complete
from day one.

**The failure seeds read the request back from `$$.Execution.Input`.** The validate task's input is
the Pipe's JSON *array*, so its catch cannot carry a `ResultPath` and the error replaces the state;
without the context read, `NotifyFailure` would take its no-recipient branch on every failure.
Threading the request through the state was tried and rejected — the Pipe record carries the same
selection again as an escaped string, so it roughly doubles the payload for the whole run.

**There are TWO seeds, and the second is not decoration.** `RecordFailure` names fields the state
has to carry — `traceparent`, `requestId`, `actor` — and a `Pass` hard-fails on an absent key, so a
catch routed straight to it raises an uncatchable `States.Runtime` and the sender hears nothing. The
envelope is the one field that is *not* such a read: it comes from `$$.Execution.Input`, which no
seed supplies and no catch can lose. The fleet guard identifies a seed structurally by
`error.$ == "$"` and **cannot see the second shape** (`"$.error"`, because that catch carries a
`ResultPath`), so the plane's own suite walks every catch instead.

**`TimeoutSeconds` (10,800) is top-level and ships WITH its rule.** Catchers do not cover top-level
execution failures, so an EventBridge `TIMED_OUT` rule — never `FAILED` — invokes `notify-failure`
through a second door. On this plane that needs `states:DescribeExecution` to read the input back,
because EventBridge drops an input this plane's own cap allows to approach 200 KB.

## The request envelope

`{requestId, traceparent, identity: {actor, delegated_by, assurance}, source: {space, items},
recipients[]}`,
plus a **legacy top-level `actor`** still carrying the raw ID token until the API stops sending
one. Unknown top-level fields are **rejected, not ignored**.

**The verb reads the block and never the flat field**, which matters because both are non-empty
strings: a fallback would build a notification recipient out of a 900-character token on the first
message enqueued before the cutover. The flat field stays in the allowed set deliberately —
removing it makes such a message a `malformed_event` instead of the `unauthorized` refusal that
path is meant to produce — and the DLQ drain redacts it as a stale token.

The original reason for the flatness still holds and now explains the block's shape rather than
the field's: the drain's redaction replaces **top-level keys only**, which is why the identity
block is nested (nothing in it is secret and all of it must stay readable in a dead-letter
record) and why a nested *token* would have been the wrong shape.

`MessageGroupId` is the SHA-256 of `{bucket}/{spaceRoot}` — a hash, because SQS caps it at 128
characters and an S3 key reaches 1024. `MessageDeduplicationId` is the `requestId`, which is the only
double-submit guard.

## Authorization, containment and expansion

**Authorization is about the SOURCE only.** A `personal` source must equal the verified username —
never a lookup, because the username *is* the prefix. A `shared` source needs `is_active_member`,
meaning the space's own status is `active`. A member whose join chip reads *pending* is authorized,
since access is granted at add time. Recipients are **not** an authorization question: any space by
name, any existing user, with unreachable ones annotated and carried.

**Containment is two rules and a third about ancestors**, and it is the one place here where a bug is
a cross-tenant read:

1. A trailing-slash-normalised root, so `alice2/` never passes as inside `alice/`.
2. Any `.` or `..` **path segment** refused outright, because `"alice/../bob/x".startswith("alice/")`
   is `True`.
3. `athenaresults/` refused as the folder, as anything under it, **and as any folder that contains
   it** — selecting the space root passes (1) and (2), and a folder is expanded by listing its
   prefix. Folder keys are normalised to a trailing slash for the same reason.

Rule 3 is **new to this plane**: the browser's `protectedFolders.ts` keeps three divergent lists and
none of them refuses copying *out* of it.

**Expansion happens once, in `inspect-source`, and travels by pointer.** A `file` item HEADs; a
`folder` walks `cpcommon.s3_listing` past its 1,000-key pagination boundary. The plan goes to
`{admin}/file-send/{requestId}/copy-plan.json` — the object list is two orders of magnitude over the
256 KB payload limit, so inline was never tunable — and only `{copyPlanKey, objectCount, totalBytes}`
return to the state. Each entry carries its owning item name, its key **relative to that item**, its
absolute source key and its size: everything the manifest builder needs, with no second listing.

## The fences

- **The destination path is built by ONE function** in `fscommon.paths`, and an AST sweep forbids a
  second. The layout is `{targetRoot}shared_files/{sender}/{item}[/{relKey}]`. Namespacing by sender
  mirrors `shared_tables/{table}/`, so two senders never collide and provenance is visible in the
  file browser with no metadata lookup — and it is independent of the sender's own folder depth.
  Keying by item **name** is what forces the two refusals an overlapping selection needs: an
  **overlapping** selection and two items whose **names** would collide are whole-request terminals,
  while a **repeated** item collapses.
- **Exclusion rules anchor at the listing prefix** — whichever item the user picked — so this plane
  anchors its own at the **space root** instead. Reusing `is_ignored` would silently drop a user-made
  `reports/athenaresults/` and any `_drafts/` from a copy. `list_data_objects` took an optional
  `ignore` predicate rather than being forked. A genuinely empty **file** is sent; a folder
  **placeholder** (zero bytes, trailing slash) is not, so an empty subfolder does not survive a send.
- **The guard's expected refusals are RETURN VALUES**, not exceptions, because a conflict must name
  the colliding item and a `TerminalError` cannot carry one to a user.
- **`NotifyOutcomes` is the ONE producer** of every per-recipient outcome, running on the terminal
  summary rather than inside the Maps: the sender per outcome, the recipient on success only, a
  `space` through its registered **owner**, a failed recipient told nothing. Its link carries the
  RECIPIENT's own space root (`/files?prefix={recipientRoot}shared_files/{sender}/`, plus `?space=`),
  because the route keeps a `?prefix=` only when it starts with the resolved space's root — a
  root-relative one is discarded and lands them at their space root. Its `Catch` goes to
  **Succeeded**: the copy has already happened, and a missed message must never turn a delivered send
  into a failed execution.
- **No shared-space directory is published**, and the same reticence applies here: the share dialog
  suggests only spaces you belong to.
- **The browser's only privilege remains `sqs:SendMessage`.** The **Send to…** control sits on the
  selection toolbar, and `useFileSend` mints the `requestId` per SUBMIT — that is the FIFO dedup id,
  and therefore what makes a retry possible rather than a queue-level guard.
- **No Lake Formation admin designation** — no table is created here. A `NoDataObjectDelete` **Deny**
  ships from the first apply, and the only write into a user's space is `*/shared_files/*`.
- **The execution role is on the user-space bucket policy's allowlist** — read that before building
  any future plane that touches the user-space bucket.

## The transfer

The shape table share established, reused rather than re-derived: a fast inline **guard Map** (one
delimited listing of `{targetRoot}shared_files/{sender}/` per recipient — a `MaxKeys=1` probe per
item **cannot** answer the question, because `/` is not the lowest byte a key may carry); a
`(recipient × object)` JSONL manifest beside the plan; a **top-level** Distributed Map with
`STANDARD` children and `ToleratedFailurePercentage: 100`; and `collect-transfer-results` reading
`SUCCEEDED_n` **as well as** `FAILED_n`/`PENDING_n`, reconciling the count against the manifest. A
recipient is `ok` only if none of its items failed, and an earlier terminal is never overwritten.

## The caps

Six, because there are six quantities, and each is measured against its own budget.

| constant | value | what sizes it |
|---|---|---|
| `SEND_MAX_OBJECTS` | 20,000 | what the selection EXPANDS to, against the plan held in `inspect-source`'s 1024 MB — a test reads that back from `locals.tf` |
| `SEND_MAX_TOTAL_BYTES` | 1 TiB | one selection's bytes at `cpcommon.transfer`'s **makespan** rate (500 MB/s, never the aggregate 4 GB/s) |
| `SEND_MAX_OBJECT_BYTES` | 10 GiB | `COPY_TIMEOUT_SECONDS` — one object is one worker, and a batch is one round of the pool |
| `SEND_MAX_TRANSFER_ITEMS` | 50,000 | the memory the two verbs either side of the Map hold the manifest in |
| `SEND_MAX_TRANSFER_BYTES` | 3 TiB | the machine's own ceiling |
| `SEND_MAX_ITEMS` | 200 | the per-item work |
| `SEND_MAX_ITEM_BYTES` | 96 KiB | the serialised selection against the chain it travels |

`SEND_MAX_OBJECTS`' timeout twin is sized per-**item**, not per-page: a `file` costs its own serial
HeadObject, so 200 files is 200 round trips where 20,000 objects is 20. Both product caps are
measured on the **requested** recipient count, before the guard.

`SEND_MAX_ITEM_BYTES` bounds the chain SQS body → the Pipe's record with that body **re-escaped** →
`StartExecution`'s 256 KB limit. A count cap cannot bound bytes, since a control character escapes to
six, and a byte cap measured against the state alone permits a request whose execution cannot start.
The producer mirrors both, held to the Python constants by a test.

## The layer — `file-send-common/fscommon/`

| Module | Holds |
|---|---|
| `authz` | source authorization |
| `config` | domain configuration |
| `copy_plan` | the copy plan, passed by pointer |
| `expand` | turning a validated selection into the concrete, bounded object list |
| `inbox` | what a recipient's inbox already holds from one sender |
| `messages` | user-facing outcome wording |
| `notify` | best-effort outcome notifications |
| `paths` | key containment and the destination layout — the one builder |

The verbs are listed in [`../INDEX.md`](../INDEX.md).
