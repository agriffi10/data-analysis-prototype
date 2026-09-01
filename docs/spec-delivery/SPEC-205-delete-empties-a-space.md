# Completed Spec — SPEC-205: A Delete Empties a Space and Destroys Nothing

Deleting a shared workspace now removes its **people**, not its **things**. Every member's access
ends, the owner's included, and it disappears from every list — while the objects, the Glue database
and the registry record survive, the record keeping `status: "active"` with an empty roster. On a
bucket with no versioning the old behaviour could not be undone at all; this one is undoable by an
administrator. Two costs are permanent and said where users can see them: **a name is never reusable**
and **data a user asked to delete is retained**.

## What was completed?

- **`everActive`, a durable monotonic field** — stamped by `registry.finalize` only on the `active`
  outcome, carried forward on both, and written by one shared writer (`registry.mark_ever_active`).
- **`registry.is_destroyable`** — one predicate with two consumers: the delete verb's route and the
  guard refusing new members. They are complements, and written twice they drifted in every draft.
- **`registry.empty_space` / `registry.restore_owner`**, and three `MembershipRefused` subclasses
  (`SpaceHasNoOwner`, `SpaceNeverActive`, `SpaceAlreadyEmptied`) plus three terminal errors, each
  registered for wording by its **class name**, which is what the shared decoder reports.
- **`cpcommon.registry.may_receive_share`** — `is_active` is no longer callable outside its definer.
- **`shared-space-backfill-ever-active`**, a one-shot Lambda with `report` / `apply` / `stamp` modes
  and its own `workflow_dispatch`, plus the deploy-role `lambda:InvokeFunction` grant it needs.
- **`failedAction: 'create' | 'delete'`** through seven browser sites, so Retry enqueues the verb
  that failed and Dismiss is offered only where it acts.
- Four sweeps: the field's monotonicity, the three reachability predicates, the invoke grant's
  population, and the existing instrumentation count.

### Deliberate deviations

- **`apply` stamps `active` only; `deleting` became a human decision.** FR-001 originally auto-stamped
  both, reasoning that only the delete verb writes `deleting`. True, and it does not follow: delete is
  gated on ownership alone — `validate.py` and `auth.py` hold no status check — so an owner can delete
  their own failed or provisioning create, the verb writes `deleting` before any teardown, and a run
  that dies leaves it there. Auto-stamping would burn such a name forever unseen. The spec criterion
  was rewritten.
- **The `failed`-record discriminator is resources *and timestamps*, not the roster** — and the
  resources alone are not decisive: a create writes its marker second and its database third of eight
  steps, so most failed creates hold both. `reason`, `createdAt`/`updatedAt` and `lastRequestId` carry
  the weight; the object signal excludes the marker.
- **The re-empty normalises rather than skipping the write.** The spec says skipped; the verb has
  already written `deleting` by then, so a skip leaves a completed delete reading as an unfinished one.
- **`forget`'s branch 2 dropped the `status != "active"` conjunct**, being subsumed by
  `is_destroyable`. One shape differs — active, owner is the actor, actor not in `members` — which
  returns `kept` where the spec said cache-only. Safe direction, near-unreachable.
- **FR-001's "No IAM change is needed" was scoped rather than kept.** True of the backfill's execution
  grants, false of the invoker.

## What changed from earlier specs?

- **SPEC-054's name lock is now permanent in effect** — `reg.delete` is reachable only from the two
  never-active routes, so an ever-used name is never released.
- **SPEC-151's `TeardownIncompleteError`** is retained in full on the destroying routes and does not
  apply to the emptying one, which frees no name.
- **SPEC-204's FR-011** asked for `revoke_portal_role` on the emptying route; this supersedes it.
- **`docs/testing/e2e.md` had two rows inverted by this change** — that deleting takes the Glue
  database, and that the name is re-creatable afterwards. The second was the *proof* the old teardown
  was complete and is now the proof the record was kept.
- Both destination validator suites' fixtures gained an `owner`. Neither suite had any coverage
  distinguishing owner-present from owner-absent, so nothing was protecting the changed behaviour.

## Verification

`pytest lambdas/` (2011), the portal suite (2177), `ruff`, `mypy`, `validate_docs.py`, `tofu validate`,
`tofu fmt`, `eslint`, `prettier` and `npm run build` — all green, and each PR verified with the later
phases' commits out of the tree so none was green on its successor's code.

**Fourteen mutations were planted, run and reverted; every guard is caught by a named test.** Six
survived a first pass and their tests were written in response — including the `emptiedAt` guard,
both name-freeing routes' union, and both resurrection re-reads.

Deferred: the live checks in `e2e.md`'s shared-workspaces section, and six rows in `owed.md` — the
retained objects and database (the owner is precisely the person who can no longer see them), the
inert record (no UI path is left to attempt it), the share/send refusals, the failed-delete
affordances, a Lake Formation denial on `GetDatabase`, and the query workspace inside the credential
window.

**Two operational obligations**, both stated on the PRs: the backfill must be dispatched before the
verb change deploys, and FR-011's Glue databases-per-account quota increase must be requested, with
the resulting headroom recorded as a measurement.
