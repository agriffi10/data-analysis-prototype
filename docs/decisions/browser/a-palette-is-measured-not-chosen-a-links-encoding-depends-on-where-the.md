---
type: Decision
title: "A palette is measured, not chosen; a link's encoding depends on where the value lands (SPEC-184)"
description: "Formatting changes how a value looks, never what is fetched: it starts no new execution, and no module it added may be reachable from `renderExplorationSql.ts`."
---

Everything this spec adds changes how a value *looks* and nothing about what is *fetched*. That is
SPEC-178's rule seen from the other side, and it is now asserted twice rather than promised: a
scripted UI sequence touching every rule and transformer leaves `runQuery` on the tab's opening
execution, and a transitive **import-closure walk** from `renderExplorationSql.ts` proves no module
this spec added is reachable from the renderer at all. The renderer's signature is a promise about
one function; the closure is a property of the whole graph.

## History

### 2026-08-14

- **Settled:** SPEC-184.
