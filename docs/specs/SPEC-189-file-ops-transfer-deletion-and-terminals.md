# Spec: File Operations — the Transfer, the Source Deletion & the Terminals

**ID:** SPEC-189
**Status:** Draft
**Last Updated:** 2026-08-17
**Depends On:** SPEC-188 (the plan, its ETags, the guard verb and the per-item outcome list), SPEC-187 (the per-item model and Premises 1–3), SPEC-160/161 (`cpcommon.transfer`), SPEC-166 (the Distributed-Map transfer precedent), SPEC-169 (the commit gate and the delete-Deny set), SPEC-171 (the second guard pass)

## Overview

Everything up to here decides *what* moves and *whether*; this spec moves it. The shape is the one
SPEC-160 established and SPEC-166 reused: a manifest is written to the admin bucket, a **top-level
Distributed Map** copies it in bounded parallel batches, and a collector attributes failures back.
What is different — and it is the whole spec — is that **every gate is per selected item**, because
SPEC-187 chose per-item partial execution over whole-request refusal.

That choice has a cost this spec must pay honestly, in two places. The transfer engine's attribution
vocabulary is hardcoded to table-share's `recipient`, so **the engine must be generalised** (FR-002)
— an escalation SPEC-187 requires be made explicitly rather than smuggled in. And Step Functions has
no per-item `Choice` over a list, so **the commit gate cannot be the graph-level guarantee SPEC-169
built** (FR-005); this spec states the weaker property it can actually assert, rather than inheriting
a sentence that no longer holds.

After this spec a file operation actually happens. It is still silent until SPEC-191.

## Scope

### In Scope

- **Generalising `cpcommon.transfer`'s attribution key** — an escalation, scoped and budgeted here.
- **The second guard pass** — SPEC-188's `check-destinations` re-run before the copy, narrowing only.
- **build-transfer-manifest**, **copy-objects** (the batch verb), **collect-transfer-results**,
  **delete-source** — four verbs, with their `locals.tf` sizing and deploy-matrix rows.
- The **Distributed Map** transfer state.
- **The per-item commit gate** and the source deletion it guards.
- The `delete` operation's own path.
- **Execution-role IAM, grants-first**, with SPEC-169's Deny set.
- Terminal states carrying everything SPEC-191 needs.
- Extending SPEC-188's outcome vocabulary with the terminal and failure codes this spec produces.

### Out of Scope

- Notifications and UI — SPEC-190/191. This spec's terminals are data, not messages.
- Rolling back a partial copy. FR-006 — for `move` the source survives, which is the safe direction;
  `copy` is additive by nature.
- Resuming or redriving a failed Map Run.
- `CopySourceIfMatch` on the copy itself. See FR-006 AC8's residual; it is a named tightening, not a
  gap.

---

## Functional Requirements

### FR-000: Where the states go

#### Acceptance Criteria:

- [ ] **This spec draws the composed machine**, which no earlier spec owns: guard-pass-2 runs **after**
      `build-transfer-manifest` is skipped for it and **before** the manifest is written, so a newly
      conflicted item never contributes lines; `ReleaseLock` runs **before** the notification producer,
      so the space is not held while messages are written; and the `Wait` → re-acquire loop's shape is
      fixed.
- [ ] SPEC-187 FR-009's release-on-every-terminal graph walk and the SPEC-152 fleet test are **re-run
      against this shape** — and SPEC-191, which adds one more state, re-runs them again.

### FR-001: The second guard pass

#### Acceptance Criteria:

- [ ] `check-destinations` runs a **second time** immediately before the transfer — the **same verb**,
      not a second implementation (SPEC-187 FR-008 AC3, SPEC-171's recorded rule that a guard
      separated from its copy has expired).
- [ ] **It evaluates only items currently `cleared`, and it may NARROW, never widen.** An item the
      first pass conflicted is not re-headed and cannot be resurrected — the colliding object may have
      been deleted in between, and file-send's collector states the governing rule: an earlier
      terminal is never overwritten.
- [ ] An item cleared by the first pass and conflicted by the second becomes `conflict` with a
      **distinct reason code** from the first pass's. Both codes are named in `focommon.messages`,
      because "the guard has not run" and "the guard ran and found nothing" are indistinguishable
      inside a handler (SPEC-171), and the ASL seeds which pass it is.
- [ ] **SPEC-188 FR-007's makespan is re-computed against TWO guard sweeps, and SPEC-189 owns that
      re-computation** — a superseded marker goes on SPEC-188 FR-007 pointing here, on the pattern
      used for SPEC-187's Premise 1. It was sized against
      "the ceiling minus the guard" — singular — and SPEC-188 FR-005 records that the ordinary case
      costs a *full* sweep, so the second pass is not a rounding error.
- [ ] Skipped whole for `delete`, by the same `IsPresent`-guarded `Choice` as the first pass.

### FR-002: Generalising the transfer engine's attribution key

#### Description:

An **escalation**, stated as its own FR because SPEC-187 requires that a change to `cpcommon.transfer`
be exactly that rather than a silent edit.

`copy_batch` builds its failure records as `{recipient, kind, reason}`, and `_from_input` does the
same for the `FAILED`/`PENDING` half. Both are hardcoded to table-share's vocabulary. This plane
attributes to a **selected item**, and there is no field to carry it: an `itemKey` placed on a
manifest line rides into the child input and is dropped on the way out.

#### Acceptance Criteria:

- [ ] The engine takes a **caller-supplied set of fields to echo** onto failure records, replacing the
      hardcoded `recipient`/`kind`, in **both** `copy_batch` and `_from_input`.
- [ ] The three existing callers pass the fields they use today; a test asserts their records are
      **byte-identical** to before — with one **named exception**: archive's manifest carries no
      `recipient`/`kind`, so `copy_batch` emits `{"recipient": null, "kind": null, …}` for every
      archive failure today. Archive passes the **empty** field set and those two nulls disappear.
      That is a deliberate change, named here so the test going red is expected rather than alarming. Byte-identity is measured by rendering both, not argued
      (SPEC-156's precedent).
- [ ] `test_a_worst_case_batch_stays_under_the_input_limit` is **re-run against the new field set**: a
      1024-byte `itemKey` on each of `MAX_ITEMS_PER_BATCH` items grows the batch payload the bound was
      computed against.
- [ ] The echoed fields stay **bounded** — no key list, no unbounded term. The engine's own rule is
      that failures name the recipient and never the key, because the list rides the exported result
      and then the state.

### FR-003: Manifest and transfer

#### Acceptance Criteria:

- [ ] `build-transfer-manifest` writes JSONL to
      `{admin_bucket}/file-ops/{requestId}/{executionName}/transfer-manifest.jsonl` — **execution-unique
      where the plan deliberately is not.** `requestId` is browser-supplied and is exactly what
      SPEC-188's `request_id_reused` guards; the key is built by one `focommon.plan` function taking
      the execution name, on `arcommon.plan.transfer_manifest_key`'s signature.
- [ ] One line per object of every **`cleared`** item, each carrying the `destKey` the plan already
      computed, the item's `itemKey` (FR-002's echoed field) **and the object's `size`**. The builder
      does not build keys.
- [ ] **`size` is not optional.** `copy_batch` reads `item.get("size") or 0` and selects the single
      `CopyObject` path below `MULTIPART_COPY_THRESHOLD` — so an absent size means **every** object
      takes the single-copy path and anything over 5 GiB returns `InvalidRequest`. Both existing
      manifest builders carry it. The multipart path also carries content type through the metadata
      round trip SPEC-171 added to the engine.
- [ ] Items with any other outcome contribute **zero** lines.
- [ ] The Distributed Map is declared at the **top level** — a test asserts the rendered ASL nests no
      Distributed Map inside another `Map`.
- [ ] **The ASL declares the Map inline and its numbers come from `locals.tf`**; `cpcommon.transfer.config`
      holds four Python constants and a test asserts the rendered numbers still equal them. Terraform
      cannot import Python — an AC claiming the reader, batcher, processor mode and `ResultWriter` come
      "from `config.py`" describes a module that does not contain them.
- [ ] The `ResultWriter` destination is a named key layout in `focommon.plan`, not an inline literal.
- [ ] With zero manifest lines the Map is skipped by a `Choice` guarded with **`IsPresent` before the
      numeric test** (SPEC-143).
- [ ] The Map's `states:` and S3 grants belong to the **state-machine role**, not the execution role —
      on the execution role this renders, applies and unit-tests green, then `AccessDenied`s at the
      `ItemReader` (SPEC-160).

### FR-004: Attribution

#### Acceptance Criteria:

- [ ] **The verb re-reads the plan from S3** — the per-item planned object counts it needs to decide
      "every object confirmed copied" live only there.
- [ ] `collect-transfer-results` reads **`SUCCEEDED_n` as well as `FAILED_n`/`PENDING_n`**. A
      deterministic item failure **succeeds** its batch under `ToleratedFailurePercentage: 100`, so a
      FAILED-only collector reports universal success over an incomplete dataset (SPEC-160).
- [ ] Every manifest line is accounted for. An **omitted** line is unattributable and is a
      **whole-request** failure — a property of the run, not of an item.
- [ ] Attribution is by the echoed `itemKey`, producing a per-item **failure count**. Successes are a
      batch-level integer in the engine and are derived by subtraction, never as a key list: keys are
      the unbounded term, and a failed-key list on the state breaches the 256 KB limit **on the Map**,
      destroying every per-item outcome it exists to preserve.
- [ ] The outcome list is **carried forward and updated**, never re-created (SPEC-188 FR-006).

### FR-005: The commit gate — and the property it can actually assert

#### Description:

SPEC-169's gate is one boolean over the whole run, and its guarantee is graph-level: the rollback arm
**cannot reach** `DeleteSource`. A per-item plane produces runs that are simultaneously committing and
non-committing, and **Step Functions has no per-item `Choice` over a list** — so that guarantee is not
available here. This FR states the weaker one honestly rather than inheriting a sentence that no
longer holds.

#### Acceptance Criteria:

- [ ] `collect-transfer-results` emits **`deletable: [itemKey, …]`**. One `Choice` gates on that list
      being **non-empty**.
- [ ] **The membership rule is per operation.** For `copy`/`move` an item is `deletable` when every one
      of its objects is confirmed copied. For **`delete` there is nothing to confirm** — the guard is
      skipped and the Map is skipped at zero lines — so `collect-transfer-results` is reached on the
      **skip branch** (file-send's ASL does exactly this) and emits every still-`cleared` item as
      `deletable`. Without this the `delete` operation reaches the fail-closed `Default` and deletes
      nothing, which is the whole operation silently not working.
- [ ] The ASL graph walk asserts exactly one property: **an empty `deletable` set cannot reach
      `DeleteSource`.** It does **not** assert the per-item property, and the spec says so — a walk
      claiming more than it proves is worse than one claiming less.
- [ ] The **per-item property is a collector unit test with a named mutation**: an item with one
      failed object must not appear in `deletable`, and the test fails if that filter is removed.
- [ ] The `Choice`'s `Default` is the non-committing arm, so an unrecognisable verdict **fails closed**.
- [ ] Two shortfalls keep an item out of `deletable`: an item failure, or a manifest disagreeing with
      the plan. A **global** export shortfall is FR-004 AC2's whole-request failure and subsumes the
      per-item case — per-item *coverage* is a success-side quantity the engine does not report
      (successes are a per-batch integer), so an AC describing it sends a builder after something
      uncomputable.
- [ ] `copy` never reaches `DeleteSource`, by an `IsPresent`-guarded `Choice` on `operation` — this
      one **is** a whole-request property and a graph walk does prove it.

### FR-006: The source deletion

#### Acceptance Criteria:

- [ ] `delete-source` **re-reads the plan from S3** and deletes the plan's keys for the items in
      `deletable`. **No key ever rides the state.**
      *This is what SPEC-187 Premise 1 means and the Premise is amended to say so:* it forbids a
      **prefix listing**, which would delete an object written into the folder after expansion that
      was never copied. It does **not** forbid a plan re-read — and per-item gating makes "the plan
      keys of a fully-succeeded item" and "the keys confirmed copied" the *same set*.
      `archive-delete-source` is the precedent — what it deletes is exactly the plan.
- [ ] **`delete-source` asserts `set(items it deletes) is a subset of set(deletable)` and raises
      otherwise**, with a named mutation test. This is the compensating guard for FR-005's weakened
      graph property: SPEC-169's walk stayed red if a later `Catch` reconnected the arms, where a
      collector unit test protects the filter and nothing else. Two guards at two layers is the honest
      replacement for one graph property. An `itemKey` in `deletable` matching no plan item deletes
      **nothing** for that item and is recorded — it never falls through.
- [ ] **Conditional `DeleteObject` is CONFIRMED against the live API before anything depends on it**
      (SPEC-188 FR-001's instruction). If it is unavailable on these buckets, the named fallback is a
      **HEAD-compare immediately before the delete** — weaker (a race remains) and slower, but it
      keeps Premise 3 buildable. The fallback has an owner here rather than being discovered at the
      end of the arc.
- [ ] Each delete is **conditional on the ETag the PLAN recorded** — `if-match`, supported on
      `DeleteObject` since 2025-09-16 and on `DeleteObjects` via a per-object `ETag` on
      `ObjectIdentifier` for general-purpose buckets.
- [ ] **The batch path does not return 412.** `DeleteObjects` answers **HTTP 200** with the object in
      an `Error` element; AWS does not document the `Code` string, and it must be distinguished from
      `AccessDenied` — one is `source_changed`, the other is `protected`. Phase 5 probes it live,
      because it cannot be got from the docs.
- [ ] **409 is handled distinctly from 412.** AWS documents a 409 on concurrent delete/put, which is
      not a precondition mismatch — the same twin SPEC-187 FR-009 records for the lock's CAS.
- [ ] A precondition mismatch is a **per-item failure** with its own outcome, never a silent skip: it
      means the source changed after the copy, so the destination holds stale bytes.
- [ ] **The `delete` operation's own deletions are UNCONDITIONAL, deliberately.** A `move`'s
      conditional delete protects bytes that were copied; a `delete` has no copy, and an object
      modified since expansion is still one the user asked to delete. An object *added* after
      expansion is not in the plan and survives — the same orphan rule.
- [ ] **`assert_deletable` is scoped PER ITEM**, not over the whole list. An item containing a denied
      key fails alone with a distinct reason; every other item's deletion proceeds. A whole-list
      refusal would be the whole-request reversion this arc's model forbids — and for `move` it runs
      *after* the copy, so it would leave every item copied and nothing deleted: a full duplicate.
      Keep the defence-in-depth framing; change the unit.
- [ ] `DeleteObjects` returns **HTTP 200 with a per-item `Errors` array**; a partial failure is read
      and raised, never treated as success (SPEC-151).
- [ ] **ETag epoch, stated once:** the condition uses the **plan's** ETag. The copy is issued
      unconditioned, so an object mutated between expansion and copy copies the *new* bytes and then
      mismatches the *stale* plan ETag — a per-item failure whose destination is in fact correct.
      SPEC-188 accepts this residual; `CopySourceIfMatch` is the named tightening if the false failure
      proves annoying in practice.

### FR-007: Execution-role IAM, grants-first

#### Acceptance Criteria:

- [ ] The role gains `GetObject`/`PutObject` on both data buckets and `DeleteObject` — plus an
      **explicit Deny** on `DeleteObject` under `athenaresults/`, `user_settings/`, `archive/` and any
      `*/DO_NOT_DELETE.txt` (SPEC-169's set).
- [ ] The Deny mirrors **each bucket's own shape** rather than averaging them (SPEC-172/188's rule).
- [ ] The IAM simulation runs against the **deployed** role, with **every denial paired with an
      `allowed` control** — an `implicitDeny` alone cannot distinguish an ungranted action from a
      wrong resource ARN (SPEC-149/157).
- [ ] A test asserts the rendered policy carries no `Resource: "*"` (SPEC-139).
- [ ] **The `s3:if-match` bucket-policy enforcement is DECLINED, and the reason is recorded.** The
      documented pattern (`"Null": {"s3:if-match": "false"}`) denies any delete lacking the header —
      which would 403 every `delete`-operation deletion, since FR-006 makes those deliberately
      unconditional. A bucket-wide condition cannot express two delete paths with different
      conditionality. Note also the dependency AWS records: a *valued* conditional delete requires
      **both `s3:DeleteObject` and `s3:GetObject`**, so a later tightening of `GetObject` would
      silently break every conditional delete.

### FR-008: Terminals and the outcome vocabulary

#### Acceptance Criteria:

- [ ] **The vocabulary is extended with terminal successes and this spec's failures**, because
      SPEC-188's set is all *gate verdicts*: `moved` / `copied` / `deleted` as terminal successes,
      plus `copy_failed` and **`duplicate`**. Following SPEC-188 FR-006's outcome/reason split,
      `source_changed` (the precondition mismatch) and `source_delete_failed` are **reasons** on the
      `duplicate` outcome, not outcomes of their own — one state, one code.
- [ ] **A dedicated `finalise-outcomes` step assigns the terminal successes**, because no existing
      verb can: `delete-source` does not run on a `copy` (FR-005 proves no path), so without this every
      successful item on a copy run arrives labelled `cleared` and the AC below fails by construction.
      It maps `cleared` → `moved` / `copied` / `deleted` by `operation`, for items that committed.
- [ ] **A gate verdict may never reach a terminal.** `cleared` means "may proceed"; an item that ends
      a run still labelled `cleared` is a defect, because SPEC-191's producer cannot tell it from
      "moved successfully". Asserted by a test over every terminal.
- [ ] An item copied but whose source was not deleted (a per-item `assert_deletable` refusal, or a
      precondition mismatch) is reported as a **duplicate** — a state no existing code describes and
      the user must be told about, since they now have the data in two places.
- [ ] Every terminal carries the **complete** per-item outcome list, plus **the `operation`, BOTH the
      source and destination spaces (kind + name) and the destination prefix, each item's `targetName`
      and `kind`, and per-item counts**. The full set is what SPEC-190 FR-005's re-submit must rebuild
      into a valid request: the source space is **not** derivable from an absolute key, and a rename's
      `targetName` has no other source. — everything SPEC-191 needs to build
      its link and word its message, so the producer reads no second source.
- [ ] A run in which **every** item was skipped or refused still reaches the ordinary terminal.
- [ ] **A whole-request terminal is reachable only from a cause that is a property of the REQUEST,
      never of an item.** Stated as the rule rather than as a list — the causes are spread across
      SPEC-187 (containment, the lock give-up) and SPEC-188 (overlapping items, `plan_superseded`,
      `request_id_reused`, every cap) as well as this spec, and an enumeration is wrong on day one.
- [ ] The lock is released on every terminal (SPEC-187 FR-009), and that graph walk is re-run against
      this spec's expanded machine.

---

## Data Model

```python
# {admin_bucket}/file-ops/{requestId}/{executionName}/transfer-manifest.jsonl
{"itemKey": "alice/reports/", "srcBucket": "…", "srcKey": "alice/reports/q1.csv",
 "destBucket": "…", "destKey": "alice/out/reports/q1.csv", "size": 91234}

# collect-transfer-results output (state) — counts, never keys
{"deletable": ["alice/reports/"],
 "items": [{"itemKey": "alice/reports/", "objects": 120, "failed": 0},
           {"itemKey": "alice/logs/",    "objects": 5,   "failed": 2}],
 "outcomes": [ ... the complete list, updated ... ]}
```

## File & Folder Structure

```
lambdas/
├── file-ops-build-transfer-manifest/
├── file-ops-copy-objects/          # the batch verb every plane ships
├── file-ops-collect-transfer-results/
├── file-ops-delete-source/
└── file-ops-common/focommon/
    ├── outcomes.py                 # + FR-008's terminal and failure codes
    └── plan.py                     # + transfer_manifest_key(request, execution_name)
                                    # + the ResultWriter key layout
```

All four verbs need `locals.tf` memory/timeout and a `lambdas/test_deploy_matrix.py` row — the deploy
matrix and what each function imports must agree (SPEC-137's shape: `update-function-code` succeeds
against a function that cannot import, and every offline gate is blind).

## Implementation Phases

### Phase 0: The ceiling and the lock constants

SPEC-187 ships `TimeoutSeconds` provisionally because its machine does no work. This spec knows the
makespan, so it re-derives the ceiling, `STALE_LOCK_SECONDS` and the give-up bound **together**, and
re-asserts SPEC-187 FR-009's two inequalities and FR-001's joint budget against the final value.

### Phase 1: The engine escalation

- FR-002 in `cpcommon.transfer`, the three existing callers' byte-identity tests, and the re-run batch
  payload bound.

### Phase 2: The second pass, the manifest and the Map

- The narrowing-only second pass with its own reason codes; the execution-unique manifest key; the
  top-level Map with its numbers from `locals.tf`; the state-machine-role grants.

### Phase 3: Attribution, the gate and the deletion

- The both-halves collector and `deletable`; the non-emptiness `Choice` with its graph walk and the
  collector unit test carrying the per-item property; the plan re-read; conditional deletion with
  409/412 handling; per-item `assert_deletable`; the `delete` path.

### Phase 4: IAM and the vocabulary

- Grants-first with the Deny set and the paired-control simulation; the declined `s3:if-match`
  decision; FR-008's outcome codes and the no-gate-verdict-at-a-terminal test.

### Phase 5: Verification

- Fixtures: an item wholly copied; an item partly copied (source survives, no `deletable` entry); an
  omitted manifest line (whole-request); a precondition mismatch; a `DeleteObjects` partial `Errors`
  array; a per-item `assert_deletable` refusal leaving siblings deleted; a run where every item is
  skipped; a `copy` proving no path to a deleting state.
- **Live checks (owed):**
  1. A real `move` of a folder over 1,000 objects — source deletion complete and conditional.
  2. **A probe for the batch path's precondition-mismatch `Code` string**, which AWS does not
     document and a builder cannot get from the docs.
  3. A `move` whose source object is **modified between copy and delete**, confirming the mismatch
     surfaces as a per-item failure reported as a **duplicate**, not a silent skip.
  4. A `delete` of a folder containing a nested `DO_NOT_DELETE.txt` — the marker survives and **the
     rest goes**, which is only true because `assert_deletable` is per item.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, component-inventory rows. (The `architecture.md` *Control Planes*
  section for the finished plane belongs to **SPEC-191**, the arc closer, not here.) `decisions.md` entries for the **engine attribution generalisation**, the **per-item commit
  gate and the weaker graph property it can assert**, and the **conditional source deletion** — all
  three diverge from SPEC-160/169 and must be findable from them.
