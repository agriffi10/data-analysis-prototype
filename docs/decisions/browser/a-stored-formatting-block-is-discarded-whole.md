---
type: Decision
title: "A stored formatting block is discarded WHOLE"
description: "A stored `formatting` block is validated whole and replaced with defaults if any part is wrong, colours against the palette; a rule naming an absent column is kept and shown as inapplicable."
---

Unlike the field-by-field normalisation beside it, `formatting` is validated as a unit and replaced
with defaults if any part of it is wrong: a partially-applied colour set is a rule list the user
never built, and a rule that survived while the one meant to override it was dropped paints the
opposite of what was intended. The colours are validated against the **palette**, not merely
against `string` — a stored `#ff0000` would render verbatim as an inline style, and the contrast
the palette is measured for would no longer hold for it. A rule naming a column the current result
lacks is **kept and shown as inapplicable**: a grouping change replaces the column set wholesale, so
that is the ordinary case, and un-grouping brings the column back.

## History

### 2026-08-14

- **Settled:** entered the register.
