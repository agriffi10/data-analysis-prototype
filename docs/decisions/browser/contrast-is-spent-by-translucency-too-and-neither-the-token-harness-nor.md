---
type: Decision
title: "Contrast is spent by translucency too, and neither the token harness nor axe can see it"
description: "**A palette is measured, not chosen**, in **both** themes; a colour that fails is measured **out**. Every theme trap in this area ships green — that is what makes them traps, and a count of them here went two out of date without anyone noticing, so they are numbered in their own entries and not here. A harness measures **tokens**, so anything painted at less than full strength is invisible to it: **opacity is never how a live element is made quieter** — reach for a quieter TOKEN, because a tint of the same one spends contrast the pairing list has already counted. A translucent **fill** declares what is behind it, and **each thing that can be behind it is its own pairing**, because which one is worst flips between the themes. And **`accent` is a fill, a ring and an icon colour, not text**: in the dark palette it clears 1.4.11's 3:1 against every surface and fails 1.4.3's 4.5 against all of them."
---

The sixth theme trap, and the one the fifth's closing sentence got wrong. `opacity-70` names no
colour, so the literal sweep passes it; it dims the whole element against whatever is behind it, so
the token harness — which measures declared values at full strength — passes it too. Two shipped
that way and were found only by compositing the values by hand: a banner's Dismiss at **2.80:1**
and a toast's close at **2.91:1**, each on the soft fill its own component painted. Both were the
variant's own colour, dimmed; the light palette is the worse half for this, because its status
colours were already tuned to sit just above 4.5 on their own fills and had nothing to spend.

**The rule is that quieter is a different token, never a tint of the same one.** WCAG 1.4.3 exempts
an *inactive* control, so `disabled:opacity-*` passes by rule and the four files that dim on a
condition instead — a button and a menu item carrying a `disabledReason`, an `aria-disabled`
checkbox, a dropzone that stops taking drops — are exempted by name in `lib/colourLiterals.test.ts`,
each with its sentence — and **by the exact utility, not by the file**. The first version exempted
whole files, and a review put a `hover:opacity-80` into `Button` and into `Menu` with nothing
reddening: the app's two most-reused controls were the two the list had opened. The sweep also
matches an opacity utility **with its variant chain**, which `Menu` is the case for — its
conditional dimming sits on the line below its `disabled:` one — and it reads `disabled:` as a whole
SEGMENT of that chain, because `not-disabled:opacity-60` contains the string and is the exemption
inverted: a control dimmed only while it is live. (An earlier draft of this entry claimed the two
that shipped sat beside a `disabled:` a per-line rule would have honoured. Neither file contained
the word at all — the claim was never measured, and a per-line rule would have caught both.)

**A translucent FILL is declared, and every candidate behind it is its own pairing.** `bg-surface/80`
is not `surface`; it is `surface` over whatever scrolls under it, and the landing page's sticky
navigation read 5.91:1 as a token against the **4.35:1** it actually painted when the fixed brand
strip passed beneath — the one background the superseded sentence called safe. `lib/contrast.ts`
gained `composite()` and `CONTRAST_PAIRS` an `over` kind naming the base. Not *the worst* base,
which was the first draft's word and is not something a single entry can hold: the nav's worst
backdrop is the brand strip in light and an accent fill in dark, so both are declared and the
harness measures each in both themes. Each pairing also names the **utility** it describes, and
`colourLiterals.test.ts` matches that against the sources in both directions — an undeclared
translucent surface fails, and so does a pairing that no longer describes anything painted.

That sweep reads a colour-with-alpha by its SHAPE rather than by a list of token names, which is
the correction a review forced: the first version enumerated spellings, and `bg-accent/[0.5]`,
`text-text-2/[0.6]` and `opacity-[0.7]` each walked past it on the first try. **What is still not
tied down, said plainly:** a pairing's foreground is the author's claim about what sits on the fill,
so recolouring that text in the markup reddens nothing — the `utility` link pins the background
only.

**`accent` is not a text colour.** It is declared as a focus ring at 3:1 and as a fill under white,
and the dark palette is built to that: it clears 1.4.11 against every surface and clears 1.4.3
against none. Two sites used it as normal-size text — a help-rail count on its active `accent-soft`
row, and the landing page's mock SQL keywords — and both now take `accent-text`. The icons and the
`role="img"` dirty dot keep `accent`, which is the floor it was derived for; so does the landing
hero, where the type is large enough for 3:1. **This class has its own list** — each file allowed
the bare token says what it paints with it — because a review put both bugs back and every suite
stayed green: two of the three classes had a gate and the third had only the fix.

**Neither axe run can carry any of this.** `color-contrast` is disabled in `test/axe.ts` because
jsdom has no layout engine, which is the standing reason the values are measured rather than
rendered — and a composited colour is a value jsdom would not have had either.

## History

### 2026-09-22

- **Settled:** entered the register.
