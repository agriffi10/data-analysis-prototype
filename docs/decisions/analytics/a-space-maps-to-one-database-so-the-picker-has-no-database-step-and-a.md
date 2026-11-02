---
type: Decision
title: "A space maps to ONE database, so the picker has no database step — and a deep link resolves without asking (SPEC-179)"
description: "A space maps to one Glue database through `spaceDatabase()`, so `?db=` in a deep link is only a cross-check; a link resolves from the memberships list, never by probing, and an unsettled link runs nothing."
---

The Data Explorer's front door. FR-005 specified the picker as *space → database → table*, and the
middle step does not exist in this codebase: a space maps to exactly **one** Glue database — the
personal space to the username, a shared space to its own name, both built by `useConnections` — so
the control would have offered a single option, which is the one-option control SPEC-163 declined to
render for the share dialog's recipient kind. The picker is two panes with the database **shown**
beside its space, and `spaceDatabase()` is the single definition of the mapping. `?db=` survives in
the deep link as a **cross-check rather than a choice**: a link naming a database that is not that
space's resolves to nothing and opens the picker.

FR-005 AC3's "a database the user cannot see is absent rather than present-and-failing" therefore
lands one step later than its wording implies. The space list comes from **memberships**, which are
known reachable; an unreadable database renders an explanation instead of a failing table list. No
table is ever offered that cannot be read, which is the property the AC is protecting.

**The deep link resolves from the LIST, never by probing** (SPEC-113's rule, applied to the
catalog). `denied` and `none` are deliberately different states: a named space this user cannot
reach renders a refusal, while anything malformed opens the picker — an error page for a bad
parameter would tell a user their correct-looking link is broken when the honest answer is "pick
something". Own username always wins over a same-named shared space, mirroring
`useDataQualityReport`'s `resolveSpace`, and `?space=` is **not read at all** with
`sharedWorkspaces` off — never resolved-then-fallen-back, because a "we sent you somewhere else"
banner over a parameter that was never consulted would be a lie (SPEC-167's rule).

**The page must not mount the picker while a link is still resolving, and this was found by a test
rather than by design.** `useConnections` reports loading before the shared spaces arrive; the
workspace rendered the picker meanwhile, and the picker reads the *personal* space's database on
mount — so a denied link issued a Glue call and swapped to the refusal a tick later. Still an answer
about a catalog, just about the wrong space. `LoadingState` now holds the page while a resolution is
pending, and the hook reports `loading` **only when a `?space=` is actually present**: without one
there is nothing to wait for, and a blanket wait would put a spinner in front of every visit to
`/explore`. This is `FeatureRoute`'s own rule one layer down. (Since 2026-09-16 it waits only while
that space is refused, and until a read of the list after the link rather than on `isLoading`: see
`docs/decisions/browser/`, *A `?space=` the cached list lacks is refused only on a read after the link*.) The
parameters are then **dropped with
`replace`** once acted on — tabs survive a reload through `sessionStorage`, so a link left in the URL
would stack a duplicate of the linked table on every reload.

**One surface, registered under TWO flags.** *Explore data* on the Query rail is the mirror image of
"Create table": a Data Explorer capability living on a Query-workspace surface. It is gated by
`dataExplorer && query` and carries a row under each, because either gate can be deleted alone and a
single row would leave the other unwatched. Verified by violation — dropping `explorerEnabled`
reddened both the walking test and the menu-shape test that asserts the **rest of the menu is
unchanged** with the flag off, which is the half the walking test cannot see: a conditional written
one bracket wide takes Refresh table and Share table with it while "the item is gone" still passes.

**Adding a flag key lands in SIX places and two of them are Python.** The spec named the publish
workflow's matrix; the matrix is per **environment**, not per flag, and needed no edit. The two that
matter are `scripts/validate_feature_flags.py`, which refuses an unknown key — without it the publish
job would have failed on the very document the key was added to — and
`lambdas/test_feature_flags_config.py`, which **re-states the same tuple on purpose** so a test
cannot pass by agreeing with a mistake it imported. That second one went red on CI: this repo's four
named local gates (`format:check`, `lint`, `build`, vitest) run no pytest, so **a change touching
`scripts/` or `lambdas/` needs `pytest lambdas/` before the push**, not just `ruff`.
`FEATURE_FLAG_KEYS` **order** is load-bearing beyond iteration: `FeatureRoute` offers the first
ENABLED feature as its fallback link, so a new key goes **last** or an existing unavailable page
silently changes where it points.

**An unsettled link must run NOTHING, and "denied" is not the same condition.** Review measured a
real `StartQueryExecution` behind the refusal: the guard read `denied ? null : …`, and `denied` is
false during the resolution window, so a tab restored from `sessionStorage` started a billed query
for a page that then rendered only the refusal. FR-006 AC2's letter survived — the execution is
against the user's *own* table and no Glue call is made — but cost is this feature's declared
through-line, so the guard is now "the link is not settled". The connections read that resolution is
*made of* stays: it is the user's own cache of their own memberships, the same document
`useDataQualityReport` reads on the same path, and no request touches the space named in the link.

**A tab's close control may not be a `<button>`, because it lives inside `role="tab"`.**
`ExplorationTabStrip` shipped one and tripped axe's `nested-interactive` — the exact arrangement
`QueryTabStrip`'s comments forbid, in a component whose own docstring claimed to mirror it. The ✕ is
a non-focusable `role="presentation"` span and **Delete on the focused tab** is the operable path
(WCAG 2.1.1). The feature had **no axe assertion at all** while 19 other feature suites have one;
that absence is what let a violation ship past a review of the markup.

## History

### 2026-09-16

- **Changed:** A resolving link waits only while the space is refused, until a read of the list after the link rather than on `isLoading`.

### 2026-08-13

- **Settled:** SPEC-179.
