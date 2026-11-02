---
type: Decision
title: "A switch-dependent option gets a guide of its own, gated by that switch (2026-09-26)"
description: "An option in a dialog that another switch can remove gets its own guide, gated by that switch, and a guide whose main action sits behind a flag gets a registry row for it; conditional wording is not used."
---

**An option inside a dialog that a different switch can remove is split into its own guide**, and
the registry hides that guide with the switch. The Parquet, JSON and Excel formats
(`resultsConversion`) and sending or sharing to a shared space (`sharedWorkspaces`) moved out of the
save, send and share guides this way, so those guides stay true with the switch thrown. A guide
whose MAIN action sits behind a flag gets a registry row for that flag even when its section follows
another: *Create a table from a folder* and *Work in a shared space's files* under `files`, *Save an
exploration as a query* under `query`.

**Why.** An audit of every guide against the code found each of these steps overstating while its
switch was off, and nothing in a guide's own gating could see it. Andrew chose the split over the two
alternatives: conditional wording ("if the dialog offers one") puts a hedge in front of every reader
for a state that exists only during an incident, and accepting the overstatement stays right only
for the rename/move/copy/delete guide, which cannot be split without leaving the core of Files
undocumented.

**Not split:** passing mentions of a shared space in a space picker (saving and opening a saved
query, the Explorer's source picker). They overstate while `sharedWorkspaces` is off, and the
content file's maintenance note says so.

**The theme guide moved to an ungated section**, *Getting around*, for the same reason from the other
side: in the Query section it vanished whenever `query` was off, while the Theme control is in the
header on every page.

**Held by** `help.test.tsx` — "names a shared space or a conversion format only in the guides those
switches hide" and "keeps the theme guide with every switch off" — and by the registry walk in
`gatedSurfaces.test.tsx`, which drives every new row in both flag states.

## History

### 2026-09-26

- **Settled:** entered the register.
