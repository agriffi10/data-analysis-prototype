---
type: Decision
title: "The outcome wording reuses the failure bodies and is deliberately NOT a resolver (SPEC-191)"
description: "File-operations outcomes reuse the failure table for the six reasons it already words, and the outcome table is never registered as a `Resolver`, since that would make a per-item outcome a valid whole-request reason."
---

Six per-item outcomes carry a reason the failure table already words — `source_missing`,
`source_empty`, `copy_failed`, `source_changed`, `source_delete_failed`, `delete_refused` — so the
item clause resolves through that same table and only the outcomes with no body of their own are
written out. A second table would be one code with two sentences, inside one module.

**The outcome table is not registered as a `Resolver`.** `Resolver.__init__` ends by marking every
key it is given a globally valid reason code, so registering these would let
`TerminalError("duplicate")` pass raise-time validation — undercutting `outcomes.py`'s rule that no
member of the per-item vocabulary may ever be a whole-request failure reason. That a success
sentence cannot open with "Couldn't move that: " is the lesser argument.

## History

### 2026-08-17

- **Settled:** SPEC-191.
