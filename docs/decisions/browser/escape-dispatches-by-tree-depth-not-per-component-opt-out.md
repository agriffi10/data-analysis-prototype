---
type: Decision
title: "Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)"
description: "Escape goes only to the innermost enabled layer through `useEscapeKey`'s one registry, and `Modal`'s `dismissible={false}` swallows it; `Drawer`'s `closeOnEscape` is gone."
---

`useEscapeKey` now maintains a module-level registry of enabled handlers, each tagged with its
`EscapeLayer` depth, and dispatches Escape to **the innermost one only**. Nested dialogs are correct
by construction.

What this replaces: `Drawer`'s `closeOnEscape` prop, a per-component opt-out that every new nesting
had to remember. It is **gone**, not deprecated — it had no consumer left, and a prop nobody sets is
a rule nobody applies. `Modal`'s `dismissible={false}` now **swallows** Escape (`useEscapeBlock`)
instead of letting it fall through and dismiss the layer beneath — the case `dismissible` could not
express before without also disabling backdrop dismiss.

This sits beside, and does not contradict, the settled finding that `stopPropagation` from a React
handler DOES stop `useEscapeKey`'s `document` listener (SPEC-147, measured). That is still true: a
child that stops the event never reaches the registry at all. Depth-based dispatch decides between
layers that *do* reach it.

## History

### 2026-08-06

- **Settled:** SPEC-155, supersedes `closeOnEscape`.
