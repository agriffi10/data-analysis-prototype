---
type: Decision
title: "A hidden column is still part of the row"
description: "Formatting is evaluated over every column, hidden ones included, and the dialogs judge applicability over the same list, so hiding a column a rule reads does not stop the rule."
---

Formatting is evaluated over EVERY column, not the visible ones. A rule reading `status` must keep
painting its row after `status` is hidden, and the dialogs are handed the same list, so what they
report as applicable is what the evaluator can actually see — judged over the visible columns, the
dialog called a rule fine while it silently did nothing, and striping turned itself off when every
chosen column was hidden. Formats for hidden columns are simply never looked up.

## History

### 2026-08-14

- **Settled:** entered the register.
