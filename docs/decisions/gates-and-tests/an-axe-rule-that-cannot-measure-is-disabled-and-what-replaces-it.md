---
type: Decision
title: "An axe rule that cannot measure is disabled, and what replaces it (2026-09-01)"
description: "An axe rule that passes what it cannot measure is disabled with a reason: `target-size` is off under jsdom through one shared constant, and a static sweep in `src/lib/targetSize.test.ts` reports candidates under 24px, not violations."
---

`src/test/axe.ts` ran axe under the `wcag22aa` tag, which includes **`target-size`** — WCAG 2.2
SC 2.5.8's 24×24 CSS px floor. jsdom has no layout engine, so every `getBoundingClientRect` is
0×0, and the rule does **not** error on that the way `color-contrast` does. It reports a **PASS**,
worded *"Safe clickable space has a diameter of 24px which is at least 24px"*, for two adjacent
10×10 buttons. Measured, and pinned as a tripwire in `src/lib/targetSize.test.ts` so the day jsdom
gains layout the rule can be turned back on.

**The hazard is the rule's presence, not its absence.** A reviewer asking "do we assert target
size?" got yes, and axe's own output recorded a pass — the same shape as the dark-mode contrast
blind spot, and the reason the fix is a disable *with a reason* rather than a note somewhere. The
disabled set is now one exported constant spread into all three options bags, asserted as such,
because a bag that spells its own `rules` map and forgets an entry is invisible.

**Audited the rest.** The base bag's tags select **70 rules** (route specs add `best-practice` for
100; a sample of those was probed too and turned up no second offender, but they were not swept); each one that plausibly needs layout, computed
style or a document was probed with markup built to violate it, and the rest were read off as
DOM-only. Four come back silently **inapplicable** rather than passing —
`scrollable-region-focusable` (nothing in jsdom reports as scrollable), `link-in-text-block`,
`css-orientation-lock`, `no-autoplay-audio`. Two come back **incomplete**, which
`toHaveNoViolations` ignores outright — `aria-hidden-focus`, `avoid-inline-spacing`. Two more
(`meta-viewport`, `bypass`) find nothing because the assertions are handed a container rather than
a document. **`target-size` is the only rule measured reporting a pass it cannot make**, which is
what separates it from all of those: an inapplicable rule records nothing and misleads nobody.
`p-as-heading` was suspected on the same grounds and cleared — it violates correctly, on a fixture
built for it, so the suspicion was wrong and the rule stays on.

**What replaces it, and what deliberately does not.** `src/lib/targetSize.test.ts` sweeps every
`.tsx` for interactive tags whose own `h-*`/`w-*`/`size-*` classes fall under the floor, with the
threshold **computed** from Tailwind's `--spacing` and the app's 14px root rather than written
down — one step is 3.5px, so `h-6` is 21px and `h-7` clears by half a pixel. Three limits, all
stated in the file so its silence is not read as coverage:

- **Under 24px is a candidate, not a violation.** SC 2.5.8's spacing exception exempts a small
  target nothing else comes within a 24px circle of. That is geometry the suite cannot do, so the
  register is named `ACCEPTED_UNDERSIZED` and its notes say what a control *is*, never that it
  conforms. A sweep reporting every small control as a violation would manufacture failures on
  correct code — the same defect as the axe rule, pointing the other way.
- **A control whose height comes from its TEXT is invisible to it, on purpose** — and the full list
  of limits lives at the top of the test file, not here, so the two cannot drift. The distinction
  worth keeping in the register is the one that decides whether a static check is honest: a bare
  `text-sm` link is ~15.5px and a `px-3 py-2 text-sm` menu row is 32px, so demanding a height class
  from either would fire on the correct one; but a **checkbox or radio is a replaced element**, with
  no line box padding can grow, so an unsized one is the UA's 13×13 box and there is no correct
  variant to false-positive on. The general argument does not transfer, and reading it as though it
  did left the app's largest population of small controls unexamined until a review counted them.
- **A guard against this class of defect must be planted against.** Every assertion here was
  broken deliberately and watched go red before being reverted, because a check for a vacuous
  guard that is itself vacuous is worse than none. Planting found three holes that reasoning had
  not: an apostrophe in a source comment (`SC 2.5.8's`) read as an opening quote to the attribute
  scanner and hid one control entirely; taking the **first** `className` on a tag read a
  decorative icon's size as the control's whenever JSX attribute order put the icon prop first
  (depth, not position, is what distinguishes them); and the register, keyed by FILE, exempted
  twelve whole files — a registered control could shrink from 21px to 7px, or be half-fixed,
  with nothing going red. It is keyed by the **measured offences** now, so a change to any of
  them is a change to the list.

  Two more were self-referential, and both are the same mistake: an assertion that derives its
  expectations from the thing it guards cannot see that thing shrink. The loop checking the
  disabled rules iterated the constant's own keys, so DELETING `target-size` — restoring the
  vacuous rule across all 41 axe specs — shrank the loop and passed. The set is spelled out now.

**Encode an absolute threshold in an absolute unit.** `min-h-[24px]` is 24px under any root;
`min-h-7` is 24.5px under this one and 21px under a 12px one, and nothing would catch the change.
A rem step expresses visual rhythm, and rhythm is not what this value is for.

> **`ACCEPTED_UNDERSIZED` is the population and the only place it is counted** — a number repeated
> in prose goes stale on the first correct fix with nothing to catch it. The register has since
> been swept in a browser, and `docs/testing/owed.md` carries the measurements and what is owed.
> The tab-strip closes and the column resize handle left it by being sized to an absolute 24px — a
> target at least 24 × 24 needs no spacing exception, whatever encloses it. The Calc panel's and the
> *Band rows by* checkbox lists stay in it: their boxes are still 13 × 13, and it is their labels,
> raised to a 24px minimum height, that bring them under the spacing exception.

## History

### 2026-09-01

- **Settled:** entered the register.
