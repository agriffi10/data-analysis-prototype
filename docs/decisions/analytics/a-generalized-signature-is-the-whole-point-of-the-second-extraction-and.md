---
type: Decision
title: "A generalized signature is the whole point of the second extraction, and one moved constant must not be renamed (SPEC-177)"
description: "`useSaveQuery` takes `{sql, link}` so the save flow serves any caller, `features/saved-queries/` imports neither sibling feature, and `QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` keeps its name and its live `sessionStorage` value."
---

`features/saved-queries/` is the arc's second extraction and it follows SPEC-176's shape exactly:
the `.sql` store — the service, the space memory, the pager, the save flow — came out of
`features/query/` before its second consumer exists, with no user-visible change and nothing live
owed. The reasoning in [the SPEC-176 entry](../browser/the-shared-layer-is-extracted-before-its-second-consumer-exists-and-the.md) applies unchanged; what follows is only what is
different here.

**The one deliberate signature change is what makes the extraction worth doing.** `useSaveQuery`
took `activeTab: QueryTab` — a shape the Data Explorer cannot produce, since it has no tabs. Moving
the module without changing it would have left SPEC-183 reimplementing the collision-and-confirm
path SPEC-175 spent a whole spec getting right: validate, `ensureSavedQueriesFolder` on the CHOSEN
space, write, the `Collision` round-trip that survives a cancelled Replace, the inline failure that
leaves the dialog open with the destination intact. So it takes `{sql, link}` — the two fields the
flow actually reads — and the Query workspace passes `{sql: activeTab.sql, link: activeTab.savedQuery}`
at the call site. An extraction that moves a module but leaves it unusable by the second consumer
has not extracted anything.

**`onSaved` keeps its second argument, against the spec's own Data Model.** The spec sketched
`onSaved: (link: SavedQueryLink) => void`; it ships as `(query: SavedQuery, sql: string) => void`,
because the workspace clears its dirty marker with `rememberSavedSql(query.key, sql)` — against the
bytes that were **written**, not against whatever the buffer holds by the time an async write
returns. Dropping the body would have changed workspace behaviour, which FR-002 AC2 forbids. A
`SavedQuery` is structurally a `SavedQueryLink` plus two fields, so a caller needing only the link
is served by the wider callback; a caller needing the body cannot be served by the narrower one.

**`QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` moved without being renamed, and its VALUE is the reason.**
`s3portal.query.savedQuerySpace.` is a live `sessionStorage` key. The `query.` segment describes
where the module used to live, which is exactly the kind of thing a move invites tidying — and
tidying it silently discards every user's remembered space on the deploy that ships it. The constant
name and the string are both untouched; the docstring says why.

**The layering rule gained a third participant and its message had to change with it.** SPEC-176's
clause governs `features/query/` ↔ `features/data-explorer/` and the layer below them;
`features/saved-queries/` joins on the same footing — it may import neither sibling, while
`features/query/` importing the store stays open (`saved-queries` appears in no `group` pattern).
The rule was verified the only way this rule can be verified — by committing a violation in the
**relative** form a sibling actually produces (`'../query/useQueryTabs'`) and watching lint fail,
in each of the four directions. Reading the config proves nothing; SPEC-176's first version resolved
onto the right files and caught nothing.

**One a11y test had to split rather than move.** `saveQuery.a11y.test.tsx` drove the Replace confirm
through `QueryDialogs`, which is a Query workspace component and stays. Moving the file whole would
have made the new feature's own test suite the rule's first violation. The three dialog passes moved
with the dialog; the confirm pass became `features/query/queryDialogs.a11y.test.tsx`, assertions
byte-identical.

## History

### 2026-08-13

- **Settled:** SPEC-177.
