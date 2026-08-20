# Spec: File Operations — Source Expansion, the Copy Plan & the Destination Guard

**ID:** SPEC-188
**Status:** Completed
**Last Updated:** 2026-08-17
**Depends On:** SPEC-187 (the validated request, the authorized roots, the per-item model and its five Premises), SPEC-165 (the expansion and copy-plan precedent), SPEC-090 (copy-plan-as-pointer), SPEC-160/161 (`cpcommon.transfer`), SPEC-170 (the destination guard — its HEAD shape, its concurrency bound and its short-circuit), SPEC-150/172/173 (protected folders)

## Overview

Given a validated request, work out exactly what each selected item will touch and where every
object will land. A selection is a mix of files and folders; folders expand recursively and can hold
thousands of objects, so the expansion happens here — once, in one verb — and the result is written
to S3 as a **plan**, never carried on the Step Functions state.

This spec also builds the **destination guard**: the per-item conflict check that decides which
items may proceed. SPEC-187 settled that a conflict is a per-*selected-item* outcome rather than a
whole-request refusal, and that `overwrite` is bounded by a predicate rather than a carried key set.
This is where both become real.

Nothing is copied or deleted yet. The machine still ends in a placeholder terminal.

## Scope

### In Scope

- **inspect-source**: expand each selected item under the authorized source root, list objects with
  pagination, compute per-item counts and bytes, enforce the expansion caps, and emit a plan pointer.
- The **relative-key rule** and the **one destination builder**, so a folder arrives with its
  structure intact and `targetName` is honoured exactly once.
- **check-destinations**: the per-item conflict guard, including SPEC-187 FR-008's `LastModified`
  predicate for `overwrite`.
- The **exclusion set** during expansion, stated as a closed enumeration — including the two rules
  SPEC-187's Premises fixed and the two the shared listing helper would otherwise decide by default.
- Expansion caps (objects, total bytes, per-object bytes) as **computed** constants.
- Re-checked containment on every key that comes back from `ListObjectsV2`.
- The two new functions' deploy wiring, the execution role's grant on the new admin prefix, and that
  prefix's lifecycle rule.

### Out of Scope

- The transfer, the source deletion, the commit gate and the terminals — SPEC-189. This spec decides
  *what* and *whether*, never *does*.
- **The second guard pass.** SPEC-171 records that the destination guard runs **twice** when hours
  separate the check from the copy. Here they are seconds apart, but SPEC-187 FR-008 AC3 still
  requires a re-check immediately before copying — that is **SPEC-189's**, using this spec's verb
  unchanged, and it is named here so it cannot fall between the two.
- Any UI change or notification beyond SPEC-187's failure path — SPEC-190/191.
- The `delete` operation's destination guard. There is no destination; `delete` skips
  `check-destinations`, and the `Choice` routing past it guards with `IsPresent` (SPEC-143).
- Any change to `cpcommon.transfer`. The manifest this plan feeds is SPEC-189's business.
- Deduplicating identical objects across two overlapping items — refused instead (FR-003).

---

## Functional Requirements

### FR-001: Expansion and listing

#### Acceptance Criteria:

- [ ] A `file` item resolves to exactly that object; a `HEAD`-absent key is a **per-item** failure
      naming the item (`source_missing`), not a whole-request one (SPEC-187 Premise 5).
- [ ] A `folder` item expands recursively through paginated `ListObjectsV2` — never assuming one page
      is the whole folder (the recorded 1,000-key constraint).
- [ ] Each object carries its key **relative to its selected item**, so `reports/2026/q1.csv` under a
      selected `reports/` keeps `2026/q1.csv`.
- [ ] **Every listed key is re-checked for containment** inside the authorized source root. SPEC-187
      FR-005 checked the request; listing is where a key first arrives from **S3** rather than from
      the caller, and the two are not the same assurance.
- [ ] **Each object records its `ETag` and `Size` from the listing.** `ListObjectsV2` returns both in
      `Contents` at zero marginal cost, and this is the **only** verb that lists the source — so it is
      the only cheap producer of the ETag SPEC-187 Premise 3 requires for the conditional delete.
      Without it, SPEC-189 must either re-HEAD every object or change `cpcommon.transfer`, which
      SPEC-187 calls an escalation. (Residual, and it fails safe: an object mutated between expansion
      and copy fails its `IfMatch` and becomes a per-item failure.) **SPEC-189 must confirm
      conditional `DeleteObject` against the live S3 API before relying on it** — the field is cheap
      and also supports a HEAD-compare fallback, but Premise 3 should not rest on an assumed
      capability.
- [ ] An item whose **derived destination equals its source** is a per-item **`noop` success**, and
      **that determination is made once, in validate-authorize** — it is check (1) of SPEC-187 FR-005's
      ordered three-step list, which owns the comparison. Validate-authorize emits the outcome and
      inspect-source **never sees the item**. Inspect-source must not re-derive it: that would be a
      second implementation of a security-adjacent comparison, and expanded, such an item's
      destination subtree *is* its source subtree, so FR-005's guard would report it as conflicted and
      flip a success into a conflict.

### FR-002: The exclusion set, as a closed enumeration

#### Description:

Four rules, two of which the shared listing helper would otherwise decide by default and two of which
SPEC-187 fixed as Premises. Stated as a closed list because every omission here is silent.

#### Acceptance Criteria:

- [ ] **A `DO_NOT_DELETE.txt` found under a folder is EXCLUDED from the plan, never a refusal**
      (SPEC-187 FR-006). `deleteObjects` partitions the root marker out as a per-key error and deletes
      everything else today, and `saved_queries/` ships its own marker — so failing a whole folder on
      a nested marker is a regression the browser never had. A marker the user *selected explicitly*
      was already refused in SPEC-187.
- [ ] **Zero-byte folder placeholders are KEPT** (SPEC-187 Premise 4). `cpcommon.s3_listing.is_ignored`
      — the **default** `ignore` predicate for `list_data_objects` — drops every `size == 0` object, so
      taking the default silently loses them.
- [ ] **Hidden segments are KEPT.** The same default predicate drops any path segment beginning `_` or
      `.`, which would silently drop a user's own `_drafts/` from a move. SPEC-165 recorded exactly
      this trap when it passed a custom `ignore`; this plane needs a custom predicate for the same
      reason and a test asserts the default is not used.
- [ ] **A root-anchored exclusion of `athenaresults/` and `user_settings/` applies during expansion,
      and it is a deliberate SECOND rule rather than a duplicate.** SPEC-187 FR-006 anchors on the
      **selected item's key**; selecting an **ancestor** is not covered — the space root `alice/` is in
      no protected list, passes containment trivially, and has no marker basename, so expansion would
      sweep `alice/user_settings/` (the notification inbox and connections cache) into the plan and a
      `move` would delete it. `fscommon`'s `_PORTAL_MANAGED_FOLDERS` guards precisely this and its
      docstring records why the anchor differs. Different anchor, different question — so the spec
      does **not** claim expansion holds no second copy of the rule.
- [ ] An item that resolves to **zero objects** is a **per-item** failure (`source_empty`). Note this
      differs from `deleteFolder`, which returns success over an empty listing; the change is
      deliberate, because on a plane "nothing happened" must be distinguishable from "it worked".

### FR-003: Item identity, overlaps and duplicates

#### Acceptance Criteria:

- [ ] **Every per-item structure is keyed by the item's SOURCE KEY, never by its leaf name.**
      `targetName` makes leaf names non-unique: `alice/a/reports/` → `r1` and `alice/b/reports/` → `r2`
      derive to different destinations, both survive SPEC-187 FR-005 AC8, and both label as `reports`.
      Keyed by name, the plan holds two groups of one name, the guard's output cannot tell them apart,
      and Premise 2's commit gate acts on their union. file-send avoided this by refusing name
      collisions outright — a rule that cannot apply here, because `targetName` is what makes rename
      expressible. The name travels only as a **display label**.
- [ ] Two selected items where one **contains** the other is a **whole-request** refusal naming both.
      Copying an object twice and silently dropping one are both worse than a clear refusal, and this
      is a property of the request rather than of an item.
- [ ] The same item listed twice is **collapsed**, not refused.
- [ ] A **duplicate is `(kind, key)`, never the key alone** (SPEC-165's recorded defect): a folder key
      normalised to a trailing slash and a file key left untouched mean one key can arrive with two
      kinds, and collapsing on the key alone sent a zero-byte placeholder and none of the folder's
      contents while reporting success.
- [ ] Items whose **derived destination keys** collide were refused in SPEC-187 FR-005; this spec does
      not re-check it.

### FR-004: The destination builder

#### Acceptance Criteria:

- [ ] Every object's destination is built by **one** function taking the item's
      `targetName ?? item_name(key)` and the object's relative key. A test forbids any verb building a
      destination by its own string concatenation — SPEC-165's AST sweep is the precedent, and it must
      exempt docstrings and the declaration **by node identity** (skipping the `Expr` and not its
      `Constant` child flagged two docstrings there).
- [ ] The builder **re-normalises a folder destination to a trailing slash** — `item_name` strips it,
      which is the residue that re-opened SPEC-187's data-loss path during review.
- [ ] The layout is unaffected by source depth: moving `alice/deep/nested/q1.csv` into `alice/out/`
      yields `alice/out/q1.csv`.
- [ ] For `delete`, no destination is built and the plan carries none.

### FR-005: The destination guard

#### Description:

Per selected item, decide whether it may proceed. Runs before anything is copied.

**The collision unit is the derived destination KEY, not the destination subtree.** That is what the
browser does — `moveFolder`/`copyFolder` intersect `sourceKeys.map(destKeyFor)` against the listed
destination — and it is what preserves **merging into an existing folder**: copying `reports/` into
`out/` when `out/reports/notes.txt` exists and no source key maps onto it is legal today and stays
legal. "The destination subtree holds anything" is a different, stricter test that would remove a
shipped capability.

#### Acceptance Criteria:

- [ ] **The verb re-reads the plan from S3.** The derived destination keys exist only in the plan, so
      the guard cannot run off the state; `plan.load`'s `plan_superseded` check applies to this read
      too, not only to `delete-source`'s.
- [ ] The guard checks **each derived destination key** with a `HeadObject`, on SPEC-170's shape — not
      a listing. A listing cannot serve this check: `CommonPrefixes` carries no `LastModified`, `Size`
      or keys, so a delimited listing structurally cannot answer the `overwrite` predicate below the
      first level; and `ListObjectsV2` never returns a per-key 403 — an `AccessDenied` fails the whole
      listing. HEADs are also bounded by **our own** `FILE_OPS_MAX_OBJECTS` rather than by the size of
      someone else's destination folder.
- [ ] Concurrency is **8**, deliberately *below* botocore's default `max_pool_connections` of 10 so
      the verb's other S3 calls are not contending for the last socket — SPEC-170's value, not merely
      its ceiling. The bound is the pool, **not** "workers × timeout ÷ latency": threads past the pool
      contend and urllib3 discards sockets, so a higher number buys throughput the client cannot
      deliver while every bound reads as satisfied. The verb's timeout is sized by a test to pay for
      `FILE_OPS_MAX_OBJECTS` heads at that concurrency.
- [ ] **The ordinary case costs a full sweep too.** Under `refuse` you can only stop early once a
      collision is *found*, so a clean item is always `objectCount` heads — the worst case and the
      common case are the same, and the timeout is sized for that rather than for a hoped-for average.
- [ ] **A 403 counts as occupied** (SPEC-170): a key this role cannot head is one it must not
      overwrite. A HEAD fault that is neither 404 nor 403 **refuses the item** — it never falls
      through to clear.
- [ ] Under `onConflict: 'refuse'`, an item with **any** existing derived destination key is
      conflicted and skipped whole; every non-conflicting item proceeds. It **short-circuits** once
      the bounded sample is full.
- [ ] Under `onConflict: 'overwrite'`, an existing object may be overwritten only when its
      `LastModified` **precedes the request's `submittedAt`** (SPEC-187 FR-008); any existing object
      that is newer conflicts the item. **A 403 conflicts the item under `overwrite` too** — it yields
      no `LastModified`, so it can never satisfy the predicate, and "an existing object" must not be
      read as "the ones we could head". **This mode cannot short-circuit** — a newer object anywhere
      in the item's key set refuses it, so the whole set must be checked. The AC says so, because a
      shared short-circuit would silently make `overwrite` sample-dependent.
- [ ] A conflict names a **bounded sample** of colliding keys relative to the space root and says
      there may be more. The fixture proving the short-circuit must **interleave** its collisions:
      SPEC-170's equivalent test could not fail because its fixture used 64 *consecutive* collisions
      and filled the sample in the first round.
- [ ] The guard is skipped whole for `delete`, and no seeding is needed: FR-006 AC4 has inspect-source
      already emit every expanded item as provisionally `cleared`, so the list is in the right shape
      when the `Choice` routes past this verb. "Every item is implicitly cleared" is therefore a
      stated contract rather than an assumed one.
- [ ] When **every** item conflicts, the run reaches the ordinary terminal reporting each item's
      outcome — not a whole-request failure. Asserted by naming the terminal reached and that each
      item appears with an outcome, never by asserting a branch is absent.

### FR-006: Per-item outcomes

#### Description:

Premise 5 requires per-item outcomes to travel to the terminal. They need a defined vocabulary and a
home on the state, or SPEC-189's collection and SPEC-191's producer each invent one.

#### Acceptance Criteria:

- [ ] The outcome set **defined in SPEC-187 FR-006b is EXTENDED here**, not created — validate-authorize
      is the first producer and ships `focommon/outcomes.py`. This spec adds: `cleared`,
      `conflict`, `noop`, `source_missing`, `source_empty`, and `protected`.
- [ ] **Each entry carries a `reason` alongside its `outcome`.** SPEC-187 FR-006 deliberately gives
      each protected-location refusal a **distinct reason code** so SPEC-191's producer can word it
      without re-deriving the cause; collapsing them all to `outcome: "protected"` throws that away
      and forces the producer to guess which rule fired.
- [ ] **The outcome list is created by validate-authorize and CARRIED FORWARD, never re-created.**
      There are three producers — validate-authorize (protected-location refusals and `noop`),
      inspect-source (`source_missing`, `source_empty`, and every expanded item provisionally
      `cleared`), and check-destinations (`cleared` → `conflict`) — and each **takes the existing list
      as input and returns the complete list**.
- [ ] **A verb's result REPLACES the path it is merged into; it does not append.** Wired naively at
      `$.outcomes`, check-destinations would silently drop validate-authorize's and inspect-source's
      entries — which are exactly the Premise-5 outcomes this FR exists to carry. So
      check-destinations **updates** entries it has decided and returns the rest untouched, and a test
      asserts a run with one refusal, one `source_empty` and one conflict ends with all three present.
- [ ] **Inspect-source emits an entry for EVERY item it expanded**, provisionally `cleared`. Without
      that, FR-005's `delete` branch has nothing to seed from — the expanded item keys live only
      inside the plan, in S3, so a `Pass` state cannot construct the list — and "every item appears
      exactly once" is unsatisfiable.
- [ ] **The outcome list's worst-case size is COMPUTED against the state limit, and the sample size is
      derived from it** — not asserted from the item count. `FILE_OPS_MAX_ITEMS` bounds the number of
      entries but says nothing about bytes: S3 keys reach 1024 bytes and are arbitrary UTF-8, so JSON
      escaping expands `"` to two bytes and a control character to six (SPEC-164 FR-004's rule). The
      test measures the **escaped** worst case through the Pipe's re-escaping and picks the per-item
      sample size to fit; this is the same "bound measured against the wrong quantity" trap the caps
      in FR-007 exist to avoid.

### FR-007: The plan, and the caps that bound it

#### Acceptance Criteria:

- [ ] The plan is written to `{admin_bucket}/file-ops/{requestId}/plan.json`; the verb emits
      `{planKey, itemCount, objectCount, totalBytes}`. The plan never rides on the state (PR #256).
- [ ] The plan body carries **`requestId`, `submittedAt` and `onConflict`** alongside the operation,
      roots and items. Without `requestId`, `plan_superseded` has nothing to compare; and taking
      `submittedAt`/`onConflict` off the state rather than the plan is the very substitution
      `plan_superseded` exists to catch.
- [ ] Each object records `srcBucket`, `srcKey`, `destBucket`, `destKey`, `relKey`, `size` and `etag`
      — enumerated because `cpcommon.transfer`'s copy reads the two bucket names per item, and "what
      the manifest builder needs" is not a testable phrase.
- [ ] `plan.load` proves the plan describes **this** run (`plan_superseded`), and inspect-source
      refuses a prefix that already holds a plan (`request_id_reused`). SPEC-169 records why both
      exist: the request id is browser-supplied and keys the plan, so without them a run can pass its
      own gate over another execution's selection.
- [ ] **Three computed caps**, each naming the schedulable unit it measures (SPEC-161).
      > **Superseded in part by SPEC-189 FR-001:** the byte cap's makespan is re-computed against
      > **two** guard sweeps rather than one — SPEC-189 re-runs this spec's guard immediately before
      > the copy, and SPEC-189 owns that re-computation.
      `FILE_OPS_MAX_OBJECTS` as the **MINIMUM of two budgets** — the plan held in memory against
      inspect-source's configured memory, *and* the guard's head sweep against check-destinations'
      timeout at concurrency 8 (FR-005). Two verbs bound this one number and naming only the memory
      one is how a cap comes to certify something it never checked: if memory permits 200,000 objects
      the guard cannot head them at any concurrency inside Lambda's 900 s ceiling. The test computes
      **both** and asserts which binds; `FILE_OPS_MAX_TOTAL_BYTES` as a **makespan** at a
      conservative per-stream rate, measured against **the machine's `TimeoutSeconds` minus the guard,
      the serial verbs and the deletion**; and `FILE_OPS_MAX_OBJECT_BYTES`, because **one object is
      one worker** — a total-bytes makespan says nothing about the largest single object, which is why
      `SEND_MAX_OBJECT_BYTES` and `ARCHIVE_MAX_OBJECT_BYTES` both exist.
- [ ] A **per-item time bound** on listing: SPEC-165 records that the timeout bound is per-**item**,
      not per-page, because a `file` item costs its own serial `HeadObject` — 200 files is 200 round
      trips where 20,000 objects is 20.
- [ ] **Caps are enforced INSIDE the walk**, not after it. The list accumulates in memory, so a cap
      checked afterwards is one the verb has already paid for — and would OOM before refusing.
- [ ] Exceeding any cap is a **whole-request** failure naming the measured value and the cap; a
      per-item reading would let a request approach the bound by attrition.
- [ ] Every refusal renders through `focommon.messages` on the `cpcommon` `Resolver` — the whole
      sentence, never a fragment (SPEC-156).

### FR-008: Infrastructure for the two new verbs

#### Acceptance Criteria:

- [ ] The execution role is granted `s3:GetObject`/`PutObject` on `{admin_bucket}/file-ops/*` — SPEC-187
      FR-013 ships the role with only logging and the lock prefix, so without this the verb cannot
      write its own plan. Every other plane grants its own prefix explicitly.
- [ ] A **lifecycle rule** expires the `file-ops/` prefix. The rule is prefix-scoped, never broad: the
      analytics module records that a broad prefix would match `logs/`, which is retained forever.
- [ ] Both new functions are in the `Deploy Lambdas` matrix, in `locals.tf` with memory and timeout,
      and covered by `lambdas/test_deploy_matrix.py` — the deploy matrix and what each function
      imports must agree. SPEC-187 FR-001 AC5 covers only its own functions, and this is SPEC-137's
      shape verbatim: `update-function-code` succeeds against a function that cannot import, and every
      offline gate is blind.

---

## Data Model

```python
# {admin_bucket}/file-ops/{requestId}/plan.json
{
  "requestId": "…", "operation": "move", "submittedAt": "2026-08-17T10:00:00Z",
  "onConflict": "refuse", "actor": "alice",
  "source": {"bucket": "dat-prod-user-space", "root": "alice/"},
  "destination": {"bucket": "dat-prod-user-space", "prefix": "alice/out/"},
  # The two items that reached expansion in the scenario below.
  "items": [
    {
      "itemKey": "alice/reports/",            # identity — never the label
      "label": "reports", "targetName": "reports",
      "objects": [
        {"srcBucket": "dat-prod-user-space", "srcKey": "alice/reports/2026/q1.csv",
         "relKey": "2026/q1.csv", "destBucket": "dat-prod-user-space",
         "destKey": "alice/out/reports/2026/q1.csv", "size": 91234, "etag": "\"abc…\""}
      ],
      "objectCount": 1, "totalBytes": 91234
    },
    {
      "itemKey": "alice/logs/", "label": "logs", "targetName": "logs",
      "objects": [
        {"srcBucket": "dat-prod-user-space", "srcKey": "alice/logs/a.txt",
         "relKey": "a.txt", "destBucket": "dat-prod-user-space",
         "destKey": "alice/out/logs/a.txt", "size": 512, "etag": "\"def…\""}
      ],
      "objectCount": 1, "totalBytes": 512
    }
  ],
  "itemCount": 2, "objectCount": 2, "totalBytes": 91746
}

# ONE scenario, followed through all three hops. The user selected four items:
#   alice/old/  (renamed to itself)   alice/athenaresults/  (protected)
#   alice/reports/                    alice/logs/
# The outcome list is created once and carried forward COMPLETE by each verb.

# validate-authorize →
{"outcomes": [{"itemKey": "alice/old/", "label": "old", "outcome": "noop"},
              {"itemKey": "alice/athenaresults/", "label": "athenaresults",
               "outcome": "protected", "reason": "results_folder_not_a_source"}]}

# inspect-source → the same list, plus an entry for EVERY item it expanded
{"planKey": "file-ops/{requestId}/plan.json", "itemCount": 2, "objectCount": 2,
 "totalBytes": 91746,
 "outcomes": [{"itemKey": "alice/old/", "label": "old", "outcome": "noop"},
              {"itemKey": "alice/athenaresults/", "label": "athenaresults",
               "outcome": "protected", "reason": "results_folder_not_a_source"},
              {"itemKey": "alice/reports/", "label": "reports", "outcome": "cleared"},
              {"itemKey": "alice/logs/", "label": "logs", "outcome": "cleared"}]}

# check-destinations → the same list again, UPDATING only what it decided
{"outcomes": [{"itemKey": "alice/old/", "label": "old", "outcome": "noop"},
              {"itemKey": "alice/athenaresults/", "label": "athenaresults",
               "outcome": "protected", "reason": "results_folder_not_a_source"},
              {"itemKey": "alice/reports/", "label": "reports", "outcome": "cleared"},
              {"itemKey": "alice/logs/", "label": "logs", "outcome": "conflict",
               "reason": "destination_occupied",
               "sample": ["out/logs/a.txt"], "more": true}]}
```

```python
# focommon.paths
destination_key(dest_prefix, target_name, rel_key, *, is_folder) -> str   # the ONE builder
```

## File & Folder Structure

```
lambdas/
├── file-ops-inspect-source/
│   ├── inspect_source.py
│   └── test_inspect_source.py
├── file-ops-check-destinations/
│   ├── check_destinations.py
│   └── test_check_destinations.py
└── file-ops-common/focommon/
    ├── config.py      # the three caps + the per-item time bound
    ├── outcomes.py    # FR-006's closed vocabulary
    ├── paths.py       # destination_key
    └── plan.py        # write / load / plan_superseded

infra/modules/file-ops/
├── iam.tf             # + the file-ops/ admin-prefix grant
├── lambda.tf          # + the two new functions
└── locals.tf          # + memory/timeout the caps are computed against
```

## Implementation Phases

### Phase 1: Expansion, exclusions and containment

- Item resolution, paginated listing, per-item grouping keyed by source key, ETag capture, the
  re-checked containment, the closed exclusion enumeration (including the custom `ignore` predicate),
  and the same-key `noop` removal.

### Phase 2: The destination builder and the overlap rules

- `focommon.paths.destination_key` with its folder re-normalisation, the AST sweep, and the overlap /
  `(kind, key)` duplicate rules.

### Phase 3: The destination guard

- The bounded-concurrency HEAD sweep, 403-is-occupied, the fault-refuses-the-item rule, the
  `LastModified` predicate and its no-short-circuit rule, the interleaved-collision fixture, and the
  seeded `delete` branch.

### Phase 4: Outcomes, caps, the plan and the infra

- FR-006's vocabulary; the three computed caps and the per-item time bound, enforced inside the walk;
  `plan_superseded` / `request_id_reused`; the plan write; the admin-prefix grant and lifecycle rule;
  the deploy matrix and `locals.tf` entries; the `IsPresent`-guarded `Choice` routing `delete` past
  the guard.

### Phase 5: Verification

- Fixtures: nested folders; a folder of 2,500 objects (pagination); an overlapping selection; a
  `(kind, key)` duplicate; a nested marker; a `_drafts/` folder surviving; an empty subfolder
  surviving; two items sharing a leaf name with different `targetName`s; a 403 destination; a merge
  into an existing folder that must **not** conflict; an `overwrite` whose destination object is
  newer than `submittedAt`; and a conflict sample whose collisions **interleave**.
- **Live check (owed):** one request whose source folder holds more than 1,000 objects, confirming the
  plan's `objectCount` matches the bucket — the pagination boundary is what a fixture proves least
  (SPEC-165's owed check, same reason).

### Phase 6: Completion ritual

- Delivery doc, INDEX status, component-inventory rows for `focommon.paths`/`config`/`outcomes`, and
  the plan layout in the `architecture.md` *Control Planes* section. The **per-item conflict model**
  and the **key-level collision unit that preserves merging** each get a `decisions.md` entry — they
  are what separate this plane from every other one, all of which refuse whole-request.
