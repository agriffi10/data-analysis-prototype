---
type: Decision
title: "The archive vault, and the four choices that shape the whole arc (SPEC-168)"
description: "Archived data sits in a separate `GLACIER` vault the browser cannot reach, under keys that encode their origin, and one machine serves both archive and restore."
---

This heading grouped the decisions below when one file held the area. Each now has a file of its own:

- [`GLACIER`, and why the other two were rejected](glacier-and-why-the-other-two-were-rejected.md)
- [Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose](retention-is-a-ceiling-not-a-worm-floor-and-the-lifecycle-rule-is.md)
- [The bucket the browser has no relationship with](the-bucket-the-browser-has-no-relationship-with.md)
- [The key layout: the archived key carries its own origin, partitioned by space kind](the-key-layout-the-archived-key-carries-its-own-origin-partitioned-by.md)
- [One plane, one `mode` branch, and no grant this spec did not need](one-plane-one-mode-branch-and-no-grant-this-spec-did-not-need.md)
- [Two things the fleet's own guards caught while this was being written](two-things-the-fleets-own-guards-caught-while-this-was-being-written.md)

## History

### 2026-08-10

- **Settled:** SPEC-168.
