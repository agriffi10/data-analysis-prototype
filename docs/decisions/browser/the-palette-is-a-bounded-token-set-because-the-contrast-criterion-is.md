---
type: Decision
title: "The palette is a bounded token set, because the contrast criterion is otherwise unassertable"
description: "Formatting colours are a bounded set of five foreground and four `*-soft` background tokens, never a free picker, so the whole cross product is measured per theme, selection included."
---

FR-002 AC8 asks that every colour pairing meet contrast requirements. Nothing can promise that
about a colour picker, so the model narrows the spec's `foreground?: string` to a five-token union
(`text`, `text-2`, `accent-text`, `success`, `danger`) and its backgrounds to the four `*-soft`
tints, all of them tokens `index.css` already declares — this spec adds none.

**`warning` was measured out of the foreground set.** It clears 4.5:1 on white (5.02) and fails on
the soft backgrounds this spec introduces: **4.49 on `accent-soft`, 4.39 on `danger-soft`**. A
colour that is legible only sometimes is worse than one fewer colour, because nothing at the point
of choosing tells the user which case they are in. The test recomputes the full cross product, the
**sampled gradient** at every step it can quantise to — including the mixed shades between two
tints of different hues, where a "both ends are pale" argument breaks — and the exclusion itself,
so a token that moves reddens CI rather than quietly failing WCAG.

**The surfaces measured against include the SELECTION.** A formatted cell is still selectable, and
an inline background beats the class that paints a selected one — so the cell drops its formatting
fill while selected (`aria-selected` says so either way), and `accent-soft` is one of the three
base surfaces every foreground has to clear.

**Axe cannot carry this criterion.** `color-contrast` is disabled in `test/axe.ts` because jsdom
has no layout engine, so the axe pass over a coloured grid proves its markup and the computation
proves its contrast. Reporting "the axe pass is green" as evidence of contrast would be a claim
that tool never makes.

`FORMATTING_TOKEN_HEX` existed only because a gradient must interpolate values and contrast must be
computed from them; a second test pinned every entry against `src/index.css` itself, since a copy
needs a guard. Vitest resolves a stylesheet `?raw` import **and** a raw `import.meta.glob` to an
empty string (measured), which would have made that guard pass by finding nothing — so it reads the
file, through a one-function ambient declaration rather than by adding `"node"` to the app's
`types` and handing every module in `src/` the Node surface.

> **Superseded in part by SPEC-210 (dark mode).** There is no copy any more, so there is nothing
> for that guard to pin: `formattingTokenHex(theme)` and `formattingBaseSurfaces(theme)` **resolve**
> from `lib/palette.ts`, which is itself pinned to `index.css` by `lib/contrast.test.ts`. The block
> scoping below is now exercised by a real second block rather than only by a synthetic one, and
> the cross product runs **per theme** with the admissible foreground set recomputed rather than
> copied — `warning` is measured out in light and measured back IN on dark, while the offered set
> stays five in both, because a colour a user can pick in one theme and not the other is a rule
> that changes meaning when they switch. Full entry: *The dark palette is derived under the
> harness…* below.

**That parse is scoped to the `@theme` block, and the scoping is the load-bearing part.** A
whole-file `--color-*` match reads every token declaration anywhere in the stylesheet, so the day a
second block appears — which is what a dark theme adds — its values overwrite the light ones and
every contrast assertion goes on passing while measuring a palette the light theme never paints. A
synthetic two-block stylesheet asserts it, because `index.css` cannot exercise the case until that
second block exists.

> **Both of this entry's guards were deleted and restored.** The 2026-08-28 suite reduction
> (`a41bda69`) removed the `index.css` agreement test *and* the sampled-gradient cross product. It
> left `src/test/node-fs.d.ts` with a docstring whose stated *reason* — that the palette has to be
> checked against `index.css` — described a check that no longer existed; the declaration itself
> kept a live consumer in `lib/runtimeConfig.test.ts`, which is why nothing pointed at the gap. And
> it left this entry and `dataExplorer.constants.ts`'s own comment both claiming a guarantee the
> repo no longer held. Restored 2026-08-28. The lesson is about the shape, not the commit: **a copy
> of a source of truth is only as good as the test that pins it, and deleting that test is
> invisible** — the mirror keeps working, the suite stays green, and the three places that promise
> the guard exists go on promising it.

## History

### 2026-08-28

- **Changed:** A suite reduction deleted the `index.css` agreement test and the sampled-gradient cross product; both were restored the same day.

### 2026-08-14

- **Settled:** entered the register.
