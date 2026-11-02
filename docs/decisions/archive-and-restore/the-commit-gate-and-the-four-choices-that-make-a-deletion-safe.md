---
type: Decision
title: "The commit gate, and the four choices that make a deletion safe (SPEC-169)"
description: "Deleting an archive's source is guarded in layers: a commit gate, a rollback confined to the run's own prefix, a narrow delete grant, a single-use request id and refusal of anything undeletable."
---

This heading grouped the decisions below when one file held the area. Each now has a file of its own:

- [The source is deleted only when EVERY object is confirmed copied](the-source-is-deleted-only-when-every-object-is-confirmed-copied.md)
- [The rollback deletes what is THERE, not what it was told about](the-rollback-deletes-what-is-there-not-what-it-was-told-about.md)
- [The delete grant is the one this role could not inherit](the-delete-grant-is-the-one-this-role-could-not-inherit.md)
- [The request id is browser-supplied, so a reused one is refused twice over](the-request-id-is-browser-supplied-so-a-reused-one-is-refused-twice-over.md)
- [An object this plane could copy but could not delete is refused, not archived](an-object-this-plane-could-copy-but-could-not-delete-is-refused-not.md)
- [The artifacts are ordered most durable to least, and the receipt's failure is terminal](the-artifacts-are-ordered-most-durable-to-least-and-the-receipts.md)
- [Three caps, and the one the spec does not name](three-caps-and-the-one-the-spec-does-not-name.md)
- [The ceiling ships with its rule, again](the-ceiling-ships-with-its-rule-again.md)
- [The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops](the-receipts-paths-name-the-roots-and-the-expansion-keeps-what-every.md)

## History

### 2026-08-12

- **Settled:** SPEC-169.
