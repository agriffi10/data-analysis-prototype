---
type: Decision
title: "A save chooses its space, and one KEY rule decides what that replaces (SPEC-175)"
description: "A save opens on the linked tab's space, else the one remembered space, and `isLinkedSavedQuery` alone judges by KEY whether a save replaces the tab's file; saving into another space is a copy with no delete, and a typed `.sql` extension is lowercased."
---

**Decision (2026-08-12).** The Save dialog asks for a **destination** as well as a name, and the
destination it opens on is **the tab's own space when the tab is linked, else the space SPEC-174
already remembers** — one memory of "the space I am working in", written on every successful save
and shared with the load surface. Two memories were the obvious alternative and are rejected: the
user has no model of a saving-space distinct from a loading-space, so two values can only ever
disagree in a way nothing on screen explains. A linked tab whose space is no longer offered falls
through the same path a stale stored id does, to personal.

**Everything that turns on "is this the same file?" goes through one predicate**,
`isLinkedSavedQuery(link, space, name)`, and it judges the **key** — not the space, and not the
name. Three behaviours read it: the dialog's promise that a submit replaces the file the tab was
opened from, the host's `overwrite` on the write, and therefore whether FR-003's Replace confirm is
raised at all. Split across two call sites each computing its own version, the dialog could promise
an in-place replace while the host wrote a new object. A different name in the tab's own space is a
different file; so is the same name in another space.

**A linked tab's unchanged re-save is confirmed ONCE.** Every save prompts — SPEC-043's silent
write-back is gone — and the prompt has already named the file and the space, so a Replace confirm
on top of it asks about the thing just answered. `SaveQueryRequest` therefore carries `{space,
name}` and **not** `overwrite`: the dialog cannot ask for a silent clobber, because the host is the
only thing that decides one.

**Choosing another space is a copy, and the absence of a delete is the decision.** One `PutObject`
into the new space, the original left alone, the tab re-linked to the new file. Moving is not
offered: a saved query a colleague may be running now must not disappear because someone copied it
elsewhere, and a move across buckets is a copy-then-delete whose second half can fail alone.

**A write failure keeps the dialog open with the destination intact.** The realistic failure is a
shared space whose membership was revoked mid-session, returning `AccessDenied` — and the user's
next move is to pick another destination, which a toast over a closed dialog takes away from them.
The message is `toUserMessage`'s, inline on the field (SPEC-106), and the space control stays
interactive.

**Validation runs on submit; `submitDisabled` does not stand in for a refusal.** SPEC-167 records
this exact failure in the send dialog — a disabled control made an inline refusal dead code, and the
test asserting "the button is disabled" passed straight over the acceptance criterion. The same
reasoning governs FR-007: with no writable space the Save control still **opens** the dialog, and
the dialog **explains itself**, rather than the toolbar rendering a mute disabled button.

**The registry gains a row, and it is not a duplicate.** FR-008 predicted none — every surface here
lives inside `/query`, which the registry gates as a route. But the dialog's destination control is
a **second instance** of the `sharedWorkspaces` choice, and the existing *Shared spaces in the
saved-queries selector* row renders the **drawer**: nothing would notice if this control stopped
being gated, and this is the worse of the two failures, because it offers a colleague's space as a
**write** target. That is SPEC-167's own precedent for the send dialog's recipient kind. The row was
**verified against a deliberate violation** — passing the ungated list reddens exactly that row and
nothing else, measured — rather than trusted.

**A typed `.sql` extension is LOWERCASED, correcting SPEC-173's `basenameFor`.** FR-002 AC4 wanted
`report`, `report.sql` and `report.SQL` to be **one** key; 173 only skipped the *appending*, so
`report.SQL` was a second object — and since `savedQueryName` strips the extension
case-insensitively, the two rendered **identically** in the load list, on the tab and in the Replace
confirm. The reachable failure is not the ambiguity but the overwrite behind it: a tab linked to
`…/report.SQL` pre-fills `report`, which resolves to `…/report.sql`, so the confirm truthfully
offers to replace `report` and **clobbers a file the user never opened** while the one they did is
orphaned. The **stem is deliberately untouched** — `REPORT` and `report` stay two names, which is the
case-sensitivity this same spec keeps — and a `.SQL` object already in a bucket still lists and
opens; only the save path normalises, so re-saving a tab linked to one is a visible Save-as rather
than a silent clobber.

**Two of this spec's tests could not fail, and a third guarded the wrong mechanism.** All three are
recorded because the pattern recurs. (1) The default-space fork (`linkedSpace ?? defaultSpace`) was
only ever exercised where the two **agree** — `onSaved` calls `selectSpace` and keeps them in
lockstep — so either operand could be deleted with the suite green; the bug it hid writes a **copy
into a shared space** and re-links the tab, with every visible cue consistent. (2) **jsdom
implements no implicit form submission**, so "Enter on the space control does not submit" passed
whatever `FormDialog` did; the guard is asserted through **`defaultPrevented`** instead, and
`FormDialog` now intercepts `<select>` as it always intercepted `<input>` — a browser submits a form
from a closed select, and `DestinationPicker` had the same exposure. (3) FR-003 AC4's "does not list
the folder" counter cannot catch the SPEC-043 regression it names, because an **in-memory scan
issues no listing**; the force comes from a test where the loaded list and S3 **disagree in both
directions**.

## History

### 2026-08-11

- **Settled:** SPEC-175.
