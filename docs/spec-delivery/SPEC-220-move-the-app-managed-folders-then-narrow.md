# Completed Spec — SPEC-220: Move the App-Managed Folders, Then Narrow

## What was completed?

The move SPEC-219 made safe. Two folders — `athenaresults/` and the receipt folder `archive/` —
now live under a real `system_settings/` prefix in every space, their existing objects were copied
across and the sources deleted, and the fences holding the old locations open came out.
`shared_tables/` did **not** move: those tables were sent to the space by another one and the user
may edit them, so filing them under the folder the app manages would say the opposite of what is
true.

- **The write switch and the browser** (`07e2e0a5`, #684) — the singular builders resolve a moving
  folder under `system_settings/`, and the disclosure row that imitated the prefix was deleted
  because the thing it imitated now exists.
- **The migration** (`98524132`, #683, with its grants in `dbb3f18d`, #678) — a runner script under
  the deploy role, dispatched by `workflow_dispatch`, with a persisted copy record, preconditions on
  in-flight work and a `resolve` mode.
- **The narrowing** (this merge) — the old-anchor statements out, the builders shrunk, and the five
  rules that did not shrink with them.

## The two points of no return, named

| What | When | What it ended |
|---|---|---|
| `finish` run **`34415666578`** — 788 deleted, 0 absent, 0 refused | 2026-09-09 | The objects. Nothing puts a deleted source back. |
| This merge | 2026-09-09 | The fences. Reverting the switch after it leaves the old home unprotected. |

**`07e2e0a5` is the last commit at which reverting the write switch was a rollback** rather than a
split store. Between it and `finish`, both homes held the objects and both were fenced; that is the
window FR-004's live checks ran in, and every one of them was discharged before `finish` was
dispatched.

Run order, all from `main`: `report` `34415568703` → `copy` `34234219110` (788 keys, 0 conflicts) →
`verify` `34234773116` (40 keys) → the FR-004 checks → `finish` → `prove-empty` `34415782105`
("every old prefix is empty across every space") → this merge. `prove-empty` had to run **before**
the merge: it reads the plural builder's first element, and the merge deletes it.

## The finding: five rules the builders did not carry

The spec's FR-005 said this merge would touch "no rule module", and that was wrong — the criterion
is corrected in the spec itself rather than struck.

Five rules mirror a **shared-bucket** Deny. Those Denies put a wildcard where the space name goes,
and an S3 resource wildcard matches `/`, so they reach the folder at any depth below a space root —
which is why the mirrors scan segments instead of comparing a prefix. Every one of them scanned for
the bare folder **name**, fed by no builder: `writeLockedPrefix.ts`,
`focommon.protected._is_at_or_below`, `focommon.delete.assert_item_deletable`,
`apicommon.protected._is_write_locked` and `arcommon.plan._assert_deletable_folder`.

Once the Deny read `*/system_settings/archive/*`, each was refusing writes, deletes and archives
that IAM permits, inside a folder the user made and named `archive` — **over-refusal, which fails
safe**, which is exactly why nothing reported it. A pair test that only asserts the refusal cannot
see it. The pair tests therefore kept two rows with opposite expectations rather than collapsing to
one, and the retired row is the one that catches this class.

All five now read a new builder, `app_managed_segments`, so the segment form has one home the way
the prefix form does.

## The other widening this closed

`results-conversion`'s execution role held `"Effect": "Allow"`, `s3:GetObject` on
`{user space bucket}/*/athenaresults/*`. Every other anchor removed here is a Deny, whose removal
de-restricts; that one's survival would have been an **escalation** — a standing read over what the
narrowing turns into an ordinary user path. It came out with the Denies.

The deploy role gave back what the one-shot borrowed: `athena:ListQueryExecutions`,
`athena:BatchGetQueryExecution`, both `states:ListExecutions`, and `glue:UpdateTable` — which was
never called, because `shared_tables/` turned out not to move, and which was the only IAM fence over
re-pointing any table's `LOCATION`.

## What the post-`finish` catalog read found

One of 16 located tables points inside the moved prefix:
`dwb_testing_all.lotto_draws_by_year` → `.../admin/system_settings/athenaresults/tables/89cfcb49-…`.
It is at the **new** home, absent from all 788 record keys, and was created after the switch — a
table built from query results, which is where those live. `finish` deleted no table's backing
data: the deleted set is 331 `.csv`, 348 `.metadata`, 107 `.txt` and 2 `.json`, with zero keys under
any `athenaresults/tables/` subfolder.

**The 09-09 pre-`finish` reading of "zero located tables point at these prefixes" was true of that
day's population, not a durable invariant.** The read reaches only the nine databases a signed-in
session can see; what bounds the rest is the deleted set's contents, not a sweep. Recorded in
[`owed.md`](../testing/owed.md).

## Deliberately not done

- **`shared_tables/` did not move**, so the `system_settings/shared_tables/` anchors SPEC-219 added
  additively guarded a prefix nothing would ever write to, and came out here.
- **The three retired names are not reserved at a space root.** After the narrowing
  `alice/athenaresults/` is an ordinary user path. The dialogs refuse the three names *directly
  inside* `system_settings/`; uploads, pastes and plane-side moves create folders without calling
  the validator, so that courtesy is partial by construction. A root-aware, all-paths guard is a
  spec of its own — recorded so the next author does not read the courtesy as the boundary.
- **`scripts/migrate_system_settings.py` stays.** Every mode now refuses with
  `narrowing_already_merged`, because the switch-landed precondition reads the plural builder, so a
  dispatch of the destructive workflow cannot delete anything. That refusal was designed and pinned
  before the merge rather than discovered by it.
