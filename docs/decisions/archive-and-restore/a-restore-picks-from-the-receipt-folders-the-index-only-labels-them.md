---
type: Decision
title: "A restore picks from the receipt folders; the index only labels them (SPEC-250)"
description: "The restore dialog lists the space's receipt folders, and the bounded, fault-swallowing index only labels them; the typed id stays one link under the list, and only a `restored` row is disabled."
---

Outside reviewers asked what an archive is called and how to find it again. An archive may now
carry a **name**, and the restore dialog **lists the space's archives** to pick from rather than
asking for a pasted id.

**The list is built from the receipt folders, and the per-space index only labels it.** Every
completed archive leaves `{root}system_settings/archive/{id}/`, which users can read and cannot
write, so listing that folder cannot miss an archive the plane finished. The index
(`index.json` beside the folders) carries the name, the date, who made it, the first items, the
counts and what its last restore did — and it is written after the receipt with every fault
swallowed, so it can lack an entry. **That costs a row its label and never its route to a
restore**: an unlabelled row restores exactly as a labelled one. An index that was the authority
would have had to fail the run when it could not be written, as the receipt does, and a CAS that
lost six races would have failed an archive that had already moved.

**The typed id stays, one link under the list, and Andrew chose that.** The one archive the list
cannot show is one whose receipt failed to write, and that failure's notification tells the user
to keep the id because restoring needs it. Removing the field would have left that user no route
but an administrator.

**Only a `restored` row is disabled.** A restore recorded as finished put every file back, so a
second would be refused (every destination occupied) or find a swept vault — and the sweep may
have partly failed, so "the vault is empty" is not the reason. A `requested` row stays selectable:
it is the ordinary in-flight state, which lasts hours, and a second request is refused safely by
the destination guard; and it is what a restore that stopped before its last write leaves behind,
where a disabled row would be a dead end. The row's status sentences are about a run, never the
archive's condition — the restore-message rule, applied to the list.

**Three things the index had to be, each found by a review rather than by design.** It is
**bounded in time as well as swallowed**: a stalled read raises nothing, and at the default
client's minute-long read timeout it held write-receipt past its Lambda timeout after the archive
had completed, failing the run the user is told about. It is **capped and written unescaped as a
pair**: with `ensure_ascii`, a full index of worst-case entries failed both the read route's stored
cap and Lambda's response ceiling, so the browser could not have read it at all. And it **never
creates an entry from the restore side**, so a row always knows what archive it labels.

**The name rule is written twice and held by a shared corpus.** `arcommon.names` and the browser's
`archiveName.ts` refuse control and bidirectional characters and a lone surrogate on the raw
value, then collapse U+0020 only — never "whitespace", on which Python and JavaScript disagree —
and cap at 100 code points. A lone surrogate was the find: it passed every other check, and the
receipt write could not encode it after the source had already been deleted. The wire field is
`archiveName`, because the bounds guard maps a leaf called `name` to a catalog identifier, and its
1,202-byte bound came out of the selection: the selection cap was pinned tight to the message
chain, so it dropped from 89 to 87 KiB.

**Not done:** a name made only of invisible characters (U+200B, a Hangul filler) is accepted and
shows as a blank-looking label; the row still shows its date, contents and size, and refusing it
means the rule taking on a taxonomy of Unicode format characters.

## History

### 2026-09-28

- **Settled:** SPEC-250.
