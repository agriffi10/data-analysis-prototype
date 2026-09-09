# Completed Spec — SPEC-229: Bound the Fields Nothing Bounds, and Measure the Cap Against the Limit That Binds

## What was completed?

- **Every caller-controlled field on an enqueue request declares a bound**, in
  `lambdas/api/apicommon/bounds.py`, with the budget that sized it. The population is **derived**
  by walking `contract.walk` over all eleven `ENQUEUE_ROUTES` — 68 declared string and list paths,
  each requiring its own entry — so a field added later with no bound fails the guard rather than
  reaching a `RecordFailure` nothing can catch. A planted route with an unbounded field is the
  positive control; with `bound_for` mutated to always resolve, the fleet guard stays green and only
  the control reddens, which is why it is there.
- **A bound says which of three units its number is in** — serialized JSON bytes, the value's own
  UTF-8 bytes, or a count. They look alike as integers and one draft got two of them wrong: it spent
  `SHARE_MAX_RECIPIENTS = 50` as fifty *bytes* (so the worst case carried one recipient, understating
  file-send by 7,497 bytes), and bounded a roster in bytes, which at the shortest legal username
  admits ~2,150 names against a cap of 44.
- **The member cap is mirrored, not re-derived.** `transfer_reader.MAX_MEMBERS_PER_MESSAGE` already
  answered "what does add-members finish inside its timeout" with a fuller cost model; a second
  derivation came out at 100 against its 44. The API now mirrors it, and a guard holds the two equal
  and checks the Terraform default the derivation charges is still 60 with no per-verb override.
- **One worst-case request per route**, `lambdas/test_request_size_chain.py`, replacing three
  hand-built literals in three plane guards that disagreed. Coverage is **set equality** against
  `ENQUEUE_ROUTES`; the piped subset is derived from the presence of a `pipe.tf`, so
  `notifications.enqueue` is excluded by rule. The fill is **swept** over five characters, not
  fixed: `"` is the escape-worst into the Pipe record at a measured 2.0, and `\x01` and `é` are
  worst inside the body at six bytes each.
- **Links one, two and four computed for all ten piped routes against one constant**, with link four
  parsed from each template so a plane naming a new field is included without anyone remembering to.
  `cpcommon.config` now owns `STATE_PAYLOAD_LIMIT_BYTES`, `CAUSE_MAX_CHARS` and
  `CAUSE_RESERVATION_BYTES`, and `errors.bounded_detail` points at them instead of restating the
  numbers as prose.
- **`MAX_MESSAGE_BYTES` re-derived from the limit that binds**, in production code: 91,136 bytes
  against the old 261,632. The SQS arm survives as the queue's ceiling and is asserted unreachable.
  `ARCHIVE_MAX_ITEM_BYTES` 96 → **89 KiB** and `SEND_MAX_ITEM_BYTES` 96 → **84 KiB**, each pinned
  tight (one whole kibibyte more breaches the chain), with the SPA mirrors moved in the same change.
- **Four live overshoots characterised against the old constants**, so the suite carries the reason
  the caps moved rather than only the delivery doc: a body at the old cap producing a record over
  the limit; data-quality's `location` and shared-spaces' `space` on a `Pass` with no `Catch`; and
  the fourth below.
- **file-ops measured a quantity nothing produces.** Its cap counted the selection with
  `ensure_ascii=False`; the API re-serialises with the default escaping one hop before the Pipe. 49
  folders of accented keys passed the cap at 64,730 bytes, cost 191,134 on the wire, and produced a
  failure state 29,172 over the limit. Both sides moved to the escaped form — the cap does not
  move, ASCII selections are unaffected, and reverting the browser's half reddens exactly the new
  accented test and nothing else.
- **The refusal names the bound.** `PayloadTooLarge` carries `ErrorParams.limit`, and
  `errorMessages.ts` renders it instead of dropping it — the old sentence said "try again with less
  selected", which is false for a single over-long name with nothing selected.

### Deliberate deviations

- **One PR, not the two the grouping review approved.** The split was to be phases 1–2 then 3–4,
  cut on risk class. The diff review of phases 1–2 then found unit defects in the bounds table that
  are only visible once the chain is computed — which is phase 3 — so the halves are not separable:
  phase 1's numbers are validated by phase 3's guard. Landing the first half alone would have pushed
  known-defective code.
- **The `Cause` fixture is constructed, not captured.** FR-003 asks for a real captured Lambda
  `Cause`; nothing in the tree holds one and obtaining one needs a production failure. The
  assertions were chosen to be falsifiable anyway — the escape **ratio** and bytes per character,
  properties of the encoding rather than of one string — and the capture is recorded as owed.
- **The Pipes-record overhead reservation is modelled, not measured.** No captured Pipes record
  exists; the declaration says so, so its passing is not read as evidence about the real record.
- **`requestId` was not the live hole the spec described.** `fifo._checked` refuses a derived
  deduplication key over 128 printable-ASCII characters before the send, on the nine routes that
  make the id one. The bound is still declared — it is the chain's, and `archive.restore`'s
  `archiveId` is the genuinely unbounded id — and the spec's Overview was corrected in place.
- **`MAX_PARTITION_VALUES_BYTES` is a share, not a derivation.** Nothing in the plane says how many
  projected keys a table may declare, so "a quarter of the definition budget" is a choice and is
  written down as one. What binds is the `partitionKeys` bound, which is derived.

### What it cost users

Archive selections shrink 7.3% and file-send 12.5% against the old caps, and a file-ops selection of
non-ASCII names shrinks to roughly a third of what the old measurement admitted. All three were
capacity the chain could not actually carry: a request using it reached a failure state over the
256 KiB limit on a `Pass` with no `Catch`, where the user is told nothing at all.
