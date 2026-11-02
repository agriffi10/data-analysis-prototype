---
type: Decision
title: "A rule's `scope` is a field the spec's model did not have"
description: "A colour rule's `column` says what it tests and `scope` (`cell` or `row`) what it paints; layers override per property, and a NULL matches nothing, `<>` included."
---

`ColourRule` carries `column?` — the spec read an absent column as "apply across the row", which
conflates what a rule TESTS with what it PAINTS and leaves the most ordinary rule inexpressible:
colour the whole row wherever `status` is `failed`. One optional `scope: 'cell' | 'row'` separates
them (SPEC-181's `valueKind` is the precedent), and an absent `column` keeps its own meaning — test
every cell in the row.

Precedence runs weakest to strongest — type tint, then band, then rules in order — and each layer
overrides only the **property** it sets. That is what makes "a later rule overrides an earlier one
on the same property" and "conditional rules win over both the type tint and the band" true without
a special case for either. **A NULL matches nothing, including `<>`**: NULL is the one value Athena
does not hand back as a string, and "is not 5" over a value that was never there would paint every
empty cell in the column.

## History

### 2026-08-14

- **Settled:** entered the register.
