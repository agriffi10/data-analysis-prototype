---
type: Decision
title: "jsdom has no layout, so a containment property must be arithmetic"
description: "jsdom reports every rect as zero, so a containment property is asserted as arithmetic over a pure function such as `listPlacement()`; the DOM test asserts only that the bound is a measurement."
---

The suggestion listbox overhung the Add-members dialog by **97px** (3 of 8 options visible) because
its flip logic measured `window.innerHeight` — right for a combobox on a page, wrong for one inside
a dialog, where `Modal`'s panel is `overflow-y-auto` and is what actually clips it. The component
now walks to its nearest scrollable ancestor and caps the list to the room there is.

The AC asked for a numeric assertion (`listbox.bottom <= dialog.bottom`), and **jsdom reports every
rect as zero**, so the geometry moved into a pure `listPlacement()` and the test derives the list's
far edge from the returned placement — over the measured case and over a sweep of every field
position in a 600px dialog. The DOM test asserts only what the DOM can see: that the bound is a
*measurement* rather than the old fixed `max-h-60`.

The flip is deliberately **conservative** — it goes up only when below is cramped AND above is
roomier — because below is where the reading order expects the list.

## History

### 2026-08-14

- **Settled:** entered the register.
