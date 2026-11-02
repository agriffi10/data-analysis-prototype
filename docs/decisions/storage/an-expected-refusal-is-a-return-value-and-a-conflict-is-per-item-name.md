---
type: Decision
title: "An expected refusal is a return value, and a conflict is per item NAME (SPEC-166)"
description: "`check-target-absent` returns its expected refusals as records and leaves its `Catch` for unpredicted faults; a conflict is decided by item name from one delimited listing of the sender's inbox and refuses that recipient, merging and overwriting nothing."
---

**Decision.** `check-target-absent` returns `{status, recipient, reason, detail}` for the two
refusals it expects — a recipient validate-authorize could not resolve, and a name conflict — and
its Map item's `Catch` is left for faults nobody predicted. The conflict is decided by **item
name**: one delimited listing of `{targetRoot}shared_files/{sender}/`, compared against the names
the selection would create. A taken name refuses **that recipient**; nothing is merged and nothing
is overwritten.

**Why not raise, as table-share's guard does.** A conflict has to name the colliding item, and a
`TerminalError` cannot carry one past the Map item's `Catch`: its `tokens` are deliberately kept
out of the exception message (they would corrupt `failure_reason`'s colon split) and its `detail`
is operator text that may quote raw service output, which SPEC-106 forbids rendering. Parsing a
filename back out of a Step Functions `Cause` would be fragile *and* a rule break. The collector
therefore reads two record shapes and decodes the raw `{Error, Cause}` only for the unpredicted one.

**Why a delimited listing rather than a probe per item.** Two round trips per item is 20,000 serial
calls for a full selection against a full recipient list — and a `MaxKeys=1` probe at
`Prefix={inbox}{item}` **cannot answer the question at all**: S3 orders keys lexicographically and
`/` (0x2F) is not the lowest byte a key may carry, so `notes.txt-old` sorts before
`notes.txt/part-0` and the one key returned reads as "clear" over an occupied destination. The
listing is bounded by what that sender previously sent to that recipient, not by the size of the
send.

**A name is a name whatever it holds.** A previous send of the file `notes.txt` conflicts with a
new send of the folder `notes.txt/`, because `destination_key` gives both the same base.

**Neither the guard nor the collector notifies.** Every per-recipient outcome is told to the sender
once, from the terminal summary, by SPEC-167's producer. Table-share notifies from its own guard
because it has no such producer; copying that here would send two messages about one conflict.

**Two fail-open holes, both found in review and neither visible to the suites as written.** The
guard cleared every recipient when the selection arrived empty (no names ⇒ no collisions ⇒ `ok`,
over an inbox that already held the send) — three lines from a missing *actor* that already failed
closed. And the collector reported universal success when the `transfer` block was absent, without
making a single S3 call; it is closed by an invariant already on the event, that the manifest
builder cannot report zero items while a recipient cleared the guard.

**Not closed: the guard is TOCTOU.** Two sends of the same item name from the same sender to the
same recipient, submitted close together, can both clear it. Inherent to check-then-copy with no
lock, and table-share has the same shape. **— Superseded in part 2026-09-15: "close together"
means before the first run's copy of that name lands, which on a large send is up to the
three-hour ceiling, because the group id orders only the starts; and the second run then
overwrites what the first delivered, a file the recipient edited in between included. The repair
is decided: [the group id entry](../control-planes/a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on.md).**

## History

### 2026-09-15

- **Changed:** The guard's accepted TOCTOU gap was widened: overlap lasts until the first run's copy lands, up to the three-hour ceiling, and the second run overwrites what was delivered; the repair is decided in the group id entry.

### 2026-08-10

- **Settled:** SPEC-166.
