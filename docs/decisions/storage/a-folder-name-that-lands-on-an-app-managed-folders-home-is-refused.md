---
type: Decision
title: "A folder name that lands on an app-managed folder's home is refused where it is typed"
description: "A typed folder name landing on the home of a `PICKER_LOCKED_FOLDERS` member is refused at every prompt that knows the landing, and Rename, same-folder copy and a conflict's rename also refuse plane-denied names; this is a courtesy for folders only, since uploads bypass it."
---

Every prompt where a user types a folder's name, and the browser knows where the folder will land,
refuses a name that would put it ON the home of one of `PICKER_LOCKED_FOLDERS`: Rename, the
same-folder copy name, a conflict's *Use a different name*, New folder, and the Rename on New
folder's collision prompt. `validateFolderName(name, parentPrefix)` compares `{parent}{name}/`
against `appManagedPrefixes`, so the rule follows each folder's real home — `shared_tables/` and the
hidden folders at the top of a space, and the two moved folders inside a folder named
`system_settings`, where they were already refused. Below the top of a space this check treats the
other names as ordinary, and `system_settings` alone is refused at every depth, as it already was.
The file-ops plane is stricter about one of them: its execution role cannot write beneath
`user_settings/` at any depth. So the three prompts whose folder that plane writes — Rename, the
same-folder copy and a conflict's rename — call `validateFolderNameForPlane`, which also refuses a
folder landing on `PLANE_WRITE_DENIED_FOLDERS` below the top, as *"user_settings" is a name the app
keeps for its own folders* (Andrew's wording, 2026-09-16). It judges only the landing: a name typed
inside a nested `user_settings` meets the plane's refusal of the whole request's destination, which
no name fixes. `protectedFoldersMirror.test.ts` holds the list equal to the plane's. New folder
keeps `validateFolderName`, because its object route writes a nested `user_settings` without
complaint. The space root is read off the parent with `spaceRootOf`, the first-segment reading
`spaceFor` already takes, so a caller cannot pass the parent and forget the root. (2026-09-16)

**Why.** A folder there is not a user's folder that happens to share a name; it has the app's key. A
rename or copy would put its contents among what the app keeps there, and the file-operations plane
refuses that per item as `destination_name_reserved` — correctly, but in the run's notification,
after the dialog has closed. A folder created under a hidden name disappears from the listing the
moment it is made.

**New folder refuses more than the object route does, and that is a decision, not drift.** The route
refuses only the reports folder among these names. Refusing the rest in the browser was chosen over
keeping the browser a strict subset of the server, because a created folder under a hidden name
vanishes, and a hand-made `shared_tables/` becomes a folder the picker then refuses to paste into.
Do **NOT** narrow New folder back to the server's set on a "the browser only mirrors refusals"
reading.

**Folders only.** Rename, the same-folder copy and a conflict's rename pass the parent for a folder
and never for a file. A file named `shared_tables` is not that folder, and neither the plane nor the
object routes refuse it, so refusing it here would be a restriction nothing else has. The older
name-only refusal of `system_settings` still reaches a *file* at those three prompts, which the plane
would accept; it predates this entry and was left alone.

**A courtesy, not a boundary**, like the `system_settings/` refusal before it. An upload creates
folders without the validator. This is the root-aware validator SPEC-220 left for later; its reasons
for leaving the two moved names unreserved at the root still hold.

## History

### 2026-09-16

- **Settled:** entered the register.
