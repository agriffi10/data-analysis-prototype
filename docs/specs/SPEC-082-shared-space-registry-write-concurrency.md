# Spec: Shared-Space Registry Write Concurrency (optimistic CAS)

**ID:** SPEC-082
**Status:** Draft
**Last Updated:** 2026-07-02
**Depends On:** SPEC-056, SPEC-062 (shared-space control plane + verb Lambdas)

## Overview

The shared-space **registry** (`{admin}/shared-spaces/<name>.json`) is the declared source of
truth for a space's owner, members, and lifecycle status. Its writer functions in
`lambdas/shared-space-common/registry.py` currently do an **unconditional read-modify-write**
(`load()` → `put_object` with no ETag precondition), even though the control plane runs on a
Standard Step Function started fire-and-forget and the module's own docstring notes that
concurrent executions can touch the same space. Two verbs racing on one space (e.g.
`add-members` vs `remove-members`, or `leave` vs `delete-space`) can therefore **lost-update**
the members list or regress a `deleting` status back to `active`, leaving the source of truth
inconsistent with reality.

The sibling module `cache.py` already solves exactly this with an optimistic compare-and-swap
helper (`_read` returns the ETag, `_write` conditions on `If-Match` / `If-None-Match: *`, and
`_mutate` retries on a 412 precondition failure). This spec brings the registry writers up to
the same concurrency discipline. No new AWS resources, IAM, or infra — a code-only hardening of
an existing module.

## Scope

### In Scope

- Convert the read-modify-write registry mutators to optimistic CAS with bounded retry:
  `finalize`, `save_members`, `set_status` (`registry.py:93/121/142`).
- Close the `reserve` "owner retrying a failed create" branch (`registry.py:82`), which currently
  overwrites with a plain unconditional `put_object` after a `load()`, with an `If-Match` on the
  read ETag.
- Reuse / factor a shared CAS primitive so `registry.py` and `cache.py` don't diverge (extract
  the `cache.py` `_read`/`_write`/`_mutate` shape into something both can use, or mirror it).
- Unit tests covering the concurrent-writer (412) retry path and the lost-update scenarios.

### Out of Scope

- Changing the registry schema, key layout, or the set of lifecycle statuses.
- Cross-space or distributed locking — this is per-object optimistic concurrency only.
- The genuine-create path (`reserve` with `If-None-Match: "*"`) — already atomic, unchanged.
- Any change to the Step Function topology, verb-to-verb ordering, or IAM.

---

## Functional Requirements

### FR-001: Registry mutators use optimistic concurrency

#### Description:

`finalize`, `save_members`, and `set_status` must read the object **with its ETag**, apply their
change to the loaded value, and `PutObject` conditioned on that ETag (`If-Match`). On a `412`
precondition failure (a concurrent writer committed first) they re-read, re-apply, and retry, up
to a bounded number of attempts, then raise a typed error.

#### Acceptance Criteria:

- [ ] Each of the three mutators issues a conditional `PutObject` (`If-Match: <read ETag>`), never
      an unconditional overwrite.
- [ ] A simulated concurrent writer (first `PutObject` returns 412) causes exactly one re-read +
      re-apply + retry that then succeeds; the final object reflects **both** writers' changes
      (no lost update).
- [ ] Exhausting the retry budget raises a typed, non-swallowed error the caller/Step Function can
      record as a terminal failure (not a bare exception, not a silent success).
- [ ] `set_status` never regresses a terminal/`deleting` status back to a live one under a race
      (the re-apply operates on freshly-read state).

### FR-002: `reserve` failed-create-retry branch is conditional

#### Description:

The branch of `reserve` that lets an owner retry a previously `failed` create must overwrite the
existing record conditioned on the ETag it just read, not with an unconditional `put_object`.

#### Acceptance Criteria:

- [ ] The failed-retry overwrite uses `If-Match` on the loaded ETag.
- [ ] Two simultaneous retries of the same failed create cannot both commit — the loser gets a 412
      and is handled (retry-or-typed-error), not a blind double-write.
- [ ] The genuine first-create path continues to use `If-None-Match: "*"` and is unchanged.

### FR-003: Shared CAS primitive (no divergence from cache.py)

#### Description:

Factor the compare-and-swap read/apply/write/retry logic so `registry.py` and `cache.py` share
one implementation (or `registry.py` mirrors `cache.py._mutate` exactly), so the two modules can't
drift in their precondition/retry semantics.

#### Acceptance Criteria:

- [ ] There is a single documented CAS helper used by both modules (or an intentional, commented
      reason they differ).
- [ ] The helper's precondition detection (412 / absent) and bounded-retry behavior are unit-tested
      independent of any one caller.

---

## Testing Notes

- Stub S3 with botocore stubbers / `moto`; simulate a 412 by having the first conditional put raise
  a `PreconditionFailed` client error, then succeed on the retried put.
- Cover: happy path (no contention), single-retry win, retry-budget-exhausted terminal, and a
  `save_members` + `set_status` interleaving that would lose an update under the old code.

## Implementation Phases

### Phase 1: Shared CAS primitive

- Extract/confirm the `_read`(+ETag) / conditional `_write` / `_mutate`(retry) shape as a shared
  helper; unit-test it in isolation (412 retry, absent, exhaustion).

### Phase 2: Convert registry mutators

- Reroute `finalize`, `save_members`, `set_status`, and the `reserve` failed-retry branch through
  the CAS helper; add the concurrency tests; confirm `ruff` + `pytest lambdas/` green.
