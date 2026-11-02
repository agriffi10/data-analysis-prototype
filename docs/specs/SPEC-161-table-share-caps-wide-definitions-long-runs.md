---
type: Spec
id: SPEC-161
title: "Table Share at Scale — Raised Caps, Wide Definitions & the Long-Running Share"
description: "Raises table share's object and byte caps and adds a recipients-times-objects cap, moves the table definition to an S3 pointer, and adds a state-machine timeout so large shares of wide tables succeed."
spec_status: Completed
depends_on: [SPEC-160, SPEC-090, SPEC-152, SPEC-157]
arc: table-share-at-scale
arc_order: 2
---

**Dependency notes:** SPEC-160 (the Distributed-Map transfer engine), SPEC-090 (caps + the copy-plan pointer), SPEC-152 (`NotifyFailure`), SPEC-157 (`TimeoutSeconds` is a top-level ASL field)
## Overview

SPEC-160 moves the copy off a single Lambda, but every ceiling written for that Lambda is still in
force: a share still refuses above 1000 objects or 20 GiB, and a wide table's cloned definition still
rides inline on the Step Functions state under a 32 KiB cap. This spec lifts the ceilings to match
the new engine, moves the table definition onto the same S3-pointer discipline the copy plan already
uses, and closes the two things a genuinely long run makes real — a machine that can now run for
hours needs an explicit timeout, and a request that now writes a multi-megabyte manifest needs those
artifacts to expire.

The result is the shape the user asked for: a table of several hundred Parquet or CSV part files
with a hundred columns shares without hitting a refusal that exists only because of how v1 copied.

## Scope

### In Scope

- **Re-sizing the caps** to the new binding constraints, with a new `SHARE_MAX_TRANSFER_ITEMS` cap
  on `recipients × objects` (the manifest's real bound) alongside the re-sized object and byte caps.
- **`tableDefinition` moves to an S3 pointer** — `{admin_bucket}/table-share/{hash}/definition.json`,
  read by `create-table` — retiring `SHARE_MAX_DEFINITION_BYTES` as a *state-size* bound.
- An explicit **`TimeoutSeconds`** on the table-share state machine, so a wedged run terminates and
  reaches `NotifyFailure` instead of hanging.
- Confirming the **existing** admin-bucket lifecycle rule (`expire-table-share-copy-plans`) covers
  the new artifacts and cannot expire a live run's manifest underneath it.
- Updated refusal wording — the "too large for v1 — S3 Batch Ops deferred" reason no longer
  describes anything true.

### Out of Scope

- The transfer mechanism itself — SPEC-160.
- Progress reporting to the browser (a percentage, a live run view). The share stays fire-and-forget
  with a completion notification; nothing in the request contract changes.
- Resuming or redriving a partially-transferred share.
- Making the caps user-configurable or per-user. They stay named constants.
- Removing caps entirely. An unbounded share is a denial-of-service on the plane and on the
  recipient's prefix; every limit below is re-sized, not deleted.

---

## Functional Requirements

### FR-001: Re-sized caps

#### Description:

`SHARE_MAX_OBJECTS` and `SHARE_MAX_TOTAL_BYTES` are raised to values sized for the Distributed Map,
and a new `SHARE_MAX_TRANSFER_ITEMS` bounds the manifest itself.

#### Acceptance Criteria:

- [ ] `SHARE_MAX_OBJECTS`, `SHARE_MAX_TOTAL_BYTES` and `SHARE_MAX_TRANSFER_ITEMS` are named
      constants in `tscommon.config`, each with a docstring naming **which** limit sized it
      (`inspect-source`'s listing time, the manifest write, the reader's file-size limit).
- [ ] A share of several hundred objects totalling more than 20 GiB **succeeds** — the case that
      motivated this arc.
- [ ] `recipients × objects` above `SHARE_MAX_TRANSFER_ITEMS` is a whole-request terminal failure
      before any manifest is written, and the reason names the item count and the cap.
- [ ] `SHARE_MAX_RECIPIENTS` (50) is **unchanged** — it bounds the inline Map's state and the
      per-item error detail, neither of which this arc touched.
- [ ] Every cap refusal reason is rendered through the `cpcommon` message `Resolver` (SPEC-156), not
      composed at the call site.

### FR-002: The definition rides as a pointer

#### Description:

`inspect-source` writes the cloned definition to S3 and emits a key; `create-table` reads it. The
Step Functions state stops carrying it.

#### Acceptance Criteria:

- [ ] `inspect-source` writes `{admin_bucket}/table-share/{hash}/definition.json` and emits
      `definitionKey`; the state no longer contains `tableDefinition`.
- [ ] `create-table` loads the definition from that key and produces a table **byte-identical** to
      what it produces today for the same source — a test compares the rendered DDL both ways.
- [ ] A 100-column table with column comments and projection `TBLPROPERTIES` shares successfully.
- [ ] `SHARE_MAX_DEFINITION_BYTES` no longer bounds the state; if a size bound is kept at all it is
      re-expressed as an object-size sanity check with a docstring saying so.
- [ ] A missing or unreadable `definition.json` fails **that recipient** with a clear reason, not
      silently creating a table from a partial definition.

### FR-003: The machine cannot hang

#### Description:

The state machine declares a `TimeoutSeconds` sized for the new caps.

#### Acceptance Criteria:

- [ ] `TimeoutSeconds` is a **top-level** field of the state-machine definition (not a resource
      argument, not a task field), set to a named value.
- [ ] A run that exceeds it fails with `States.Timeout`, reaches `NotifyFailure`, and the sender is
      told — "it just never came back" stays unreachable (SPEC-152's guarantee).
- [ ] The timeout is larger than the worst-case run implied by the FR-001 caps, and the spec's
      delivery doc records the arithmetic.
- [ ] The SPEC-152 fleet test still passes.

### FR-004: Request artifacts expire — and not too soon

#### Description:

**The rule already exists.** `expire-table-share-copy-plans` on the admin bucket
(`filter { prefix = "table-share/" }`, `expiration { days = var.admin_results_retention_days }`)
already covers every artifact this arc adds — manifest, definition and Map Run results all live
under `table-share/` — and `check "admin_lifecycle_rules_are_prefix_scoped"` already pins the prefix
scoping. So the obligation here is **inverted**: nothing new needs expiring, and the risk is that an
existing rule expires a *live* run's manifest underneath it, now that a run can last hours.

#### Acceptance Criteria:

- [ ] `admin_results_retention_days` is confirmed to exceed the new `TimeoutSeconds` by a stated
      margin; if it does not, the variable's default is raised and the delivery doc records both
      numbers.
- [ ] The new artifacts (transfer manifest, `definition.json`, the `ResultWriter` export) are
      confirmed to sit under the `table-share/` prefix, so the existing rule covers them with **no
      new rule and no new rule id**.
- [ ] No duplicate lifecycle rule is added, and the existing `check` block still passes.
- [ ] The execution role's `s3:DeleteObject` Deny on the admin bucket is **unchanged** — expiry is
      the bucket's job, not the plane's.

### FR-005: Honest refusal wording

#### Description:

**The docs are already corrected** (2026-08-10): `architecture.md` → *Table Share* carries a
superseded marker, *Deferred / Future Scope* no longer lists a Batch Ops scale path, `decisions/`
→ *Table Share* has the amended fence, and `ARCS.md`, SPEC-090, SPEC-091 and SPEC-090's delivery doc
each carry an in-place marker. What remains is three strings in `lambdas/`.

**They are operator-facing, not user-facing** — worth stating precisely, because the obvious reading
is wrong. Both call sites pass the phrase as a `TerminalError` **detail**, which
`tscommon.notify.emit_failure` deliberately does **not** forward to the user message; it stays on
the exception for logs and the Step Functions record. The user sentence is
`messages.py`'s `"source_too_large"` — *"the source table is too large to share."* — which has never
contained the phrase and needs no change. The audience for this fix is an operator reading a failed
run, and the reason it matters is that a stale detail sends them looking for a Batch Ops path that
no longer exists.

#### Acceptance Criteria:

- [ ] `table_share_inspect_source.py`'s two `TerminalError` details no longer mention S3 Batch
      Operations; they state the measured value and the cap, nothing more.
- [ ] `tscommon/config.py`'s `SHARE_MAX_OBJECTS` docstring is corrected the same way.
- [ ] The user-facing `"source_too_large"` sentence is **unchanged** — it was already correct, and
      it continues to resolve through the `cpcommon` `Resolver`. The detail stays composed at the
      raise site and bounded by `bounded_detail`: detail is operator context and wording is the
      `Resolver`'s, and SPEC-156 settled that split.
- [ ] A grep-style check fails if the retired phrase reappears anywhere in `lambdas/`. **No existing
      test asserts the old wording** (the suites assert `exc.reason` and the user sentence, neither
      of which carries it), so this check is the only guard and must be added, not assumed.
- [ ] **No further docs edit is needed** — re-editing `architecture.md`, `decisions/`, `ARCS.md` or
      the SPEC-090/091 markers for this would mean one was missed, which is itself the finding.

---

## Data Model

```python
# tscommon.config — after this spec
SHARE_MAX_OBJECTS          # re-sized; bound = inspect-source listing time
SHARE_MAX_TOTAL_BYTES      # re-sized; bound = acceptable wall-clock for the Map Run
SHARE_MAX_TRANSFER_ITEMS   # NEW; bound = manifest write + ItemReader file-size limit
SHARE_MAX_RECIPIENTS = 50  # unchanged

# inspect-source output — tableDefinition replaced by a pointer
{ "definitionKey": "table-share/{hash}/definition.json",
  "copyPlanKey":   "table-share/{hash}/copy-plan.json",
  "location": { "bucket": "...", "prefix": "..." },
  "partitioned": true }
```

## Implementation Phases

### Phase 1: The definition pointer

- `inspect-source` writes `definition.json`; `create-table` reads it; assert DDL equivalence against
  the current inline path before deleting it.

### Phase 2: Caps

- Re-size the constants, add `SHARE_MAX_TRANSFER_ITEMS` and its pre-manifest check, move every
  refusal string onto the `Resolver`, and retire the S3-Batch-Ops phrasing.

### Phase 3: Timeout + retention check

- Top-level `TimeoutSeconds`; confirm `admin_results_retention_days` clears it by the stated margin
  and that the new artifacts fall under the existing `table-share/` rule. **Do not add a rule.**

### Phase 4: Verification

- **Live check (owed):** share a table of several hundred objects well over 20 GiB to a real
  recipient — it completes, the recipient's table queries, and `logs/service=table-share/` shows the
  item count. Then share one deliberately over `SHARE_MAX_TRANSFER_ITEMS` and confirm the refusal
  names the count and cap. Fold in a `GetTable` on the recipient's clone to confirm the 100-column
  definition survived the pointer.

### Phase 5: Completion ritual

- Delivery doc (including the `TimeoutSeconds` arithmetic), INDEX status, `decisions/` entry for
  the pointer-not-state rule extended to the definition, and one Key Decisions line. **No
  `architecture.md` edit** — FR-005's last criterion says why.
