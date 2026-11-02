---
type: Decision
title: "Consolidation is worth doing against a SWEEP, not against a list"
description: "Consolidate shared UI shapes against a sweep, never a spec's list: a `?raw` glob guard holds each shape to one home, with a guard-the-guard asserting every needle still matches its owner, and `components/` may export only components."
---

The reuse pass found that the problem is not missing components — it is existing components being
bypassed and then drifting. Three chip lists were byte-identical until one grew an `h-6 w-6` remove
target and the other two stayed at `h-5 w-5`; `Badge` shipped and
was used by two files while three others hand-rolled it, each differing by a token or two.

That drift was recorded here for years as "24x24" against "20x20", and **neither figure was ever
real**: the spacing scale is rem-derived against a 14px root, so those classes draw 21px and 17.5px
and *none* of the three met WCAG 2.2 SC 2.5.8's 24px minimum — including the one this entry called
correct. The chip's target is now pinned absolutely at `h-[24px] w-[24px]`, because 24 is a
threshold rather than a step on a scale that tracks the root.

The spec enumerated six status-pill sites; the sweep found **seven** (`LandingPage`, whose own
comment said "Mirrors UploadList's StatusChip"). It counted eleven caption sites; the sweep found
**22 files** across three spellings. A `?raw` glob guard now holds each shape to one home, with a
guard-the-guard asserting every needle still matches its owner — because "found nowhere" reads
exactly like "consolidated".

Two deliberate visual changes, on SPEC-155 FR-007's precedent: neutral pills gain a border, and
`QueryHistoryRow`'s neutral dot brightens from `text-text-3` to `text-text-2` now that every dot is
`bg-current`. **Chip width is bounded** for the first time — a 63-character username
(`^[a-z][a-z0-9_]{2,62}$`) extrapolated to a ~610px chip inside a 448px dialog.

**`components/` may export only components** (react-refresh), which is why the shared class strings
live in `fieldStyles.ts` / `dialogChrome.ts` and `displayedMemberStatus` in `memberStatus.ts`.

## History

### 2026-08-14

- **Settled:** entered the register.
