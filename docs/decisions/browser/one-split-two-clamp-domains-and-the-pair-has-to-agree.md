---
type: Decision
title: "One split, two clamp domains, and the pair has to agree (SPEC-209)"
description: "The split is a stored fraction clamped in two domains that must agree: pixel floors are the whole clamp on a measured column, fraction bounds apply only to an unmeasured one, and the 24px divider counts in the results cap."
---

The editor/results split is stored as a **fraction** and rendered as **pixels**, so it is clamped
twice: `splitBounds` gives the fraction bounds the separator reports as `aria-valuemin`/`max` and
that `Home`/`End` land on, and `clampEditorHeight` gives the pane's pixel height. Two clamps over one
value can describe **different splits**, and the divergence is silent — the pane looks right while
the value a screen reader announces is wrong. A swept test pins the agreement over a grid of
fractions and column heights, and it caught two real cases while it was being written.

What makes them agree is that the **pixel floors are the whole clamp on a measured column**. Mixing
the hard fraction bounds in — a 5% floor that is *looser* than 96px on a 1946px column, a 95% ceiling
that is *tighter* than the results floor on a 3000px one — is exactly what pulled them apart. Those
two constants describe an **unmeasured** column and nothing else: the column measures 0 on the first
render of every mount, `MIN_EDITOR_HEIGHT / 0` is `Infinity`, and axe rejects `"Infinity"` in a
`decimal`-typed `aria-value*`, so a bound that never divides by the measurement is not a nicety.

The divider's own **24px is inside the results cap**, not beside it. A cap that ignores the element
between the two panes is wrong by exactly its height, which is the kind of error that reads as a
rounding artefact and never gets found. It is one constant, applied as an inline style rather than a
Tailwind class, so the number the clamp uses and the number the browser lays out cannot drift.

## History

### 2026-09-01

- **Settled:** SPEC-209.
