---
type: Decision
title: "The file-send exclusion rule is anchored at the space root, not the listing prefix (SPEC-165)"
description: "**The analytics exclusion rules anchor at the listing prefix**, which for file-send would be whichever item the user picked, so file-send carries its own predicate anchored at the space root — reusing them silently drops files."
---

**Decision.** `fscommon.expand` carries its own ignore predicate — folder placeholders, the prefix
marker, and `{root}athenaresults/` — and `cpcommon.s3_listing.list_data_objects` grew an optional
`ignore` parameter rather than being forked or reused as-is.

**Why not reuse `is_ignored`.** Every rule in it is anchored at the **listing prefix**. That is
right for the three analytics planes, which list a table's or a check's own folder, and wrong here:
the listing prefix is whichever item the user picked. Sending `alice/reports/` would have dropped a
user-made `alice/reports/athenaresults/` — which SPEC-164 explicitly records as an ordinary
sendable folder — and any `_drafts/`, with **no refusal and no message**. A silent drop from a send
that reports success is worse than either copying it or refusing it. The hidden-segment rule also
exists because *Athena* ignores such paths, which says nothing about a byte-for-byte file copy.

**Why a parameter rather than a second paginator.** The pagination genuinely is shared, and it is
the part a fixture proves least — the 1,000-key boundary is where a truncated listing returns a
plausible smaller number rather than an error. One paginator, and a plane whose exclusions are
anchored elsewhere says so at the call site. The default is byte-identical for the three existing
callers, held by a test in both directions.

**Two consequences, both deliberate.** A genuinely **empty file is sent** — `is_ignored` drops
every zero-byte object, and a folder placeholder is excluded by its trailing slash instead, the
shape `createFolder` actually writes — so an **empty subfolder does not survive a send**. And the
`athenaresults/` exclusion has **no live path** through the shipped front door, because
validate-authorize refuses a root selection outright; it is written anyway, for the reason SPEC-164
gave for writing that rule as containment rather than equality.

**`user_settings/` is excluded too, and it is NOT in the spec's list.** Narrowing the analytics set
to the three rules FR-001 AC4 names would have dropped it without anyone deciding to: it holds the
sender's notification inbox and shared-space connections cache, `protectedFolders.ts` hides it
everywhere in the browser, and — unlike the two rules this plane deliberately does not reuse —
anchoring it at the space root preserves the exclusion with **zero** false positives. Narrowing an
exclusion set is a decision; this one had not been made, only inherited by omission.

**The exclusions apply to a selected FILE as well as to a listing**, and applying them only to the
listing was a real defect. Nothing upstream filters a `file` item — validate-authorize normalises a
*folder* key to a trailing slash and leaves a file key untouched — so naming `{root}DO_NOT_DELETE.txt`
as a file copied the prefix marker into someone's inbox, and naming a folder *as a file* copied its
zero-byte placeholder as a file. AC4 says excluded from the copy set; it does not say "when they
turn up in a listing".

## History

### 2026-08-10

- **Settled:** SPEC-165.
