---
type: Decision
title: "The commit gate is per ITEM, so the graph proves less than SPEC-169's did (SPEC-189)"
description: "The per-item commit gate cannot be proved from the graph: the walk asserts only that an empty `deletable` set cannot reach `DeleteSource`, a collector test and `delete-source`'s subset check hold the rest, and both gates default to not deleting."
---

SPEC-169's gate is one boolean over the whole run and its guarantee is **graph-level**: the rollback
arm cannot *reach* `DeleteSource`. A per-item plane produces runs that are simultaneously committing
and non-committing, and **Step Functions has no per-item `Choice` over a list** — so that guarantee
is not available here. Rather than inherit a sentence that no longer holds, this plane asserts the
weaker property honestly and buys the rest at two other layers:

- **the walk asserts exactly one thing** — an empty `deletable` set cannot reach `DeleteSource` — and
  says in its own docstring that it does **not** assert the per-item property. A walk claiming more
  than it proves is worse than one claiming less;
- **the per-item half is a collector unit test with a named mutation** (an item with one failed
  object must not appear in `deletable`), plus **`delete-source`'s subset assertion at the boto
  boundary** — checked against the keys actually handed to `DeleteObjects`, never over the filter's
  own output, which would re-check the filter with the filter.

**Both gates enumerate their positive cases and default to not deleting.** `NeedsSourceDeletion`
names `move` and `delete` explicitly; a state whose `operation` was lost or mistyped reaches
`FinaliseOutcomes`. The first draft had the deleting arm as the `Default` — fail-open, and the
opposite of every neighbouring gate on this fleet.

**The skip branch is recognised positively.** A `delete` reaches the collector with the Map skipped
and every still-`cleared` item deletable. Implemented as the natural negative — *no `mapRun`,
therefore the skip branch* — a `move` arriving without an export would mark every cleared item
deletable and the next state would delete a source nothing had copied.

## History

### 2026-08-17

- **Settled:** SPEC-189.
