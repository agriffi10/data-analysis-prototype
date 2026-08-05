# Completed Spec — SPEC-145: Refresh Table — Menu Item, Dialog & Notifications

## What was completed?

The browser surface for the refresh arc — the first (and only) part of 143 → 144 → 149 a user can see.

- **A `Refresh table` item** in the Query rail's table menu (`DatabaseNode.tsx`), between **View data** and
  **Share table**; omitted for views, disabled without a `location`. `TableActions` gained `onRefreshTable`.
- **`RefreshTableDialog`** — the confirm dialog on `ConfirmDialog`, in both states, with the always-present,
  never-remembered removals opt-in.
- **`useTableRefresh(notify, linked?)`** — dialog state, enqueue, toast, and the FR-005 rail invalidation.
- **`enqueueTableRefresh`** in `tableBuild.service.ts` — `mode: 'refresh'`, `partitionKeys: []`, `allowRemovals`
  only when ticked, through the existing `enqueueFifoRequest`.
- **`parseTableLocation`** (`tableRefresh.location.ts`) and **`parseRefreshLink`** (`tableRefresh.link.ts`) — the
  two pure parsers the feature turns on.
- **Help & guides**: two new guides under **Tables** (*Refresh a table after the files change*, *When a table
  can't be refreshed*) and a pointer to them from the Create-table guide.

### Deliberate deviations

- **FR-002's "briefly unavailable" line was corrected, not implemented.** That criterion predates SPEC-149,
  which replaced 144's drop-and-recreate with one in-place `glue:UpdateTable` — there is no window. The copy
  says the table stays queryable throughout. Struck in place in the spec with the reasoning.
- **`useTableRefresh` takes an optional second argument**, `{target, onConsumed}`, instead of the pinned
  `(notify)`. The link-borne dialog cannot be *opened* from an effect: React Compiler's
  `set-state-in-effect` rule (blocking in `npm run lint`) rejects both the `setState` and the
  `setSearchParams` that the capture-then-open shape needs. So the target is **derived from the URL** and
  passed in; an explicitly opened table always wins. This is the shape react.md §3 asks for anyway.
- **The query parameters are cleared when the dialog is acted on** (confirm or dismiss), not the moment it
  opens — the derived form has no earlier point to clear them at, since clearing *is* what closes the dialog.
  A reload after the user acts does not reopen it, which is what FR-005's criterion is for. A link that
  resolves to nothing (unknown table, unreachable database, a view) leaves its parameters in place and shows
  nothing at all; nothing else reads them.
- **`space.kind` is derived from `database === username`**, not read off the rail connection — `open`'s pinned
  signature carries no connection, and the two are equal by construction (the personal database *is* the
  username, SPEC-033) and re-checked server-side against the verified actor.
- **One file beyond the spec's list**: `tableRefresh.link.ts`, so FR-005's validation rules are unit-testable
  outside the 1700-line workspace.

## What changed from earlier specs?

- **`TableActions` (SPEC-044/093) gained `onRefreshTable`** — every implementor updated; `canViewSourceFiles`
  untouched.
- **`enqueueTableBuild` is unchanged.** The refresh is a second function over the same queue rather than a
  `mode` parameter on the create path, as SPEC-143's comment anticipated.
- **`QueryWorkspace` now reads the router location** (`useLocation` + `useSearchParams`) — its first query
  parameters. It reads the RAW `location.search`: `URLSearchParams` decodes, and SPEC-144 percent-encodes each
  column name around a comma separator, so `URLSearchParams.get('removed')` would split a column named `a,b`
  into two phantom columns. `parseRefreshLink` splits before it decodes.

## Verification

`npm run test` (1299 passing, 168 files), `npm run lint` and `npm run format:check` green locally, plus
`tsc --noEmit`. Axe clean in the plain, link-borne and busy dialog states.

**Owed live** — this is the surface that makes the arc's two live checks runnable from the UI, and they are
still owed: FR-010's add-column / remove-column / opt-in sequence (including against a *partitioned* table),
and SPEC-149's `Description` + column-comment preservation read-back, which is also where the **column-casing
premise** gets settled. See `CLAUDE.md`.
