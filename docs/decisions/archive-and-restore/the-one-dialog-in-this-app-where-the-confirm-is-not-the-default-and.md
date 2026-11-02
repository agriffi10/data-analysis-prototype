---
type: Decision
title: "The one dialog in this app where the confirm is not the default, and Enter does nothing"
description: "`ArchiveDialog` is built on `ConfirmDialog`, never `FormDialog`, so focus lands on Cancel and Enter cancels; it must not say \"This can't be undone\" and states how long a restore takes instead."
---

Every other destructive confirm in this portal focuses Cancel because a stray Enter should not
delete a file. Archiving raises that from a courtesy to a structural requirement: it is the **only**
action here that removes the user's data and cannot be undone in the same sitting — getting it back
takes three to five billed hours.

So `ArchiveDialog` is built on `ConfirmDialog` **because of what `FormDialog` has**. `FormDialog`'s
`submitOnEnterRef` is a real affordance, and a dialog that merely declined to pass one would be one
refactor away from acquiring it. `ConfirmDialog` is not a form at all: focus lands on Cancel and
Enter cancels, by construction rather than by discipline. `RestoreArchiveDialog` makes the opposite
call for the opposite reason — one field, and Enter submits from it.

**The dialog does NOT say "This can't be undone."** `ConfirmDialog` will render that line on
request, the delete confirm uses it, and it would be the single false sentence in this dialog: a
restore is exactly that undo. What it says instead is how long one takes, which is the fact the user
actually needs and the one no button label can carry.

## History

### 2026-08-12

- **Settled:** entered the register.
