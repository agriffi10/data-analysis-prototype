---
type: Decision
title: "The key namespace moves with the module, and a prefix is not cosmetic"
description: "A query-key prefix moves with its module, so `catalogKeys` is rooted at `['catalog']`, and invalidating one feature's keys cannot reach another feature's caches."
---

`catalogKeys` is rooted at `['catalog']`, not `['query']`. Keeping the old prefix would have been a
smaller diff and is the wrong call: a key namespace naming a feature the module no longer belongs to
is the same hidden coupling the extraction removes, and it would make a future
`invalidateQueries({queryKey: queryKeys.all})` in the Query workspace silently reach into the Data
Explorer's caches. Cache keys are in-memory and per session, so the change needs no migration and the
spec asserts none.

## History

### 2026-08-13

- **Settled:** entered the register.
