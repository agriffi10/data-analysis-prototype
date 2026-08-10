# Spec: Restore — Request Contract, Archive Lookup & the Destination Guard

**ID:** SPEC-170
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-168 (the plane, the bucket, the `mode` branch, `arcommon`), SPEC-169 (the archive key layout and the receipt)

## Overview

An archive is only worth having if it comes back. The user pastes the UUID from a receipt, and this
spec answers the three questions that have to be settled before a single byte of Glacier retrieval is
paid for: **does that archive exist and belong to this space, what would be written back and where,
and is anything already sitting there.**

The last question is the one the feature was asked for explicitly. S3 has no move and no rename; a
restore is a copy, and a copy overwrites. If the user has re-created `reports/q1.csv` since archiving
it, restoring on top would destroy the newer file silently. So the guard is absolute: **any**
collision refuses the whole restore and tells the user what to clear. Nothing is partially restored
around an obstacle.

The lookup deliberately does not read the manifest to find out what to restore. The archived key
carries its own origin, so `ListObjectsV2` over `personal/alice/archive/{uuid}/` yields both the objects and
their destinations with no record required — the manifest is consulted only as a cross-check, which
means a restore still works when the manifest is missing and refuses when it disagrees.

## Scope

### In Scope

- The **restore request contract** — `mode: "restore"` on the plane SPEC-168 built — and its FIFO
  group and dedup rules.
- **validate-authorize-restore**: verify the ID token, authorize the target space, and validate the
  pasted UUID **before** it is used to build a key.
- **inspect-archive**: list the archive prefix, derive every destination key, cross-check against
  `_manifest.json` when present.
- **check-destination-clear**: the absolute collision guard and its refusal.
- The refusal wording, the bounded sample of colliding keys it names, and the terminal states for
  every refusal path.
- Execution-role IAM for reading the archive bucket and heading the destination.

### Out of Scope

- `RestoreObject`, the wait loop, the copy-back, the archive cleanup and the receipt update —
  SPEC-171. This spec ends at a placeholder terminal immediately after the guard passes, which is
  deliberate: everything here is verifiable in seconds, while everything in SPEC-171 takes hours.
- Any UI, and the notification producer — SPEC-172. The refusal *reasons* are specified here; the
  notification that carries them is built there.
- Restoring to anywhere other than the original path. The receipt records one origin and the restore
  honours it; a "restore to a different folder" flow is a different feature.
- Restoring a subset of an archive. An archive is restored whole or not at all.
- Browsing or searching archives. The user finds the UUID from the receipt folder in their own space;
  there is no archive index and no listing of the archive bucket from the browser.

---

## Functional Requirements

### FR-001: The restore request contract

#### Acceptance Criteria:

- [ ] The message carries `requestId`, `mode` (`"restore"`), `actor.idToken`, `space` (kind + name)
      and `archiveId` — the UUID the user pasted. Unknown top-level fields are rejected, not ignored.
- [ ] `requestId` and `archiveId` are **different values**. `requestId` identifies this restore run;
      `archiveId` identifies the archive being restored. Conflating them was the obvious shortcut and
      is wrong: a refused restore must be re-submittable, and a second attempt at the same archive is
      a new request.
- [ ] `MessageGroupId` is the **SHA-256 hex digest** of `{archiveBucket}/{archiveRoot}` — keyed on
      the *archive*, not the space, so two restores of the same archive serialize while restores of
      different archives in one space proceed in parallel. This is the field's one job here: without
      it, a double-submitted restore could pass the guard twice before either copy lands.
- [ ] `MessageDeduplicationId` is `requestId`.
- [ ] **The space comes from the request, not from the archive.** The route the user is standing in
      names the space, exactly as the data-quality report view takes its space from the route rather
      than deriving it (SPEC-113). Authorization is then a question about *that* space, and an
      archive belonging to a different one simply is not found.
- [ ] A malformed or unparseable body fails before any AWS call and reaches `NotifyFailure`.

### FR-002: Actor identity, space authorization and the pasted UUID

#### Description:

The UUID is the only piece of this request that is both attacker-controlled and used to build an S3
key. It is validated as a UUID before it is concatenated, not sanitised afterwards.

#### Acceptance Criteria:

- [ ] The ID token is verified through the single `cpcommon` JWKS path (SPEC-156); `username` comes
      from the verified claim and nowhere else.
- [ ] A `personal` space is authorized only when its name equals the verified username; a `shared`
      space only when the verified username is an **active** member. Any active member may restore,
      matching SPEC-168's archive rule and the space's existing write model.
- [ ] `archiveId` is matched against a **strict UUID pattern** in `arcommon.paths` and rejected
      otherwise, **before** any key is built from it. A value containing `/`, `..`, a percent escape,
      or a trailing space is refused as malformed, not normalised — the same discipline SPEC-151
      applied to DDL literals, where a raw interpolation of a user-supplied string was the defect.
- [ ] A test enumerates the rejection cases explicitly: `../`, a bare `.`, an embedded `/`, an empty
      string, a UUID with surrounding whitespace, and a 36-character string that is not a UUID.
- [ ] The archive root is built **only** by `arcommon.paths.archive_root(kind, name, archiveId)` —
      the same function SPEC-168 used to write it. One builder, so the read and the write cannot
      drift.

### FR-003: Archive lookup

#### Acceptance Criteria:

- [ ] `inspect-archive` lists `{archiveRoot}` with full pagination and derives, for each object, its
      destination as `{spaceRoot}{relKey}` where `relKey` is the archived key minus the archive root
      — `arcommon.paths.origin_key`, the exact inverse of the writer.
- [ ] `_manifest.json` is **excluded** from the restored object set. A test asserts it is never
      assigned a destination, because a restored `_manifest.json` would land in the user's space as a
      stray file.
- [ ] An empty listing is the terminal failure `archive_not_found`. The message says the archive id
      was not found **in this space** and does not distinguish "never existed" from "belongs to
      someone else" — the same no-existence-oracle rule the data-quality report view follows.
- [ ] When `_manifest.json` is present, its `objectCount` is compared against the listing. A
      disagreement is the terminal failure `archive_incomplete`, naming both numbers. This can only
      fire when something is already wrong, which is the point of an integrity check.
- [ ] When `_manifest.json` is **absent**, the restore proceeds on the listing alone and records that
      it did so in the structured log. The manifest is not load-bearing (SPEC-169 FR-006), and a
      restore that refuses for want of a convenience record would be the failure mode the
      self-describing key layout exists to prevent.
- [ ] The derived object set is written to `{admin_bucket}/archive/{requestId}/restore-plan.json` and
      passed onward as an **S3 pointer, never inline** — the 256 KB state cap, whose overflow escapes
      every `Catch`.
- [ ] The plan carries each object's size, so SPEC-172's notification can tell the user how much is
      coming back and SPEC-171 can bound its wait.

### FR-004: The destination guard

#### Description:

The rule the user asked for: if a key exists where the archived data used to be, the restore is
denied and the user is told to clear it.

#### Acceptance Criteria:

- [ ] Every destination key in the plan is checked for existence. **Any** occupied key refuses the
      whole request with the terminal failure `destination_occupied`. There is no skip, no overwrite,
      no merge and no "restore what fits".
- [ ] Existence is established by `HeadObject` per key, tolerating `404` as absent and treating a
      `403` as **occupied** — a key the execution role cannot head is a key it must not overwrite.
      Both branches have a test.
- [ ] The check is batched with a bounded worker pool and **short-circuits on the first collision**;
      an archive of 200,000 objects must not issue 200,000 heads to report a conflict found in the
      first hundred.
- [ ] Because it short-circuits, the failure names a **bounded sample** of colliding keys — at most
      `RESTORE_CONFLICT_SAMPLE` of them — and states plainly that there may be more. A message
      implying the sample is exhaustive would send the user round the loop repeatedly.
- [ ] The sampled keys are rendered **relative to the space root**, not as full `s3://` URIs, so the
      user reads a path they recognise from the file browser.
- [ ] A folder placeholder object at a destination counts as a collision like any other key.
- [ ] The guard runs **before** any `RestoreObject` call. Glacier retrieval is billed and irreversible
      once initiated; discovering the conflict afterwards would charge the user for a restore that
      cannot land. A test asserts there is no ASL path from the guard's failure branch to any
      retrieval state.
- [ ] A restore whose destinations are all clear reaches the placeholder terminal, and the run
      appears in `logs/service=archive/` with the object count and total bytes.

### FR-005: Refusal wording

#### Description:

Three refusals reach the user, and each one has to tell them what to do next. SPEC-172 builds the
notification; the vocabulary is fixed here so that the two specs cannot disagree.

#### Acceptance Criteria:

- [ ] `archive_not_found` — names the archive id and the space, and points the user at the `archive/`
      folder where receipts live.
- [ ] `archive_incomplete` — names the expected and found object counts and says the archive should
      not be restored.
- [ ] `destination_occupied` — names the sample, says there may be more, and states the required
      action: clear or rename the listed paths, then request the restore again.
- [ ] All three go through `arcommon.messages` on `cpcommon`'s `Resolver`, which renders the **whole
      sentence** (SPEC-156) — no verb assembles wording from fragments, and no raw AWS text reaches
      the user (SPEC-106).
- [ ] Each has its own dedup token per **outcome**, not per verb, matching the data-quality
      notification rule.

### FR-006: Execution-role IAM

#### Acceptance Criteria:

- [ ] The role's additions for this spec are `s3:ListBucket` and `s3:GetObject` on the archive bucket
      (already present from SPEC-169 FR-007) and `s3:GetObject` on the two space buckets for the
      `HeadObject` guard — `HeadObject` is authorized as `s3:GetObject`, which is the trap here: a
      role granted only `ListBucket` reads every destination as absent and the guard silently passes.
- [ ] A test asserts the guard's permission is `s3:GetObject` and not `s3:ListBucket`, with the reason
      recorded, because the failure mode is a **false pass** rather than an error.
- [ ] A rendered-policy test asserts no new `Resource: "*"` statement.

---

## Data Model

```python
# The enqueued restore request
{
  "requestId": "b71d…",                                    # this run
  "mode": "restore",
  "actor": { "idToken": "eyJ…" },
  "space": { "kind": "personal", "name": "alice" },
  "archiveId": "9f2c1b8e-…"                                # what is being restored
}

# inspect-archive output  (the pointer; the plan itself is in the admin bucket)
{
  "requestId": "b71d…",
  "actor": { "username": "alice" },
  "archive": { "bucket": "dat-prod-archive", "root": "personal/alice/archive/9f2c1b8e-…/" },
  "space":   { "bucket": "dat-prod-user-space", "root": "alice/" },
  "planKey": "archive/b71d…/restore-plan.json",
  "objectCount": 1204,
  "totalBytes": 8_412_339_201,
  "manifestPresent": True
}

# restore-plan.json
{
  "objects": [ { "archiveKey": "personal/alice/archive/9f2c…/reports/2026/q1.csv",
                 "destKey":    "alice/reports/2026/q1.csv",
                 "bytes": 90_112 }, … ]
}
```

```python
# lambdas/archive-common/arcommon  (additions)
#   config.py   RESTORE_CONFLICT_SAMPLE, RESTORE_HEAD_CONCURRENCY
#   paths.py    is_archive_id(value) -> bool          — strict UUID, used before any concatenation
#               origin_key(archive_key, archive_root, space_root)
#   messages.py archive_not_found / archive_incomplete / destination_occupied
```

## Implementation Phases

### Phase 1: The contract and the branch

- `mode: "restore"` through the machine's `Choice`, the restore request envelope, the FIFO group
  keyed on the archive, and `validate-authorize-restore` including the UUID validation.

### Phase 2: Archive lookup

- `inspect-archive`: pagination, `origin_key` derivation, `_manifest.json` exclusion and cross-check,
  the restore plan as an S3 pointer.

### Phase 3: The guard

- `check-destination-clear`: bounded concurrent heads, short-circuit, the 403-is-occupied rule, the
  sampled refusal, and the terminal states for all three refusals.

### Phase 4: Verification

- Unit tests for every UUID rejection case, the `403` branch, the short-circuit, the missing-manifest
  path and the count-disagreement path.
- **Live check (owed):** using the archive created by SPEC-169's live check, submit a restore and
  confirm it reaches the placeholder terminal. Then re-create one file at its original path, submit
  again, and confirm the `destination_occupied` refusal **names that file** and that **no
  `RestoreObject` call was made** — check the archived object's `head-object` output shows no
  `Restore` header. The absence of that header is the assertion; a refusal that still initiated
  retrieval would look identical from the UI.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, extend the `architecture.md` → *Control Planes → Archive* section with
  the restore branch, a `decisions.md` entry (the absolute guard, the space-from-request rule, the
  self-describing key layout as the lookup mechanism, `requestId` ≠ `archiveId`), and one Key
  Decisions line. No user-facing surface yet — no Help change.
