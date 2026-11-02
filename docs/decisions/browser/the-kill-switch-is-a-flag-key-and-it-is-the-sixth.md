---
type: Decision
title: "The kill switch is a flag key, and it is the sixth (SPEC-190)"
description: "`asyncFileOperations` is a default-on flag over copy, move and delete routing: off, a single file stays synchronous and a folder or multi-item selection is refused; the conflict view stays under `files`."
---

Five flags are areas; `asyncFileOperations` is a switch over the file browser's copy/move/delete
routing. **— Since SPEC-246 it is the first of two: `archive` is the second, over the archive and
restore entry points ([*Archive and restore get their own kill switch*](archive-and-restore-get-their-own-kill-switch.md)).** It earns a key rather than a build-time constant because its only other kill switch is
`files: false`, which removes the entire file browser — and because publishing a flag needs no app
build, which is what makes the largest user-visible change in the product survivable. Default **on**,
keeping the all-on fallback rule intact: an unreadable document must never change behaviour. ~~Off,
every gesture keeps the browser's synchronous path exactly as it was.~~ **— superseded by SPEC-198:**
off, a single file keeps the synchronous path, and a folder or any multi-item selection is refused
at the control — a folder because the browser's folder-recursive functions are deleted rather than
ported, a multi-item selection because the gate refuses every shape the routing rule sends to the
plane. `docs/decisions/storage/`, *The folder-recursive functions are deleted, not ported*.

Its two registry rows are the in-flight surface and the conflicts guide. **The conflict VIEW is
registered under `files` instead**, deliberately: throwing the switch must not strand a conflict
raised before it was thrown, and resolving one finishes work the plane already started rather than
beginning a new gesture — and it keeps the `Review conflicts` control already shipping on
notification rows from becoming a link to nothing. ~~A row's `name` is its accessible name and
`RECIPES` keys are unique, so one control cannot hold a row under two flags; the choice had to be
made rather than hedged.~~ **— superseded by SPEC-246:** the `Explore data` rows already held one
surface under two flags, by giving the second row a description rather than the accessible name,
and the archive rows now do the same. Choosing `files` for the conflict view stands on its own
reasoning above, not on a registry limit.

## History

### 2026-08-23

- **Settled:** SPEC-190.
