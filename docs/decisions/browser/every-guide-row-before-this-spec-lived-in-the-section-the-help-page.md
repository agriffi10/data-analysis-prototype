---
type: Decision
title: "Every guide row before this spec lived in the section the Help page opens on"
description: "The Data Explorer has its own Help section with a registry row per guide, guide recipes select the section first, and the guides say plainly that every filter and sort runs a query that scans data."
---

The walking test's guide recipe queried a guide card without selecting its owning section. That
worked for four rows by coincidence — all of them were in `files`, the default section — and would
have returned `null` in **both** flag states for a row anywhere else, which reads as "correctly
hidden" rather than as a recipe that cannot see its surface. The recipe now selects the section
first, and returns null only when the section itself is gone (the `files` shape, where a section row
and a guide row share one flag).

The Data Explorer gets **its own Help section** rather than guides folded into Query: it is a
primary nav destination with its own flag, and a user looking for it in Help should find it by name.
The section and each of its five guides get a registry row, on the `files` precedent — the section
row alone would suffice today and would go on passing if a later spec moved one guide into the Query
section, where it would then be visible with `dataExplorer` off.

The guides document only what is shipped and wired (SPEC-074 FR-005), which here means saying two
things plainly that the UI cannot: that **every filter and sort runs a real query against Athena and
scans data**, with the figures at the bottom as the cost signal; and that a saved exploration
**reopens in the Query workspace as SQL**, not back here as an exploration — SPEC-183 descoped the
loading half, so a guide promising otherwise would document a spec that has not been written.

> **Superseded by SPEC-247.** A file saved from the Data Explorer now reopens here through **Open
> saved view**, and the guide says so; a file saved from Query, or edited there since, still reopens
> only as SQL in Query. The entry is `docs/decisions/analytics/` → *A saved exploration carries its view on one comment line, and a shared space's is held*.

## History

### 2026-08-14

- **Settled:** entered the register.
