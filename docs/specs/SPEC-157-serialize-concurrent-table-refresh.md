# Spec: Serialize Concurrent Table Refresh

**ID:** SPEC-157
**Status:** Completed
**Last Updated:** 2026-08-05
**Depends On:** SPEC-149 (the in-place `glue:UpdateTable` apply, and the exposure this closes), SPEC-143 (refresh eligibility + `load-table-definition`), SPEC-066 (the table-builder control plane, its FIFO queue and Pipe), SPEC-123 (the ETag-CAS precedent this reuses)

> **This spec adds no user-facing feature.** It closes the one exposure SPEC-149 left open, and
> the whole of it is a correctness change inside the table-builder control plane.
>
> **It expands the table-builder execution role's IAM as in-scope work** (the `CLAUDE.md` infra
> rule). No new resource type is introduced — the lock is an S3 object in a bucket that already
> exists — so the deploy role needs nothing new, and this ships as ONE PR rather than two.
>
> **Rulebooks:** `lambdas/info/best-practices/lambdas/lambdas.md`, `lambdas/info/best-practices/python/python.md`.

## Overview

Two refreshes of the same table can overlap, and the second one to finish wins.

`MessageGroupId` on the request queue is the target **database**, so SQS serializes *delivery*
per database. But the Pipe starts the state machine with `FIRE_AND_FORGET` and returns
immediately, so it is free to deliver the next message while the previous execution is still
running. Delivery is ordered; **execution is not**.

SPEC-149 reduced the damage — its apply is one in-place `glue:UpdateTable`, so neither run can
ever see a missing table — but could not close it: **Glue offers no compare-and-set on
`UpdateTable`**. The worst case is last-write-wins between two definitions.

**The severity is genuinely low, and the spec says so rather than inflating it.** Both runs
re-infer from the same folder, so two overlapping refreshes usually compute the *same* schema and
last-write-wins is a no-op. It only matters when the files change between the two reads — then a
run holding the older view can commit after the newer one, and the table silently carries a stale
schema until someone refreshes again. What makes it worth fixing anyway is that the failure is
**silent**: `diff-schema` reports "unchanged", no notification is emitted, and nothing in `logs/`
says a definition was overwritten.

The fix is a per-table lock, so that the second refresh is **refused with a notification** rather
than racing.

## Scope

### In Scope

- **A per-table lock object** in the admin bucket, acquired and released under **ETag CAS**.
- **Two new states** in the table-builder state machine, on the refresh path only.
- **A `TimeoutSeconds` on the state machine**, which is what makes a stale lock provably stale.
- **A bounded steal** for a lock left behind by an execution that died without releasing.
- **Contention → a user notification**, reusing the existing failure/notify path.
- **A `glue:GetTable`-based freshness guard in `apply-refresh`**, catching the residual window.
- **The table-builder execution role's IAM**, expanded for the lock prefix only.
- **The rejected alternatives, recorded** so they are not re-proposed.

### Out of Scope

- **Serializing CREATE.** The duplicate-name race is already closed by `check-table-absent` plus
  `CREATE … IF NOT EXISTS` (SPEC-066), and a create and a refresh of one table cannot both
  succeed — create requires the table absent. Only the refresh path takes the lock.

  > **SUPERSEDED 2026-09-15.** The race is narrowed, not closed: two same-name creates can both
  > pass `check-table-absent`, and the second's `IF NOT EXISTS` is a no-op. Nothing is overwritten,
  > and the per-database ordering this spec leans on below orders the starts only. The no-op was
  > reported as a created table until later the same day, when execute-ddl gained a read-back that
  > refuses `table_exists` unless the catalog carries the run's own declaration; the create path
  > still takes no lock. — `docs/decisions/control-planes.md`, *A group id orders the STARTS,
  > not the runs*.
- **The other three control planes.** Table-share, data-quality and shared-space have their own
  FIFO groups and none of them performs a read-modify-write on a shared catalog object.
- **Queueing the loser.** A refused refresh is not retried, held, or re-enqueued — see FR-003.
- **Converting the state machine to EXPRESS**, or the Pipe to `REQUEST_RESPONSE`. FR-006 records
  why, with the API-model evidence.
- **Any change to what `apply-refresh` writes.** SPEC-149's `TableInput` allowlist projection,
  its lowercasing, and `ddl.mark_managed` are untouched.
- **A general-purpose locking library.** One verb needs this; a `cpcommon` module for it can be
  extracted the second time a plane does.

---

## Functional Requirements

### FR-001: The lock object, and why it is never deleted

#### Description

The lock is a small JSON object under `locks/table-builder/` in the **admin bucket**, one per
`{database}/{table}`. It is claimed and released with conditional `PutObject` — the same ETag-CAS
mechanism the fleet already uses.

> **Corrected during build (2026-08-09).** This spec was authored 2026-08-05 and named
> `dqcommon.index_store` and `log_sweep` as the precedent; **SPEC-156 FR-001 folded both onto
> `cpcommon.cas` two days later.** The lock reuses `cas.is_precondition` — the one place that
> knows a failed match and a racing create are the same answer — but deliberately **not**
> `cas.cas_mutate`: that loop *retries* on a precondition failure, which is right for an append
> and wrong for a lock, where a lost precondition means another execution holds it and the
> correct response is to refuse.

**It is released by OVERWRITING, never by deleting, and that is forced rather than chosen.** The
table-builder execution role carries an explicit `Deny` on `s3:DeleteObject` for the admin bucket
(`NoDataObjectDelete`), which SPEC-149 deliberately kept when it removed `glue:DeleteTable`. A
lock that released by deletion would require amending that Deny — trading a standing safety
property for an implementation convenience. So "free" is a *state* of the object, not its absence.

#### Acceptance Criteria:

- [ ] The key is `locks/table-builder/{database}/{table}.json`. `database` and `table` are both
      catalog-safe by construction (SPEC-033), so neither can escape the prefix; a test asserts
      the key builder rejects anything failing `CATALOG_IDENTIFIER_RE` rather than sanitising it.
- [ ] The body is `{"version": 1, "holder": <executionArn|null>, "acquiredAt": <ISO-8601 UTC|null>}`.
- [ ] **Acquire** reads the object. Absent → `PutObject` with `IfNoneMatch: "*"`. Present with
      `holder: null` → `PutObject` with `IfMatch: <etag>`. Present with a live holder → refused.
- [ ] **Release** is a `PutObject` with `holder: null` under `IfMatch` of the ETag the acquire
      returned. A release that loses its CAS is logged and **not retried** — losing it means the
      lock was stolen (FR-004), and re-writing would clobber the new holder.
- [ ] `s3:DeleteObject` is never called on this path, and a test greps the verb for it.
- [ ] A precondition failure on acquire (`PreconditionFailed`/412, `ConditionalRequestConflict`/409)
      is treated as "someone else holds it", identically to a live-holder read.

### FR-002: Where the lock is taken, and where it is released

#### Description

The lock must be held across the entire read-modify-write, not merely across the write: the whole
point is that run A's `GetTable` and run A's `UpdateTable` are not separated by run B's
`UpdateTable`. It is therefore acquired **before** `LoadTableDefinition` and released on **every**
terminal path.

#### Acceptance Criteria:

- [ ] A new `AcquireRefreshLock` state runs on the refresh branch of `RouteByMode`, before
      `LoadTableDefinition`. The create branch is untouched.
- [ ] A new `ReleaseRefreshLock` state runs before `RecordSuccess` **and** on the failure path, so
      that a refusal in `diff-schema`, a `TerminalError` in any verb, and a caught Lambda fault all
      release. A test asserts every terminal path in the refresh branch passes through it.
- [ ] Release **never fails the request**: a failed release is logged at `error` and the state
      proceeds. The lock is recoverable by FR-004's steal; a request that did its work and then
      reported failure because of its own bookkeeping would be worse.
- [ ] `ReleaseRefreshLock` carries the ETag from `AcquireRefreshLock` on the state payload. A
      `Choice` on an **absent** path raises uncatchable `States.Runtime`, so the guard is
      `IsPresent` (the SPEC-143 trap).
- [ ] The lock is **not** taken for a request that `validate-authorize` rejects — an unauthorized
      request must not be able to touch another user's lock at all.

### FR-003: Contention is a refusal, and the refusal is the notification

#### Description

The loser is refused, not queued. This mirrors SPEC-144's stance on removals: the request that
cannot safely proceed changes nothing and says so.

Queueing was considered and rejected. A held lock means a refresh of that table is *already
running against the same files*, so the queued run would almost always compute an identical
definition and write it a second time — paying a full inspect-source over the folder to produce a
no-op. The user's intent ("refresh this table") is already being satisfied by the run in progress.

#### Acceptance Criteria:

- [ ] A refused acquire raises a `TerminalError` with reason `refresh_already_running`, routed
      through the plane's existing `Catch` → `RecordFailure` path. No new failure machinery.
- [ ] The user is notified through the existing `notifies_on_failure` path, with wording that
      names the table and says a refresh of it is already running and that this request did
      nothing. Wording goes through `lib/errorMessages.ts`'s single source on the browser side —
      no new raw text is rendered (SPEC-106).
- [ ] The refusal is **not** retried by the state machine: `refresh_already_running` is absent
      from every `Retry` list, and a test asserts it.
- [ ] A refused request leaves the table, the lock and the registry **byte-identical**. A test
      asserts `UpdateTable` is never called on the refusal path.

### FR-004: A stale lock, and the timeout that makes "stale" mean something

#### Description

An execution that dies without releasing — the state machine itself failing, a hard Lambda kill —
would otherwise hold the table's lock forever, and "you can never refresh this table again" is a
worse failure than the race.

**A lock is stealable only because executions are bounded, so the bound comes first.** The state
machine has **no `TimeoutSeconds` today**, which means a Standard execution may run for up to a
year and no age threshold could be justified. Adding one is a prerequisite of this design, not a
tidy-up.

#### Acceptance Criteria:

- [ ] `aws_sfn_state_machine.table_builder` gains a `TimeoutSeconds`. The value is derived and
      recorded: the sum of the refresh path's Lambda timeouts plus their Retry budgets, rounded
      up, and it **must exceed** the create path's Athena polling budget so that adding it cannot
      fail an ordinary create.
- [ ] `STALE_LOCK_SECONDS` is the machine timeout **plus a stated margin**, defined in one place
      and referenced by the verb. A test asserts it is strictly greater than the timeout — a steal
      threshold below the timeout would let a running execution's lock be stolen.
- [ ] A lock whose `acquiredAt` is older than `STALE_LOCK_SECONDS` is stolen: claimed with
      `IfMatch: <etag>` of the stale object, and a `warning` event is emitted naming the table and
      the age. Stealing is never silent.
- [ ] A malformed or unparseable lock body is treated as stale, not as held. A body nobody can
      read is not evidence that a refresh is running, and the alternative is a table that can
      never be refreshed again.
- [ ] Tests cover: a fresh lock is not stolen; an expired lock is stolen; a malformed body is
      stolen; two simultaneous steals — only one wins the CAS.

### FR-005: The residual window, closed as far as it can be

#### Description

A lock reduces the race; it does not eliminate it, and the spec must not claim otherwise. Two
windows remain: the instant between a steal and the writer's `UpdateTable`, and any future path
that writes the table without taking the lock.

`apply-refresh` already performs a `GetTable` immediately before its `UpdateTable` (SPEC-149's
read-modify-write). That read gives a freshness signal for free.

#### Acceptance Criteria:

- [ ] `load-table-definition` captures the live table's `UpdateTime` onto the state.
- [ ] `apply-refresh` compares that captured `UpdateTime` with the one on its own pre-write
      `GetTable`. A difference means another writer committed during this run: the update is
      **abandoned**, and the request fails with reason `table_changed_during_refresh`.
- [ ] That check is documented as narrowing the window, **not closing it** — `GetTable` and
      `UpdateTable` are still two calls, and Glue offers no compare-and-set to make them one. The
      comment says so in those terms, so a later reader does not mistake it for a guarantee.
- [ ] `VersionId` is **not** used as a precondition. Verified against botocore's service model
      (2026-08-05): `UpdateTableRequest.VersionId` is documented only as "the version ID at which
      to update the table contents", with no precondition-failure error. A test pins that we do
      not pass it, so nobody re-adds it believing it is a CAS.

### FR-006: The alternatives, rejected in writing

#### Description

Two obvious fixes look better than they are, and both will be proposed again by someone reading
"the Pipe is fire-and-forget" without checking. Recording the evidence here is cheaper than
re-deriving it.

#### Acceptance Criteria:

- [ ] **`REQUEST_RESPONSE` on the Pipe is impossible, not merely undesirable.** Verified against
      botocore's `pipes` model (2026-08-05): the `InvocationType` documentation states plainly
      that *"REQUEST_RESPONSE is not supported for STANDARD state machine workflows."* Making the
      Pipe synchronous therefore requires converting the machine to EXPRESS.
- [ ] **EXPRESS is rejected on two independent grounds**, either of which is sufficient: its
      5-minute ceiling cannot bound `inspect-source` over a large folder, and its **at-least-once**
      execution semantics would introduce duplicate refresh executions — the exact thing this
      spec exists to prevent.
- [ ] **A finer `MessageGroupId` (database.table) is rejected.** It would serialize *delivery*
      per table, but delivery is already ordered and the gap is that `FIRE_AND_FORGET` decouples
      delivery from execution. It would change nothing, and would also split the per-database
      ordering the create path relies on.
- [ ] Both rejections are recorded in `decisions/` with the model evidence, not only here.

### FR-007: Observability

#### Acceptance Criteria:

- [ ] The verb is instrumented per SPEC-132's per-plane rules: `@observability.traced`, service
      `table-builder`, and the `verb` matching the request `action` vocabulary.
- [ ] Events: lock acquired (fields `database`, `table`, `stolen`), lock refused (`held_since`),
      lock released, and steal (`age_seconds`). Database and table names are metadata and
      permitted under the field rule; the execution ARN is **not** logged as a field.
- [ ] The event count is O(1) per request — no emitter inside a retry loop.
- [ ] The function's environment carries every variable `cpcommon.config._require`s, asserted by a
      test against the Terraform environment block (the PR #196 / #317 cold-start trap, and the
      SPEC-146 lesson that the assertion must parse the `variables` block rather than grep the
      file).

### FR-008: IAM

#### Acceptance Criteria:

- [ ] The table-builder execution role gains `s3:GetObject` and `s3:PutObject` on
      `${admin_bucket_arn}/locks/table-builder/*` — **and nothing else**. It holds neither today:
      its only admin-bucket grant is `GetObject` on `shared-spaces/*`.
- [ ] The `NoDataObjectDelete` Deny is **untouched**, and a test asserts the rendered policy still
      denies `s3:DeleteObject` on the admin bucket.
- [ ] No deploy-role change: the lock is an object in an existing bucket, and the deploy role
      already holds `s3:*` there via `S3AthenaAdminBucketManage`. A comment records the omission
      as deliberate.
- [ ] `aws iam simulate-custom-policy` against the **deployed** role confirms `PutObject` allowed
      under `locks/table-builder/`, `DeleteObject` **explicitDeny** there, and `PutObject` denied
      elsewhere in the admin bucket — each with an `allowed` control alongside, so an
      `implicitDeny` cannot be mistaken for a pass on a wrong ARN.

### FR-009: Tests and lint

#### Acceptance Criteria:

- [ ] `ruff check lambdas/` and the Python suite pass. (`ruff` is a CI-only gate with no local
      counterpart in `CLAUDE.md`'s Common Commands — run it explicitly.)
- [ ] The CAS is tested against a fake implementing **real** conditional-put semantics —
      `IfMatch`/`IfNoneMatch` with a changing ETag — as `log_sweep`'s suite does. A fake that
      ignores the preconditions makes every test here green regardless of the code.
- [ ] Tests cover the FR-001 protocol, both FR-002 release paths, the FR-003 refusal leaving
      everything untouched, all four FR-004 steal cases, and FR-005's abandon-on-change.
- [ ] A live check is owed and recorded in the delivery doc: submit two refreshes of one table in
      quick succession from the UI, and confirm one succeeds while the other produces the
      `refresh_already_running` notification, with both runs visible in `logs/`.

---

## Data Model

```jsonc
// s3://{admin-bucket}/locks/table-builder/{database}/{table}.json
{
  "version": 1,
  "holder": "arn:aws:states:us-east-1:…:execution:…:…",  // null when free
  "acquiredAt": "2026-08-06T09:14:02Z"                    // null when free
}
```

```python
# lambdas/table-builder-common/tbcommon/table_lock.py — the shape, not the implementation.

def acquire(database: str, table: str, holder: str) -> tuple[bool, str | None]:
    """Claim the table's lock. Returns (acquired, etag).

    Conditional PutObject only — IfNoneMatch on create, IfMatch on a free or STALE lock.
    NEVER DeleteObject: the execution role carries an explicit Deny for it on this bucket
    (NoDataObjectDelete), so "free" is a state of the object, not its absence.
    """


def release(database: str, table: str, etag: str) -> None:
    """Mark the lock free under IfMatch. Never raises, never retries a lost CAS."""
```

## Environment Variables

`ADMIN_BUCKET` is already required by `cpcommon.config`. `STALE_LOCK_SECONDS` is a module
constant derived from the state machine's `TimeoutSeconds`, not an env var — the two must not be
able to drift independently.

## File & Folder Structure

```
lambdas/
├── table-builder-common/
│   ├── tbcommon/table_lock.py              # NEW — acquire / release / steal
│   └── test_table_lock.py                  # NEW — at the LAYER ROOT, not inside the package:
│                                           #   deploy-lambdas.yml does `cp -r …/tbcommon` into
│                                           #   the layer, so a test file inside it would SHIP.
│                                           #   Matches every other layer's suite.
├── table-builder-acquire-refresh-lock/     # NEW verb
├── table-builder-release-refresh-lock/     # NEW verb
├── table-builder-load-table-definition/    # + capture UpdateTime (FR-005)
└── table-builder-apply-refresh/            # + the freshness comparison (FR-005)

infra/modules/table-builder/
├── state-machine.asl.json.tftpl            # + two states, refresh branch only
├── stepfunction.tf                         # + TimeoutSeconds
├── lambda.tf                               # + two functions
└── policies/execution.json.tftpl           # + the locks/ prefix, Deny untouched

.github/workflows/deploy-lambdas.yml        # + two matrix rows
docs/decisions/                           # + the entry FR-006 requires
```

## Implementation Phases

### Phase 1: The lock primitive

- `tbcommon/table_lock.py` and its tests, against a fake with real conditional-put semantics.
- **Tests:** FR-001 in full, plus FR-004's four steal cases. Written first — every later phase
  rests on this, and it is the only part with no AWS dependency.

### Phase 2: The two verbs and the state machine

- The acquire and release verbs, their IAM, the two ASL states, and `TimeoutSeconds`.
- **Tests:** FR-002's release-on-every-terminal-path assertion; FR-008's `simulate-custom-policy`
  checks against the deployed role.

### Phase 3: The residual-window guard

- `load-table-definition` captures `UpdateTime`; `apply-refresh` compares and abandons.
- **Tests:** FR-005, including that `VersionId` is not passed.

### Phase 4: Live check and closing out

- The two-refresh live check from the UI.
- Completion ritual: `INDEX.md`, delivery doc, the `decisions/` entry (which **supersedes** the
  "reduced, NOT closed" clause in SPEC-149's entry — mark it in place), and the `CLAUDE.md`
  digest line.
