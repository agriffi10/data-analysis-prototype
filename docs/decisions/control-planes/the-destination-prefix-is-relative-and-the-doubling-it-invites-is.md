---
type: Decision
title: "The destination prefix is relative, and the doubling it invites is refused by nothing (SPEC-223)"
description: "**A conversion's destination prefix is RELATIVE to the space root; the browser's picker is absolute.** Passing one through writes `alice/alice/…` and **nothing refuses it** — containment only proves the key starts with the root, which a doubled root does. Derive the root from the string being sliced: a lookup needs a fallback, and the only one available is the bug."
---

`ConversionDestination.prefix` is **relative to the space root** — `rccommon.paths.destination_key`
builds `{root}{prefix}{filename}` — while the browser's `DestinationPicker` deals in full in-space
prefixes rooted at `alice/`. Handing one straight to the plane writes `alice/alice/reports/q1.parquet`,
and **no gate catches it**: `cpcommon.paths.assert_inside_root` proves the key sits inside the root,
which a doubled root does, and the write then succeeds into a folder the user never chose.

The browser slices the root off, and **derives** it from the very string being sliced rather than
looking it up in its list of spaces. That is the part worth keeping: the first revision did look it
up, with `?? ''` when the destination was not found, and `startsWith('')` is universally true — so
the fallback re-created the exact bug the slice existed to prevent, through the one branch no test
covered. Derived, `spaceFor(...).name` *is* the prefix's first segment, so the slice is total and
there is no branch to get wrong. A guard around it was tried and deleted: a review planted its
removal and the whole suite stayed green, because no reachable input can fail it.

**A fixture set that is all personal cannot see any of this.** The read space and the write space
coincide for a personal destination, and so do the absolute and relative prefixes' first segments —
the conversion tests use a shared-space destination for that reason, and the live check in
`e2e.md` §4.3 is the one row worth running even if no other is.

## History

### 2026-09-07

- **Settled:** SPEC-223.
