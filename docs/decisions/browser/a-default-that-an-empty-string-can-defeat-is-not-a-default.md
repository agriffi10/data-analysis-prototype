---
type: Decision
title: "A default that an empty string can defeat is not a default (SPEC-186)"
description: "A default must survive an empty string, and a live check must be one somebody can run: a check whose assertion no principal or surface can reach is indistinguishable from one that passes."
---

**Context.** A live-check session on 2026-08-14 discharged several long-owed checks and, in doing
so, found that a number of *other* owed checks could not be performed at all — not because the
behaviour was broken, but because the assertion they named was unreachable from any principal or
surface a human has. A check nobody can run is indistinguishable from a check that passes, which is
SPEC-138's "did not run is never clean" and SPEC-137's blind gates in a third place. The same
session found, by eye, that nine dialogs rendered at full viewport width.

## History

### 2026-08-14

- **Settled:** SPEC-186.
