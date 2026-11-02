---
type: Spec
id: SPEC-177
title: "Extracting `features/saved-queries/` — the Shared `.sql` Store"
description: "Moves the saved-queries store (folder, space memory, pager, save flow) into a shared features/saved-queries/ and generalizes useSaveQuery to take {sql, link}, with no user-visible change."
spec_status: Completed
depends_on: [SPEC-176]
arc: data-explorer
arc_order: 2
---

## Overview

SPEC-183 lets the Data Explorer load a `.sql` file as an exploration source and save an
exploration back out as one. The store that would serve it — the `saved_queries/` folder, its
space memory, its pager and its save flow — lives inside `features/query/`, which SPEC-176 has
just established as a leaf feature that other features may not import from.

This spec moves that store into a shared `features/saved-queries/`, and generalizes one hook
while doing so: `useSaveQuery` currently takes a `QueryTab`, which is a shape the Data Explorer
has no way to produce. Taking `{sql, link}` instead makes the whole collision-and-confirm flow
reusable and stops SPEC-183 from reimplementing it.

Like SPEC-176 this ships **no user-visible change** and is deliberately separated from it, so a
difficult move here cannot block the rest of the arc.

## Scope

### In Scope

- A new `features/saved-queries/` owning the `.sql` store: `savedQueries.service.ts`,
  `useSavedQueries.ts`, `useSavedQueriesPager.ts`, `useSavedQuerySpace.ts`,
  `savedQuerySpace.ts`, `SavedQuerySpaceSelect.tsx` and `SaveQueryDialog.tsx`.
- Moving `useSaveQuery.ts` **and generalizing its input** from `activeTab: QueryTab` to
  `{sql: string; link?: SavedQueryLink}`.
- Moving the `SavedQuery`, `SavedQueryPage` and `SavedQueryLink` types, the
  `SAVED_QUERIES_PAGE_SIZE` and `QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` constants, and
  `queryKeys.savedQueries` (becoming `savedQueryKeys`).
- Extending SPEC-176's layering rule so `features/saved-queries/` may not import from
  `features/query/` or `features/data-explorer/`.

### Out of Scope

- **`SavedQueriesPanel`.** It is the Query workspace's rail panel — a list with tab-opening
  affordances and a mobile home tab. It stays; the Data Explorer's load surface is SPEC-183's.
- **Tab linking.** `useQueryTabs`' `savedQuery` field and everything that maintains it are
  query-workspace state and stay put.
- **Every SPEC-173/174/175 rule.** The store is still `.sql` files in an ordinary folder;
  `UNDELETABLE_ROOT_FOLDERS` still protects only the folder itself; the top-level `.sql`
  filter with `Delimiter: '/'` still keeps the load list coherent; `savedQueryName` still
  strips the extension case-insensitively while the stem stays case-sensitive. None of this
  changes, and no test asserting it is edited beyond its import path.
- **Any behaviour change**, including the S3 calls, the folder marker, the ETag handling and
  the wording of every refusal.
- Renaming anything except where a module's name would misdescribe its new home.

### Corrections made during the build

- **`onSaved` keeps its second argument.** The Data Model below sketches
  `onSaved: (link: SavedQueryLink) => void`; it ships as `(query: SavedQuery, sql: string) => void`,
  unchanged from before the move. `QueryWorkspace` clears its dirty marker with
  `rememberSavedSql(query.key, sql)` — against the bytes that were *written*, not against whatever
  the buffer holds when the async write returns — so narrowing it would have changed workspace
  behaviour, which FR-002 AC2 forbids. Only the `activeTab` → `payload` change, which FR-002
  actually pins, went in. A `SavedQuery` is structurally a `SavedQueryLink` plus two fields, so
  SPEC-183 can ignore what it does not need.
- **`saveQuery.a11y.test.tsx` split rather than moved.** Its fourth case drives the Replace confirm
  through `QueryDialogs`, a Query workspace component that stays — so moving the file whole would
  have made the new feature's own suite the FR-004 rule's first violation. The three dialog passes
  moved with the dialog; the confirm pass is now `features/query/queryDialogs.a11y.test.tsx`, with
  its assertions byte-identical.
- **The rule's message was rewritten.** It named only `features/query/` and `features/data-explorer/`,
  which is what a developer reads when the rule fires on a `saved-queries` import. It now names the
  lower layers too.

---

## Functional Requirements

### FR-001: `features/saved-queries/` owns the store

#### Description:

A new feature directory holds the `.sql` store and its surfaces, with a barrel `index.ts` as
its only public surface. Modules move whole, keeping filenames and exported names.

#### Acceptance Criteria:

- [ ] `features/saved-queries/index.ts` exports every symbol previously exported from
      `features/query/index.ts` that originates in a moved module, under the same names.
- [ ] No module under `features/saved-queries/` imports from `features/query/`.
- [ ] `features/query/` continues to work unchanged, importing what it needs from the new
      feature.
- [ ] `npm run build -w apps/portal` passes and the full Vitest suite exits zero, with no
      test's assertions changed — import paths only.
- [ ] **The consumer sweep is run before the move, not assumed.** A survey at drafting time
      found every importer of every moving module inside `features/query/` — but SPEC-176 made
      exactly this claim, shipped, and found **six** external files including a
      `features/table-builder/` that had been reaching into a leaf feature for two arcs. The
      build must re-run the sweep and record what it finds, including "nothing new".

### FR-002: `useSaveQuery` takes a payload, not a tab

#### Description:

`useSaveQuery` currently reads `activeTab: QueryTab` to source the SQL being saved and the
link identifying what it would replace. It takes `{sql, link}` instead. The Query workspace
passes its active tab's two fields at the call site; nothing about its behaviour changes.

This is the one deliberate signature change in the spec, and it exists so SPEC-183 can reuse
the flow rather than reimplement the collision-and-confirm logic that SPEC-175 spent a spec
getting right.

#### Acceptance Criteria:

- [ ] `useSaveQuery` accepts `{sql: string; link?: SavedQueryLink}` and does not reference the
      `QueryTab` type.
- [ ] `QueryWorkspace`'s behaviour is unchanged: the same dialog opens with the same default
      space and name, the same Replace confirm is raised for a linked re-save, and the same
      inline message appears on a write failure with the dialog left open.
- [ ] `isLinkedSavedQuery` remains the single predicate behind the dialog's promise, the
      host's `overwrite` and whether a Replace confirm is raised at all (SPEC-175).
- [ ] An unchanged re-save is still confirmed exactly once.
- [ ] `SaveQueryRequest` still carries `{space, name}` and **not** `overwrite` — the dialog
      cannot ask for a silent clobber.

### FR-003: `savedQueryKeys` replaces `queryKeys.savedQueries`

#### Description:

The saved-query cache key moves into the new feature under its own namespace rooted at
`['saved-queries']`, following the house pattern and SPEC-176's precedent.

#### Acceptance Criteria:

- [ ] `savedQueryKeys` exports `all` and `list(spaceId)`, keyed by **space** exactly as
      SPEC-173 requires — the same user reads a different list per space.
- [ ] `queryKeys` retains only `all` and `history` after this spec.
- [ ] No module hand-builds a saved-query key array.

### FR-004: The layering rule covers the new feature

#### Description:

SPEC-176's rule gains `features/saved-queries/` as a third participant: it may not import from
`features/query/` or `features/data-explorer/`.

**SPEC-176 shipped this clause once already and it caught nothing** — `no-restricted-imports`
matches the *literal* import source, and one sibling feature reaches another as `'../query/…'`,
which contains no `features/` segment. The pattern must match the relative form, and only
violating it proves that it does.

#### Acceptance Criteria:

- [ ] `npm run lint -w apps/portal` fails on a deliberate import from `features/query/` into
      `features/saved-queries/` — **verified by making the violation and observing the
      failure**, not by reading the config.
- [ ] The violation used to verify is written in the **relative** form a sibling feature
      actually uses (`'../query/useQueryTabs'`), not an alias or absolute form that would pass
      a pattern the real code never produces.
- [ ] `features/saved-queries/` importing from `features/catalog/` is permitted (it needs
      `QuerySpace`).
- [ ] The rule's existing exemptions are unchanged.

### FR-005: No user-visible change

#### Acceptance Criteria:

- [ ] No file under `features/help/` changes.
- [ ] No wording in `lib/errorMessages.ts` changes.
- [ ] No S3 call's parameters change — the listing's `Delimiter`, `MaxKeys` and prefix, the
      folder marker write, and the `PutObject`/`HeadObject` on save are byte-identical.
- [ ] The portal coverage floors (SPEC-150) still pass without being lowered.

---

## Data Model

No new types. These move from `features/query/query.types.ts` unchanged:

```ts
// apps/portal/src/features/saved-queries/savedQueries.types.ts

export type SavedQuery = {
  spaceId: string;
  bucket: string;
  /** `{rootPrefix}saved_queries/{name}.sql` */
  key: string;
  name: string;
  updatedAt: string;
  size: number;
};

export type SavedQueryPage = {
  queries: SavedQuery[];
  isTruncated: boolean;
  nextContinuationToken?: string;
};

export type SavedQueryLink = {
  spaceId: string;
  bucket: string;
  key: string;
  name: string;
};
```

The one changed signature:

```ts
// apps/portal/src/features/saved-queries/useSaveQuery.ts

type Params = {
  spaces: QuerySpace[];
  defaultSpace: QuerySpace | null;
  /** WAS: activeTab: QueryTab */
  payload: {sql: string; link?: SavedQueryLink};
  onSaved: (link: SavedQueryLink) => void;
  toast: ToastApi;
};
```

And the key namespace:

```ts
// apps/portal/src/features/saved-queries/savedQueryKeys.ts

export const savedQueryKeys = {
  all: ['saved-queries'] as const,
  list: (spaceId: string) => [...savedQueryKeys.all, 'list', spaceId] as const
};
```

---

## File & Folder Structure

```
apps/portal/src/features/
├── saved-queries/                   # NEW
│   ├── index.ts
│   ├── savedQueryKeys.ts
│   ├── savedQueries.types.ts
│   ├── savedQueries.constants.ts
│   ├── savedQueries.service.ts
│   ├── savedQuerySpace.ts
│   ├── useSavedQueries.ts
│   ├── useSavedQueriesPager.ts
│   ├── useSavedQuerySpace.ts
│   ├── useSaveQuery.ts
│   ├── SaveQueryDialog.tsx
│   ├── SavedQuerySpaceSelect.tsx
│   └── *.test.ts(x)                 # moved with their modules
└── query/
    └── SavedQueriesPanel.tsx        # STAYS
```

---

## Implementation Phases

### Phase 1: Move the store

- Create `features/saved-queries/` with the barrel.
- Move the service, the two space modules, the three hooks and their co-located tests.
- Split the saved-query types and constants out of the query modules.

### Phase 2: Keys and the generalized save hook

- Introduce `savedQueryKeys`; strip `savedQueries` from `queryKeys`.
- Move `useSaveQuery` and `SaveQueryDialog`; change the input to `{sql, link}` and repoint
  `QueryWorkspace`'s call site.

### Phase 3: The rule and verification

- Extend the layering rule; verify by deliberate violation in both directions.
- Run format, lint, the full suite (exit code, not pass count) and `npm run build`.
