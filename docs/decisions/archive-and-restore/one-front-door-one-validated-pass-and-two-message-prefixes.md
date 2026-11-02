---
type: Decision
title: "One front door, one `Validated` Pass, and two message prefixes"
description: "The restore validator is a branch of validate-authorize: both modes return the same five top-level keys, check unknown fields per mode, and carry `mode` on the failure path to pick between two message prefixes."
---

The restore validator is a **branch of the existing verb**, not a second Lambda, and that is forced
rather than chosen: `ChooseMode` sits downstream of validate-authorize and reads `$.mode` off the
parsed request, while in the raw Pipe record the same field is inside an escaped JSON string ASL
cannot look into. A separate front door would need the branch to happen before anything had parsed
the body.

Both modes therefore return the **same five top-level keys**, because a shared `Validated` Pass
naming a path one mode lacks raises an uncatchable `States.Runtime`. `source` is the authorized
SPACE in both — the archive's source in one, the restore's destination in the other — and only its
`items` are archive-only. The unknown-field check is made **per mode**: a union of the two contracts
would accept a restore carrying a selection and an archive naming an archive id, and silently ignore
whichever the mode did not read.

The failure path carries `mode`, and `arcommon.messages` registers **two resolvers over one body
table**. The codes only one mode can reach are unambiguous; `forbidden`, `malformed_event` and
`invalid_request` are reachable by both and are exactly what a single "Couldn't archive that" prefix
gets wrong. `ValidateFailureSeed` supplies a literal `null` — its input is the raw error, so reading
`$.mode` there would raise on the failure path itself.

**`restore_archive_incomplete` does not reuse FR-005's proposed `archive_incomplete`.** SPEC-169 had
already registered that code for a copy that fell short, its body promises "nothing was deleted and
your files are exactly where they were" — meaningless about a restore — and the ASL seeds the
literal in `RollbackReturnedSeed`. One code cannot carry both sentences, and the shorter name
belongs to the arm that shipped first.

## History

### 2026-08-12

- **Settled:** entered the register.
