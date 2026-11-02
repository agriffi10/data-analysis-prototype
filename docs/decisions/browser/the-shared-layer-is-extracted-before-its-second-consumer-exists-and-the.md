---
type: Decision
title: "The shared layer is extracted before its second consumer exists, and the rule that guards it had to be verified by violating it (SPEC-176)"
description: "A layer two features will share is extracted before its second consumer exists, with no behaviour change; `features/catalog/` is that layer for Query and the Data Explorer."
---

`features/query/` had become the portal's catalog layer by accident: the Glue reader, the Athena
start/poll/results/cancel layer, the space list, the results pager, the background row-count walk and
the column-width store all lived inside a feature that owns an editor and a tab strip. The Data
Explorer (SPEC-179 onward) needs every one of them.

**The extraction leads the arc rather than following it.** Building the Data Explorer first and
factoring afterwards would mean writing `import {useSchema} from '../query/useSchema'` and living
with it — which is exactly the undeclared shared layer SPEC-155 spent a whole spec dismantling, one
directory over. Extracting first costs a large mechanical diff against a codebase where every test
still passes; extracting later costs the same diff plus a second feature's worth of call sites, at a
moment when the pressure is to ship the feature. So `features/catalog/` exists with **no** user-
visible change, no new behaviour and no altered AWS call — the change most likely to go wrong,
made when nothing is riding on it.

## History

### 2026-08-13

- **Settled:** SPEC-176.
