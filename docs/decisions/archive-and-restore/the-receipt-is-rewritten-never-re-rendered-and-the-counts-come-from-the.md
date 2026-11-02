---
type: Decision
title: "The receipt is rewritten, never re-rendered, and the counts come from the run"
description: "A restore rewrites two receipt lines by label and keeps the rest verbatim; only a proven 404 composes a fresh receipt, the ASL seeds the stage, the run supplies the counts, and only the pre-retrieval write can fail the run."
---

`arcommon.receipt` is still the single writer, but SPEC-171 rewrites **two lines by label** and
keeps every other line verbatim. The archive lines record the archive RUN, and its start time is the
one field no restore can recompute — so re-rendering the document from the restore's own state would
silently blank `Requested` on the only durable record the user has of what was archived and when. An
absent receipt (a **proven** 404) is composed fresh, losing only that one field; an **ambiguous**
read — a 403, or a fault carrying no status — raises rather than taking that branch, which is the
destination guard's fail-closed 403-is-occupied discipline pointed at a write.

**The marker runs before the retrieval, not after.** FR-006 AC4 asks for it "when retrieval is
initiated"; immediately before is the same guarantee and strictly safer, because there a
receipt-write failure costs nothing where a moment later it would fail a run the user had already
been billed for. It is also why that stage's failure contract differs from the other two: before the
bill a failed write fails the run, and after the data has landed it must not — the ASL `Catch` on
`UpdateReceipt` reaches the SUCCESS terminal, because the ordering is most durable to least (data
restored → receipt → notification).

One function serves all three stages and **the ASL seeds which one**, rather than the verb inferring
it from what else is on the state: "nothing has run yet" and "the run reported nothing" are
different facts that look identical from inside a handler. The seed carries the STAGE and the run
carries the COUNTS — an earlier version let the seed supply `restored`/`expected` too, so the
sentence written onto the receipt and the tokens in the notification had **two sources and could
disagree**, with nothing to say which was right.

## History

### 2026-08-12

- **Settled:** entered the register.
