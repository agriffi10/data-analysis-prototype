---
type: Decision
title: "`saved_queries/` is gated on `query`, and the gate is not the refusal (SPEC-173)"
description: "`saved_queries/` is a `GATED_SURFACES.query` registry row: with the flag off it leaves the file browser's listing and the destination picker, which is presentation only, while the delete and rename refusal takes no flag and always holds."
---

**Decision (2026-08-11).** The folder is a Query feature wearing a file-browser row, so it is a
`GATED_SURFACES.query` **registry** row — the same shape as "Create table", the row SPEC-163 calls
the one everyone forgets — and not a per-component opt-in. With the flag off it leaves the file
browser's listing **and** the destination picker together, because a destination the user cannot
see is not a destination; that is the one place the gate touches an otherwise ordinary folder
operation, and it is presentation: it removes a way of *asking* and revokes no grant.

`DestinationPicker` reads the flag **itself** rather than taking it from its four callers, so every
picker in the app inherits the rule from one place. The cost is real and accepted: the picker now
requires an auth context, which one bespoke a11y tree had to be given.

**The delete/rename refusal is unconditional, and structurally so** — ~~`deleteFolder`/`moveFolder`
take **no flag**, so there is no state in which the gate can reach them. That is the argument, and
it is stronger than the test FR-008 AC3 asks for: a service-level test cannot render "with the flag
off" because the service never reads one. The refusal is tested directly and the structural claim
is recorded in the test's own comment.~~ **— superseded by SPEC-198:** `deleteFolder` and
`moveFolder` are deleted, and the argument holds of what refuses in their place. Neither
`undeletableRootFolderRefusal` nor `undeletableSelectionRefusal` in `protectedFolders.ts` takes a
flag, and neither does the plane's `source_refusal`, so there is still no state in which the gate
can reach the refusal. `fileBrowserPure.test.ts` tests the browser's refusal for `saved_queries/`
directly; the test comment that recorded the structural claim went with SPEC-198's rewrite of the
service tests. "You cannot see it" and "you cannot destroy it" are different guarantees, and only
one of them survives a stale cached flag document.

## History

### 2026-08-11

- **Settled:** SPEC-173.
