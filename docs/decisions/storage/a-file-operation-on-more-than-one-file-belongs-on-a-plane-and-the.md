---
type: Decision
title: "A file operation on more than one file belongs on a plane, and the boundary is the SELECTION (SPEC-187)"
description: "A file operation stays in the browser only when a non-empty selection is exactly one item and that item is a file; anything else, including one folder or a folder rename, goes to the plane, whichever the operation, and the rule has one home."
---

An operation stays in the browser **if and only if the selection is exactly one item and that item is
a file**. It is a property of the selection, never of the operation: the same selection routes the
same way for copy, move and delete.

**The first draft of this rule was measured against the wrong quantity.** It said an operation goes
async only when it must LIST to know what it touches — coherent, and wrong: a file-only copy or move
of K files is a sequential loop of `HeadObject` + `CopyObject` + `DeleteObject`, up to 3K round trips
from the user's laptop, which is precisely the cost the plane exists to remove.

A single folder is enqueued, **including a folder rename** — forced rather than chosen, since a
rename is one `CopyObject` per contained object and cannot be bounded without listing. It is the case
a reader assumes is synchronous, so the rule's test names it.

**The empty selection is a precondition, not an answer.** Without it, "not exactly one item" routes a
zero-item selection to the plane, which refuses an empty source as a request-shape error minutes
later, by notification.

The rule has **one home**, and the sweep that enforces it counts IMPORTERS rather than parsing for
the rule: a boolean over `kind` and `length` has no recognisable syntactic signature, so an AST sweep
would fire on every legitimate branch in the file browser. That is the opposite call from SPEC-165's
key-builder sweep, where the signature *is* recognisable.

## History

### 2026-08-17

- **Settled:** SPEC-187.
