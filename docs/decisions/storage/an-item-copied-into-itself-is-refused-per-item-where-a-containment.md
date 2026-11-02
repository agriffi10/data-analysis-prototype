---
type: Decision
title: "An item copied into itself is refused PER ITEM, where a containment breach fails the request (SPEC-187)"
description: "A refusal about the request, such as a key outside the root or two items colliding, fails it whole; one about a single item, such as a protected folder, a no-op, an into-itself copy or a reserved landing name, is that item's outcome, with source protection checked first."
---

The plane's front door has two kinds of refusal and the split is not stylistic.

**Whole-request, raised:** a key outside the actor's own root, a dot segment, a `targetName` that is
not one usable segment, and two selected items whose derived destinations collide. These are
statements about the REQUEST — there is no sensible partial execution of one that names a key outside
the actor's space, and where two items collide neither of them is the wrong one, so there is no item
to fail and no way to choose.

**Per item, returned as an outcome record:** a protected folder, a same-key no-op, and an item whose
destination is inside its own subtree. The browser has always carried on with the rest — a select-all
delete at a space root deletes what it may and reports the folders it may not — and a whole-request
refusal would turn that into deleting nothing.

The into-itself case is the one that could have gone either way. It is per item because it is a
statement about ONE item's own pairing rather than about the request's legitimacy, which makes it a
**user-visible divergence from today's browser**, where it refuses the whole gesture.

**A collision is between two DIFFERENT items, and an exact repeat is not one.** The identity is
`(kind, key)`, never the derived key alone: the same item named twice lands on itself, which is
idempotent, while two different items landing on one key lose a file. Collapsing on the derived key
alone refuses a request that does exactly what it says — and it is the same rule SPEC-165 recorded
for file-send, arrived at from the other direction.

**The source's protected-location rules run FIRST, before either pairing rule.** An item the user
may not touch should be told so rather than told that nothing happened: `move alice/archive/ →
alice/` derives its own key, so a pairing-first order answers "no-op" to a request the plane
actually refuses, and two protected folders answer the same request differently depending on which
list they are on.

**Where each item LANDS is judged too, not only the prefix it is put into** (2026-09-16). The prefix
is the folder a request names and every item lands one name below it, so a prefix-only rule accepted
moving `sales/stage/_data-quality-reports/` into `sales/`, or renaming a folder `shared_tables` at
the root — in a shared space, one member replacing another's data-quality reports, which that plane
reads back between its verbs. validate-authorize runs the destination rules over each item's derived
key, per item, as `destination_name_reserved`, labelled by the name the item would land under so a
rename names what the user typed. It sits AFTER the same-key no-op, which writes
nothing, and before into-itself, in every bucket pairing. `_data-quality-reports/` and everything in
it is refused as a delete or move source, root-anchored like the plane's only write. **No
execution-role Deny backs the reports folder on either side, by choice**: the role has no principal
tag to anchor a Resource at a root, so `*/_data-quality-reports/*` reaches a user's own nested
folder too, and every file-ops rule would have to refuse it at any depth or the Deny fails a run
part way through. Results-conversion's role takes that trade for one save location; here it would
refuse copying, moving and deleting a folder the browser shows as the user's own.

**Where the execution role denies a write, the plane refuses it at any depth, in both buckets**
(2026-09-16). The role's write Deny names `*/user_settings/*` and the two `system_settings` pairs
with no principal tag to anchor them, so it reaches those folders at any depth; the destination rules
followed the picker and the bucket policies instead, and a copy into a folder a user had made —
`alice/foo/user_settings/`, a nested `system_settings/athenaresults/`, in a personal space a nested
`system_settings/archive/` — passed validate-authorize and failed at the write. The Denies stay:
nothing can anchor them without a principal tag, and dropping them removes the only IAM fence over
the real settings, results and receipt folders. `focommon.protected.role_denied_folder` is the one
reading of both role Denies — every key segment but the first and the last, which is exactly what
`*/name/*` means — and three seats use it: the destination prefix (whole request,
`destination_folder_reserved`), each item's derived key (`destination_name_kept_for_app`), and
build-transfer-manifest over every planned destination key (`write_refused`, the item refused whole
before anything copies). **The last trades away a partial copy, by the owner's choice**: a copied
folder holding a nested `user_settings/` used to land everything else and end `copy_failed`; a move
of the same folder was already refused whole on its source side. The same predicate replaced
`focommon.delete`'s own scan, which counted a key's first segment and so refused every move and
delete for a user literally named `user_settings`, and a `system_settings` user's own root-level
`athenaresults/` and `archive/` folders — names the sign-up pattern admits and deletes the role
permits; the owner chose the fix. An item that itself sits inside one of those
folders is refused as a move or delete source at the front door, as `delete_refused`, ahead of the
derived-key rule, which would otherwise tell it to choose a different name. Three more visible
shifts: a same-key no-op inside such a folder is now a refusal, as at the root; a folder item that is
occupied and holds an object bound for one of these folders is still told first that it is occupied,
and its overwrite resubmission, which used to land part of the folder, is now refused whole; and a
lone file still goes through the API, which permits a nested `user_settings/` write — and, in a
personal space, the nested pairs — that the plane refuses: an asymmetry, not a regression, since that
multi-item write failed before. **These refusals' sentences state only what holds for every request
that reaches them and name no step**: three review frames each found one that did not — "managed for
you" of a folder the user made, "choose a different destination" where none works, "give it a
different name" to a folder the plane will not rename — and the class, not the instance, was fixed.
`test_file_ops_rules_mirror_execution_role.py` holds the predicate, the prefix wiring and the delete
check against the role's template.

**The space root is refused as an item, and it is the third way to select a protected folder.** Every
protected rule matches the named folder or something below it; none looks UP. So one item of
`alice/` passes all of them while naming a subtree containing `athenaresults/`, `user_settings/`,
`archive/` and every marker — a request this plane's own IAM refuses part-way through, which is the
mismatch those rules exist to prevent. The browser cannot express it, so refusing costs nothing.

## History

### 2026-09-16

- **Changed:** Destination rules now judge where each item lands, not only the prefix it is put into, refusing per item as `destination_name_reserved`, and `_data-quality-reports/` is refused as a delete or move source.
- **Changed:** Wherever the execution role denies a write, the plane now refuses it at any depth in both buckets through `role_denied_folder`, trading away a partial copy for a whole-item refusal before anything copies.

### 2026-08-17

- **Settled:** SPEC-187.
