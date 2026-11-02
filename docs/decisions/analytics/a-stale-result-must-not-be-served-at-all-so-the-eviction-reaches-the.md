---
type: Decision
title: "A stale result must not be served at all, so the eviction reaches the tab in front of you (2026-08-19)"
description: "`invalidateSchema` takes the changed table and evicts that table's cached executions with `resetQueries`, the tab on screen included; only a change naming no table falls back to the whole database, and an async build catches up through `armCatalogCatchUp`."
---

The Data Explorer caches an Athena execution at `staleTime: Infinity, gcTime: Infinity`, keyed by
the SQL it rendered. That cache **is** the cost control — changing a filter and changing it back is
a hit rather than a second bill. What it could not see is a table dropped and rebuilt over
different data under the same name: the SQL renders byte-identical, so the entry stayed a hit and
the pre-rebuild rows came back for the rest of the session, with nothing on the page able to ask
otherwise.

**It evicts what is on screen, and a reload fixing it is not a fix.** The first attempt spared
observed entries to avoid a second billed `StartQueryExecution` — measured, 2 calls where there
should be 1 — which left the tab in front of the user showing old rows until they came back to it.
That is the bug, quieter. `resetQueries` rather than `removeQueries`: removal only re-runs an
observed query if something re-renders afterwards, and in the app something usually does (a toast,
a dialog closing), which is exactly the accident correctness must not rest on.

**The narrowing is what makes that affordable.** The execution key carries the TABLE, and
`invalidateSchema(client, db, table?)` takes the table its caller changed. Dropping the table you
are exploring re-runs it; creating a view beside it does not. Only a change that names no table
falls back to the whole database — an arbitrary DDL statement the user typed and the rail's own
refresh button, both of which ARE requests to re-read everything. A caller that could name its
table and does not is a bug in that caller.

**The rebuild had a second road in, and it was the reported one.** A table build is asynchronous:
the browser enqueues and the table appears minutes later, announced by a notification nothing in
the tab hears. So dropping invalidated and rebuilding did not. `armCatalogCatchUp` is **module
state drained by a listener mounted once in `ProtectedLayout`** — held per component, the arm died
with the control that set it, and both controls that enqueue a build unmount when the user leaves
that route. Residual: `focus` fires on blur→focus only, so a user who never leaves the window gets
no catch-up until they do.

**A registration, not a call beside each `invalidateSchema` site.** `features/catalog/` reaching
into `features/data-explorer/` is the undeclared shared layer pointing the wrong way; five call
sites is five things to forget, and the sixth would be written by someone who had never heard of
this cache. Not a query-cache subscription either: TanStack emits no event for invalidating a key
nothing has cached, and the rail's schema is not always loaded when DDL runs.

## History

### 2026-08-19

- **Settled:** entered the register.
