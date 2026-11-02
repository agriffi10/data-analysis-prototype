---
type: Decision
title: "The run's ONE sentence opens neutrally, because its residue is not all failure (SPEC-191)"
description: "A file-operations outcome sentence opens with `N need your attention` rather than a denial, since its residue includes `duplicate` and `noop`, and a mixed run names what succeeded first."
---

Partitioning a run's outcomes into "the operation's success outcome, or not" is the obvious split,
and it makes the sentence contradict itself on the two outcomes that matter most.

A **`duplicate`** reached the destination — the notification's own link points there — so an opening
of "Nothing was moved" is false, and it is followed two clauses later by "This data is now in both
places". A **`noop`** is a success that did nothing, which this plane's vocabulary says in as many
words; reported as a denial it reads as exactly the failure the wording rules exist to prevent.

So the opening is `N need your attention`, which is true of every member of the residue and is the
only thing they have in common. What succeeded is still named first on a mixed run — "2 of 5"
answers the question a user actually has, where a message listing only refusals reads as though
nothing worked.

## History

### 2026-08-17

- **Settled:** SPEC-191.
