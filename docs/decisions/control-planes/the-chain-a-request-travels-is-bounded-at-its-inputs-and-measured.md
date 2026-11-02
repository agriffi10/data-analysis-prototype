---
type: Decision
title: "The chain a request travels is bounded at its inputs and measured against the limit that binds (SPEC-229)"
description: "**Every cap is COMPUTED against the budget that sized it** — memory, makespan, or a service quota — and it names that budget. A hard-coded number hides a wrong model, and so does the right number against the wrong quota: the fleet message cap was derived from SQS's message limit, which bounds what the QUEUE takes and not what an execution can carry. **A cap the request must clear before a verb runs is computed in PRODUCTION code**, because every per-plane cap runs inside `validate-authorize`, after the request that would overflow has already arrived. And **check the unit**: bytes on the wire, bytes in the value, and a count are three different questions that look alike as integers."
---

A request travels four representations, each capped by Step Functions at 256 KiB: the caller's body;
the Pipe's record, which carries that body as an **escaped** JSON string and is what
`StartExecution` receives; the validated state a verb returns; and, on a failure, the
`RecordFailure` state, which is the record again plus an error `Cause`. It was bounded in one place
and by the wrong budget — `MAX_MESSAGE_BYTES` was the **SQS** message limit less the identity
block, and SQS accepting a message says nothing about Step Functions starting an execution with it.

**Every caller-controlled field now declares a bound on the CONTRACT**, which is the only place the
population is derivable: a template cannot tell a caller's value from a stamped one, so resolving
it there needs data flow across ASL and eight verbs, where reading the contract needs neither. The
rule is unconditional — every declared string or list path either carries a bound or is a finding —
and that catches a field before any template names it. Sixty-eight paths, each with the budget that
sized it.

**Three units, and conflating them is the failure this shape invites.** A bound is serialized JSON
bytes, or the value's own UTF-8 bytes, or a count — and they look alike as integers. An earlier
draft spent `SHARE_MAX_RECIPIENTS = 50` as fifty *bytes*, so the worst case it built carried one
recipient and understated file-send by 7,497 bytes; it also bounded a roster in bytes, which at the
shortest legal username admits two thousand names against a cap of forty-four. The member cap is
**mirrored from `transfer_reader.MAX_MEMBERS_PER_MESSAGE`** rather than re-derived: a second
derivation of the same verb's capacity came out at 100 against its 44, and the looser one would have
let the API admit a request the operator path already refuses as unable to finish.

**`MAX_MESSAGE_BYTES` is re-derived from the state limit** — the `Cause` reservation, a Pipes-record
overhead reservation, the largest plane's `RecordFailure` literals, an escape factor of exactly 2
and stated headroom — in production code, with a guard measuring each reservation against artifacts
the module cannot read (`infra/` is not in the image). The SQS arm survives as the queue's own
ceiling and is asserted **unreachable**, so nobody reads its passing as evidence it fires.

**The `Cause` is reserved at twice its documented length, and that is what moved the caps.** 32,768
is a maximum length in **characters** on the execution-history event shapes, not a byte quota on a
state, and a Cause is a JSON document inside a JSON string on the state — escaped there like
everything else. Reserved honestly, a quote-heavy selection at the old 96 KiB caps reached a
`RecordFailure` of **263,533 bytes (archive) and 271,446 (file-send)** against 262,144, on a `Pass`
with no `Catch` — figures the chain guard computes rather than restates, because the first pair
written here was measured before the units were corrected and was wrong by up to 8 KB. `ARCHIVE_MAX_ITEM_BYTES` came down to **89 KiB** and `SEND_MAX_ITEM_BYTES` to **84 KiB**, each
pinned tight — one whole kibibyte more and the chain breaches — with the SPA's mirrors moved with
them. *(Superseded for archive by SPEC-250: **87 KiB**, because the archive's optional name rides
in the same message and its bound had nowhere to come from but the selection. The characterised
overshoot above describes the body without the name.)*

**A fourth live overshoot the spec never named: file-ops measured a quantity nothing produces.** Its
selection cap counted the selection with `ensure_ascii=False`, on the reasoning that the browser
sends literal UTF-8 and the Pipe keeps it literal. Both halves are true and the conclusion was not —
the API re-serialises the body with the default escaping one hop before the Pipe. Measured: 49
folders of accented keys passed the 64 KiB cap at 64,730 bytes, cost **189,974** on the wire, and
produced a failure state **27,151** bytes over the limit. Both sides now measure the escaped form; the
cap does not move and an ASCII selection is unaffected. **The wire stays pure ASCII deliberately** —
that is what keeps the worst-case escape into the Pipe record a provable 2.0 whatever AWS's own
serialiser does.

**Two things this entry does not claim.** `requestId` was never the live hole the spec described:
`fifo._checked` refuses a derived deduplication key over 128 printable-ASCII characters before the
send, on the nine routes that make the id one. And the Pipes-record overhead reservation is
**modelled, not measured** — no captured record exists in the tree — which its declaration says so
nobody reads its passing as evidence about the real record. Detail: `spec-delivery/SPEC-229`.

**A cap the request must clear before a verb runs is computed in PRODUCTION code**, because every per-plane cap runs inside `validate-authorize`, after the request that would overflow has already arrived.

## History

### 2026-09-09

- **Settled:** SPEC-229.
