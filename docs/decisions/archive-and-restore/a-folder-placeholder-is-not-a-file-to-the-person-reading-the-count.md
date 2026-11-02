---
type: Decision
title: "A folder placeholder is not a file to the person reading the count"
description: "Sentences a person reads count files, and `arcommon.counts` counts a placeholder only when it is what fell short; plans, manifests and gates still count objects, and the file count rides inside `$.transfer`."
---

**Found by the live check on 2026-09-21.** A member of a shared space made a folder with **New
folder**, uploaded one 38-byte file into it and archived the folder. The notification said
"Archived 2 files", the receipt said `Files archived: 2`, and the restore said "Restoring 2 files".
The second "file" was the zero-byte `live0921_archive/` key that New folder writes. This plane
carries such keys on purpose, because an archived empty folder has to come back
([the expansion entry](the-receipts-paths-name-the-roots-and-the-expansion-keeps-what-every.md)),
and every sentence was rendering `objectCount`.

**The fix changes the number a person reads, not what is copied.** `objectCount`, the plans, the
manifest's item count, the commit gate, `archive_is_intact` and the retrieval record all still count
objects, and the Maps still iterate every placeholder. A separate count is used for the wording, and
`arcommon.counts` holds the one rule for it: **a placeholder counts toward a number a person reads
only when it is the thing that fell short.** A success names files. A shortfall names "done of
total", where done is the files that landed and total is the files plus any placeholder that fell
short. The gap between the two is then the whole shortfall, so no sentence about a real shortfall
can read "only 1 of 1 file(s) could be copied". A selection with no files, only empty folders, reads "Archived 1 empty
folder". Andrew chose that wording and the exact treatment of the failure sentences on 2026-09-21;
the receipt still records `Files archived: 0` for it. Its failure sentences still count in
files ("only 0 of 1 file(s) could be copied"), which was left unworded. The two archive
shortfall bodies say "file(s)", as the restore's already did, because a total of 1 is ordinary.

**The rule's cost, accepted with it.** When only a placeholder falls short, the sentence counts it
as one of the files: "only 1 of 2 file(s)" over a one-file selection, and on a partial restore a
receipt whose `Files archived: 1` sits above "1 of 2 file(s) were written". The alternative was
"only 1 of 1", which reads as a run that did not fall short at all.

**Every copy-shortfall sentence needed the copy's per-item results to say which kind fell short, and
they said nothing.** The engine forbids echoing keys onto a failure record. So each transfer-manifest
line on both arms now carries a boolean `folder`, which is a bounded name and keeps that rule. The
one copy verb and the one collector echo it on both halves of the export. The collector adds a
`shown` block to its verdict, and the rollback, the receipt's restore line and the three
partial-restore bodies all read it, so they still share one source. Delete-source counts its total
from the keys it deletes. The rollback's residue stays a count of every object left behind, because
by the rule each one is a thing that fell short. One constant names the field for the builders, the
copy verb and the collector, because if the name drifted between the writer and a reader, every
failed placeholder would be counted as a file and nothing would fail.

**The file count rides inside `transfer`, not as a field of its own, and that is a deploy
constraint.** Deploy Infrastructure and Deploy Lambdas run in parallel on a merge, in no fixed
order. A notify payload reading a new `$.fileCount` would be an absent `Parameters` path whenever
the definition landed before the verb that writes it. That is an uncatchable `States.Runtime` on
`NotifyArchived`, which runs after the source has been deleted. The manifest builders already put
`$.transfer` on the state under the old code and the new alike, so the three notifies thread the
whole block. This is the precedent `$.cleanup` set. Each reader falls back to the object count when
the block, the field or the `shown` verdict is absent: a restore waits hours on the definition it
started with. A failure record with no flag, from a copy verb or a manifest older than it, returns
the object counts for the whole verdict rather than guessing its kind; only items an export never
covered are attributed, to files first and never below zero. An ASL walk reddens when any reader of
`$.transfer` is reachable before a builder, or after a state that reshapes the object — a `Pass`
naming its own keys, a Map or Catch with no `ResultPath`, or a Task that stops selecting its verb's
return.

**Deliberately left counting objects.** `restore_archive_incomplete`'s "holds {found} file(s) but
its record says {expected}" compares two object inventories. Manifests already written record only
`objectCount`, so no file figure exists for them, and the sentence fires only on an already-broken
archive and sends the user to an administrator. `too_many_objects` names a cap that the walk counts
in objects, not a count of the run. Over-coverage, an export that accounts for more items than the
manifest listed, is incomplete with nothing attributable, so its pair reads "N of N". The object
counts it replaced read "3 of 2" there.

**The other planes were checked, and none needs this.** File-send's expansion drops keys ending in
`/` (`fscommon/expand.py`), so its "(N files)" was already files. File-ops keeps placeholders, but
every number it renders counts selected items. Table-share renders no count, and its default listing
drops them anyway.

## History

### 2026-09-21

- **Settled:** entered the register.
