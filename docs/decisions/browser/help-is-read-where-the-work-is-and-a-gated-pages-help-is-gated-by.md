---
type: Decision
title: "Help is read where the work is, and a gated page's help is gated by derivation (SPEC-207)"
description: "The header help control opens a panel over the current route through `HELP_SURFACES`, which holds no flags; the panel reads flag-filtered sections and is not addressable."
---

The guides were good and in the wrong place: reading one meant leaving the page, and whatever was
half-filled-in there was a separate worry. The header control now opens a **panel over the current
route** — the shared `Drawer`, so Escape-by-depth, the focus trap, focus restoration and the mobile
full-height sheet all come for free — and the route beneath stays mounted. One `HELP_SURFACES`
registry maps a route path to a section id, and that is **all** it maps: no flag information, held
by a test that sweeps its import list.

**No control was added.** The one already in the bar is repointed, so the mobile header's width
budget is untouched, which is what lets a sibling spec spend that budget instead. The guard is
**route invariance** (the control count on a route with a row equals the count on a route without
one), never a pinned number, because a pinned number is exactly what a sibling spec adding a header
control legitimately breaks.

**A gated page's help is gated by derivation, and NOTHING declares it a second time.** With
`dataExplorer` off, the Data Explorer section is already filtered out of the visible set, so
`/explore` resolves to no section and the control falls back to navigating. `GATED_SURFACES` gains
no row — the registry's per-flag set-equality over row names would fail on one anyway, which is the
mechanism that keeps this honest.

**One row is an exception, and it is the one this spec introduced.** `/data-quality` maps to the
`files` section because that is where its two guides were authored, and there is no data-quality
section to filter out — so with the flag off the panel still opens, over the unavailable page. It
discloses nothing (the two guides are hidden with the flag, and the rest is Files content the user
has anyway), and closing it would mean declaring the gate a second time, which is the thing this
entry is against. Stated rather than left as a silent counterexample to the sentence above.

The two fences that would otherwise fork:

- **The panel reads the FLAG-FILTERED sections, never `HELP_SECTIONS`.** One extracted helper,
  `visibleHelpSections`, serves the page and the panel. A panel reading the raw content would show,
  with `asyncFileOperations` off, a guide `/help` hides — the fork the guide→flag registry exists to
  prevent, reintroduced one layer up.
- **The panel is not addressable and must not become so.** Only the full page is. Putting it in a
  search param would make every route's URL carry help state for no producer that needs it.

**Closing on a route change is adjusted during RENDER, not from an effect** — `react-hooks/set-state-in-effect`
forbids the effect form, and the render-time adjustment is the better shape anyway: the panel is
gone before the new route paints. Deriving `open` from the pathname instead does **not** work, and
the failure is narrow enough to name: open it on `/files`, go elsewhere, come back, and a
pathname-keyed state reopens it.

`/help` gained **guide-level** hashes (`/help#upload-files`) beside the section hashes it already
had. Section hashes are matched first and behave exactly as before. The guide's card is expanded by
carrying the addressed id in the card's React `key` — `HelpGuideCard` reads `defaultOpen` once into
state, so a hash change with the page still mounted would otherwise do nothing — and the page wraps
each card in an anchor `div` rather than changing that component. The scroll effect is declared
**after** the existing scroll-to-top: both run on a hash-driven mount, the later one wins, and
jsdom has no layout, so no test can catch a reordering.

## History

### 2026-08-28

- **Settled:** SPEC-207.
