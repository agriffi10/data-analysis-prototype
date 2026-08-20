# Completed Spec — SPEC-187: File Operations — the Plane, the Request Contract & validate-authorize

## What was completed?

The seventh control plane's foundation, in five PRs. The plane is **live in production** and the
browser has an enqueue service that **nothing calls** — the file browser still runs its existing
synchronous paths, so no user-visible behaviour changed.

- **`cpcommon.lock`** — the compare-and-set lock protocol, extracted out of `tbcommon.table_lock`
  ahead of its second consumer. `tbcommon` and `focommon` both bind to it; table-builder's two lock
  suites were not rewritten, which is what makes the move provably behaviour-preserving.
- **`lambdas/file-ops-common/focommon/`** — `config`, `paths`, `authz`, `protected`, `outcomes`,
  `messages`, `notify`, `lock`. Tables and wording; every algorithm stays in `cpcommon`, enforced by
  an AST sweep.
- **`infra/modules/file-ops/`** — FIFO queue + DLQ, Pipe, Standard machine with the per-space lock's
  waiting loop and three release states, one execution role holding **no grant on either data
  bucket**, and the `TIMED_OUT` door.
- **Four verbs** — `validate-authorize`, `acquire-lock`, `release-lock`, `fo_notify_failure`.
- **`fileOps.service.ts` + `fileOpRouting.ts`** — the enqueue path and the sync/async predicate,
  plus `lib/spaceDigest.ts`, which file-send now shares.
- **`docs/testing/fixtures/spec-187-file-ops-plane.sh`** — nine live checks, all CLI-only, all
  recorded as **owed**.

## What changed that a reader would not expect

**The lock protocol moved, and that was escalated rather than decided.** Copying it would have left
two full CAS lock implementations in the fleet. Extracting it meant this spec editing a shipped
plane, which is the user's call; the extraction went in as its own PR with its own review.

**The machine has no `Validated` Pass, and its absence is load-bearing.** Every neighbouring plane
rebuilds the whole state there to cross-check the verb's return shape. Three of this contract's
fields are **absent for a delete**, and a `Pass` reading an absent path raises an uncatchable
`States.Runtime` — so the very first delete would have died before `NotifyFailure` and told the user
nothing. `StampExecution` merges the execution ARN with `ResultPath` instead, reading only
`$$.Execution.Id`. A rule over every `Pass` now forbids reading an optional field, because the next
person will reach for the pattern the other planes use.

That removal took the verb↔ASL cross-check with it, which was not noticed until a reviewer mutated
the code: deleting `requestId` from the verb's output left all 4000 tests green. The contract is now
read from the rendered ASL — read paths only, since a bare `$.x` search also matches every
`ResultPath`.

**The two runtimes measured the byte cap differently.** Python escapes non-ASCII by default and
JavaScript does not, so 170 accented filenames measured 25,671 bytes in the browser and 66,471 on
the plane — the browser accepting selections the plane then refused by notification. The plane now
measures `ensure_ascii=False`, which is the quantity that actually travels, and the mirror test
compares **measurements** rather than the two constants.

**Deliberately narrower than the planes it was modelled on:** no Cognito grant (this plane verifies
a token offline and authorizes against a *space*, never a user directory), no Distributed-Map
statements on the state-machine role, and no data-bucket grant at all.

## What is owed

All nine live checks. Nothing in the browser reaches this plane until SPEC-190, so every one is a
hand-crafted envelope — see `docs/testing/owed.md` §1 and the script. Two of them need techniques
that are easy to get wrong: the contention check needs **one `send-message-batch`** (two submits
seconds apart both return independently, because this machine does no work), and the wedged-lock
check needs a **dead** holder (a live waiter refreshes its own `acquiredAt` and is never stolen).

Also owed: **one real table refresh against the deployed plane**, because the `cpcommon.lock`
extraction touched a shipped path and unit suites passing unedited is strong evidence but not proof
about deployed behaviour.

## Notes for SPEC-190

1. **`requiresControlPlane` needs a single call site and the browser has four** (`confirmDelete`,
   `confirmMove`, `confirmCopy`, `confirmRename`) — the branch has to **move**, not be consulted
   four times.
2. **Consult it AFTER the emptiness guard, never before.** It throws on an empty selection. That is
   unreachable today only because the toolbar disables at zero selected and `useDelete`/`useCopy`
   early-return — **`useMove`'s `runMove` has no such guard**, so a call at its head would abort a
   React event handler with no feedback.
3. **The overwrite retry is a SECOND SUBMIT** with a fresh `submittedAt`, or the plane refuses the
   very objects the user just agreed to overwrite.
4. **FR-008's "a first submit can never carry `overwrite`" is owed.** The service forwards whatever
   it is given; that AC is dischargeable only where the gesture is built.
5. Listing **reconciliation** replaces `invalidateListing`, and the shared-space "Refresh access"
   recovery needs a new trigger.

## Notes for SPEC-188

- `focommon/outcomes.py` ships the record shape and three members (`noop`, `protected`, `refused`).
  **`refused` is not in SPEC-188's own enumeration** and needs adding to it.
- The ancestor question is closed only for the **space root**. A folder containing a nested
  protected folder is the expansion's problem, and the spec already says a nested marker is excluded
  from the plan rather than refused.

## User-facing docs

**Nothing user-facing changed**, so the Help sweep was checked and skipped: the file browser still
runs its existing synchronous paths and no gesture reaches the plane. SPEC-190 and SPEC-191 own the
visible change.
