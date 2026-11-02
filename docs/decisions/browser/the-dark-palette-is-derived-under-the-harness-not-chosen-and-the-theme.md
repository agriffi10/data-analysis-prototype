---
type: Decision
title: "The dark palette is derived under the harness, not chosen, and the theme boundary put four fences there (SPEC-210)"
description: "Dark values are whatever passes the `lib/palette.ts` contrast harness in both themes, and every token is in a pairing or a named decorative exemption; themed shadows, dual-role tokens, fixed brand surfaces and non-hex colours each ship green if wrong."
---

The rule this project already had — *a palette is measured, not chosen* — is what decides a second
palette too. `lib/palette.ts` declares both themes and every pairing the design uses;
`lib/contrast.test.ts` computes WCAG ratios from those values and fails naming the pair and its
measured ratio, in **both** themes. The dark values are whatever passes it. The harness ran against
the **light** palette first and reproduced every ratio `index.css`'s comments record, which is what
makes it trustworthy for a palette nobody has measured before. axe cannot carry any of this:
`color-contrast` is disabled in jsdom, at both sites in `test/axe.ts`, and the app shell gets one
dark axe pass for markup — the cap is written into that module rather than inferred from absence.

**A completeness guard, not a pairing count.** Every token is either in a pairing or in a named
decorative exemption carrying its reason; a token in neither fails. Measured against the light
palette the four borders are 1.06–1.27, so **any** floor fails the shipped palette — the exemption
is a fact about hairlines, not a convenience, and the list is frozen so "decorative" cannot become
where a failing colour is put. The harness has a deliberately-failing pair asserted to be reported,
because one that silently passes everything is indistinguishable from one that works.

**Four fences the second theme put there, each of which ships green if you get it wrong:**

- **A themed `--shadow-*` is inert.** Tailwind **inlines** an `@theme` shadow value into the utility
  and emits no `--shadow-*` custom property at all (read out of the built CSS), so a dark block
  redefining `--shadow-md` changes nothing while the stylesheet-agreement check beside it passes.
  What survives inlining is a `var()` **inside** the value: each shadow references a
  `--shadow-tint-*`, and the theme overrides the tint. Colours are unaffected — `bg-surface`
  compiles to `var(--color-surface)` and themes itself.
- **One token cannot be both a text colour and a fill.** In the light palette `danger` reads on
  white *and* backs a white button, and `accent-hover` happens to equal `accent-text`. In the dark
  palette those roles pull apart: `danger` has to be light enough to read on a dark surface, which
  leaves it too light to carry white. So the one danger BUTTON gained `--color-on-danger`, and
  `accent`/`accent-hover` are measured as white-on-the-fill rather than as text — which is the
  pairing the design actually uses, verified by grep before the pairing list was written.
- **A fixed brand surface has to be made fixed.** The landing call-to-action strip was `bg-accent`
  with `text-accent-text` buttons; both theme, and in the dark theme the label goes light and
  vanishes against its white button. Its six colours are now plain custom properties declared
  outside `@theme` and outside every theme block, declared once more in `palette.ts`, pinned
  together by a test and measured as four raw pairings.
- **A hex-only sweep misses the colours that matter most.** `text-gray-900` is as unreachable by a
  theme as `#15191e` and invisible to a sweep looking for `#`. Three of them sat on the 404 page —
  a public route that renders the themed shell to a signed-out visitor. The guard reads every
  non-test source through `import.meta.glob('?raw')` (measured to work for `.ts`/`.tsx`, unlike a
  stylesheet) and sweeps hexes, Tailwind's numbered scales, and `white`/`black` separately, the last
  exempted per file with a reason.

**A fifth trap, found by measuring rather than by the theme boundary: a foreground carrying an
opacity modifier.** `text-danger/80` is not `danger` — it is `danger` blended toward whatever is
behind it, so it lands below the number the harness measured for the token, and no pairing
describes it. One shipped at 4.19:1 on its own `danger-soft` fill and nothing could see it: the
literal sweep looks for literals, the harness measures tokens at full strength. Swept now — and
the sentence that once stood here, that a background modifier is "a scrim or a hover state whose
foreground is measured against the result", was **false on both halves** and is superseded by the
[contrast entry](contrast-is-spent-by-translucency-too-and-neither-the-token-harness-nor.md): no foreground was being measured against any composited result, and the sticky
navigation bar was a third thing the sentence did not cover.

**The preference is a module store read through `useSyncExternalStore`** — three states
(`light`/`dark`/`system`, anything else read as `system`), `localStorage`, per browser. **A Context
provider would work equally well, and the entry says so because two justifications for preferring
the store were written here and both were false.** The first: a provider would remount its subtree.
It would not — a reviewer built one and measured it; consumers re-render, the controlled input keeps
its value, the DOM node is identical, and FR-004's no-remount criterion is met by either shape. The
second, written to replace the first: the consumers sit in disjoint subtrees, so a provider would
have to sit above the router. Also false — `RootLayout` renders the header and the `Outlet` as
siblings and already hosts `NavRailProvider` in the exact position a theme provider would occupy.

The one real asymmetry is small: the state lives outside React, so the setter is callable without a
render and the module resolves the preference the same way `theme-init.js` does, with no provider to
thread. **The lesson is not about theming.** A design choice that is genuinely a preference attracts
a justification anyway, each one plausible and each one written with more confidence than the last;
both of these were caught only by someone building the alternative rather than reading the argument
for it. When the honest answer is "either would do", write that.
`public/theme-init.js` stamps `data-theme` before the first paint and is **external, not inline**:
the CSP is `script-src 'self'` with no nonce and no hash, so an inline initialiser would work in dev
and be refused in production. It throws on nothing, because it blocks the module script behind it.

**The control is on the header bar, one instance, both auth states, every width — and it took two
moves to get there.** It began in the header with a copy in `AppNavDrawer`, because below `tablet`
the authenticated bar was over its width budget (SPEC-211 FR-007). Then it went into the account
menu, which removed the duplicate and cost it its name: an unlabelled avatar holding an unrelated
set of options is not where anyone looks for the theme. It is now a named control beside
Notifications, and the duplicate stays gone. The landing route, which suppresses the app header
entirely, carries its own copy.

**What paid for the room is the WORDMARK, and the threshold is `desktop`, not `tablet`.** Naming
three bar controls costs about 210px, and the words that had to yield are the ones nothing else
depends on — the tab strip is the navigation and the labels are the point. A `tablet:` threshold is
the trap here, and it ships looking correct: it fixes the phone, and leaves 900–1023 — an ordinary
laptop, a half-screen window — wrapping the wordmark onto a second line inside a one-line bar.
The band was measured against the former, longer `Data Workspace`, and the rename to `Data Quarry`
does NOT re-derive it. The wordmark's width IS a term in that sum — an earlier draft of this
paragraph claimed otherwise, which was simply wrong — so what the rename buys is a direction, not a
number: `Workspace` is nine glyphs led by a `W` against `Quarry`'s six, which is narrower in any
proportional face, so the edge can only move DOWN and `desktop` is left conservative rather than
unsafe. Note the warrant is the glyphs, not the character count — a count entails nothing about
width in a proportional font, and an earlier draft of this sentence leaned on one. That needs no measurement, which is why it is the claim worth writing. A
differently-shaped bar — another named control, a longer name — moves it the other way and owes a
real measurement.
Signed out none of this applies: no hamburger, no tab strip, no user zone.
**The wordmark was not enough on its own:** measured on 2026-09-10, the bar still overflowed from
900 to 960 and wrapped two tab labels well above that, and the username and the tab icons now wait
for `desktop` too — see [At `tablet` the words stay and the decoration waits](at-tablet-the-words-stay-and-the-decoration-waits-the-top-bar-and-the.md).

**The cost is stated rather than mitigated, because the mitigation does not exist.** Between 900 and
1299 a signed-in user sees the app's name NOWHERE on screen: the wordmark is withheld and
`AppNavDrawer`, which carries it below `tablet`, is mounted only below `tablet`. Two things make
that the accepted answer rather than a gap to close. `desktop` is a real compiled breakpoint and
1024 is not — only `tablet`/`desktop` compile, so hitting the measured 1023 edge means an arbitrary
variant against that convention. And the band where the words would fit but are withheld is
1024–1299, which is slack rather than breakage. `document.title` carries the name throughout. If a
third breakpoint is ever compiled for another reason, this is the first thing that should use it.

## History

### 2026-09-10

- **Changed:** Withholding the wordmark proved not to be enough for the top bar, so the username and the tab icons also wait for `desktop`.

### 2026-08-28

- **Settled:** SPEC-210.
