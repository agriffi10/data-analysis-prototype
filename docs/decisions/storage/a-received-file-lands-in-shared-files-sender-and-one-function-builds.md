---
type: Decision
title: "A received file lands in `shared_files/{sender}/`, and one function builds every key (SPEC-165)"
description: "**A received file lands in `shared_files/{sender}/`, built by ONE function** — an AST sweep forbids a second. Keying by item **name** forces the two refusals an overlapping selection needs. **A duplicate is `(kind, key)`, never the key alone.** One key can arrive as both a file and a folder; collapsing on the key ships a zero-byte placeholder and reports success."
---

**Decision.** Everything a sender sends lands at
`{targetRoot}shared_files/{sender}/{itemName}[/{relKey}]`, computed by a single
`fscommon.paths.destination_key`, with `shared_files` a named constant and a test sweep forbidding
any verb from composing its own.

**Why namespaced by sender.** This is what a recipient sees forever, and it is the decision with
the longest half-life in the arc — a layout is not something a later spec can quietly change, since
files are already sitting in it. Mirroring `shared_tables/{table}/` buys three things at once: two
senders sending `reports/` never collide, provenance is visible in the file browser with no
metadata lookup and no second request, and the recipient's own top level stays theirs rather than
accumulating a folder per sender's whim.

**Why the destination is keyed by ITEM NAME, and what that forces.** The alternative — preserving
the sender's path — leaks their folder structure into someone else's space and makes the
destination depend on where a file happened to live, so `alice/deep/nested/q1.csv` and
`alice/q1.csv` would arrive differently for no reason the recipient can see. Keying by name means
`a/reports/` and `b/reports/` would interleave into one folder, so that selection is a
**whole-request refusal naming the collision** — as is a selection where one item contains another
(copying the object twice and silently dropping one are both worse than a clear refusal). A
**repeated** item collapses instead: there is one right answer and no ambiguity about intent.

**A repeat is `(kind, key)`, and the key alone is not enough.** validate-authorize normalises a
`folder` key to a trailing slash and leaves a `file` key exactly as it arrived, so
`{"file","alice/reports/"}` and `{"folder","alice/reports"}` reach the expansion as one key with
two kinds. Collapsing on the key kept whichever came first: the file reading sent one zero-byte
placeholder and **none of the folder's contents**, reporting success, with the outcome depending on
the order of a JSON list. That is precisely the silent drop this rule exists to prevent, arriving
through the one part of it that was supposed to be safe.

**Why one builder.** The destination tests can only ever prove the ONE builder is right; a verb
concatenating its own would pass every one of them while writing somewhere else, and the symptom
would be files in the wrong inbox rather than an error. The sweep reads the AST for a
`shared_files` literal or an f-string composing the constant, exempting docstrings and the
declaration **by node identity** — an earlier version skipped the `Expr` and not its `Constant`
child, and flagged two module docstrings. Verified against four deliberate violations, including
one placed after a docstring.

## History

### 2026-08-10

- **Settled:** SPEC-165.
