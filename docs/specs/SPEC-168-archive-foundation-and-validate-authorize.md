# Spec: Archive — Foundation Infrastructure, the Archive Bucket & validate-authorize

**ID:** SPEC-168
**Status:** Completed
**Last Updated:** 2026-08-10
**Depends On:** SPEC-088/089 (the table-share plane as the pattern), SPEC-107/125/156 (`cpcommon`), SPEC-126 (DLQ drain), SPEC-152 (`NotifyFailure` on every plane), SPEC-160 (`cpcommon.transfer`)

## Overview

Data that a user no longer works with still costs S3 Standard rates, still fills the file browser,
and still has to be scrolled past. There is no way to put something away. Archiving moves a file or a
whole folder out of the user's space into a separate bucket at a Glacier storage class, leaves behind
a human-readable receipt, and — because the archived copy is genuinely cold — can be reversed only
through a request that takes hours rather than a click.

This spec builds the plane and the vault: a new archive bucket with a seven-year lifecycle, the
queue, the pipe, the state machine, the execution role, the `arcommon` domain layer, and the first
real verb — **validate-authorize**, which proves from the verified ID token that the actor may read
what they are archiving. Nothing is copied and nothing is deleted; the machine ends in a placeholder
terminal.

Two properties of the design are settled here because everything downstream rests on them. **The
archive bucket is never read by the browser** — no CORS, absent from the CSP `connect-src`, and the
portal role holds zero grants on it — so the only route to archived bytes is a restore request
through this plane. And **the archived key encodes its own origin**: an object at
`personal/alice/archive/{uuid}/reports/q1.csv` came from `alice/reports/q1.csv` and can be put back with no
lookup at all, which is what makes SPEC-170's restore robust against a lost record.

## Scope

### In Scope

- A new **archive bucket** (`{project}-prod-archive`): a bucket-wide 7-year expiration lifecycle
  rule, an abort-incomplete-multipart rule, SSE, public access blocked, and a bucket policy admitting
  only the archive execution role and the deploy role.
- `infra/modules/archive/`: a **FIFO** request queue + DLQ, an EventBridge Pipe, a **Standard** state
  machine, one shared execution role, and the `arcommon` domain layer beside `cpcommon`.
- The **archive request contract** the browser enqueues, and its FIFO `MessageGroupId` / dedup rules.
- **validate-authorize**: verify the ID token, take `username` from the verified claim, authorize the
  source space, confirm every selected item sits inside it, and refuse the reserved prefixes.
- A skeleton machine — validate-authorize → placeholder states → terminal — carrying its
  `NotifyFailure` state before `Fail` on every failure path from day one.
- Browser IAM: `sqs:SendMessage` on the new queue **only**, plus a **Deny** on `PutObject` /
  `DeleteObject` / `AbortMultipartUpload` under `archive/` in both space buckets, plus
  `VITE_ARCHIVE_QUEUE_URL` and its deploy wiring.
- **Deploy-role IAM expansion** as in-scope work — this adds a new bucket and a new plane, so
  `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split*
  are required reading before the first `.tf` line.
- Adding the new execution role to **both** the user-space bucket policy's principal allowlist and
  the new archive bucket's policy.
- Registering the new request DLQ with SPEC-126's drain sweep list.

### Out of Scope

- Listing, copying, deleting or writing a receipt — SPEC-169.
- Anything about restore — SPEC-170 and SPEC-171 own the second contract, the guard and the retrieval.
- Any UI, and any notification other than the SPEC-152 pre-verb failure path — SPEC-172.
- **S3 Object Lock and bucket versioning.** Retention is a *ceiling* (objects expire at 7 years), not
  a WORM floor — see FR-001. Object Lock requires versioning, which this project deferred by decision
  (2026-08-03), and in compliance mode would make SPEC-171's archive cleanup impossible.
- Archiving from one space into another's archive. An archive always lands under the space it came
  from.
- In-browser preview of the receipt. The receipt is deliberately a **plain text file the user
  downloads and reads themselves** — that is the whole intent, not a limitation worked around. The
  project's no-preview rule is untouched.
- Any storage class other than `GLACIER`. `GLACIER_IR` and `DEEP_ARCHIVE` were considered and
  rejected — see FR-002.

---

## Functional Requirements

### FR-001: The archive bucket and its retention

#### Description:

A fifth bucket, holding nothing but archived objects, reachable by nothing but this plane.

#### Acceptance Criteria:

- [ ] `local.archive_bucket_name` follows the sibling convention —
      `${var.project_name}-prod-archive`, overridable by a root variable because S3 names are
      globally unique — and its ARN is constructed in root locals like every other bucket.
- [ ] Public access is fully blocked, SSE is enabled, and the bucket has **no CORS configuration**;
      the absence carries the same explicit "never read by the browser" comment the admin bucket
      uses.
- [ ] The bucket host is **not** added to the CSP `connect-src` (SPEC-140). A reviewer must be able
      to read the enumerated `connect-src` and see that no archive host appears.
- [ ] A lifecycle rule expires **every** object 2557 days (7 years) after creation. The rule is
      deliberately **bucket-wide with no prefix filter** — the inverse of the admin bucket's
      `admin_lifecycle_rules_are_prefix_scoped` check, which exists only because that bucket mixes
      `logs/` (retained forever) with expiring content. This bucket holds exactly one class of
      object, so a prefix filter would be a silent way to leave some data unexpired.
- [ ] A comment at the rule records that S3 lifecycle can include a prefix but never exclude one, so
      any future second content class in this bucket must revisit the rule rather than add a filter.
- [ ] An `abort-incomplete-multipart-uploads` rule exists (the Checkov CKV_AWS_300 disposition every
      other bucket already carries).
- [ ] A bucket policy denies every principal except the archive execution role and the deploy role,
      in the same `StringNotLike aws:PrincipalArn` shape the user-space bucket policy uses.
- [ ] A rendered-policy test asserts the **portal role has no statement of any kind** naming the
      archive bucket ARN. The browser's only relationship with this bucket is that it has none.

### FR-002: The storage class and what it costs the user

#### Description:

Archived objects are written at `GLACIER` (S3 Glacier Flexible Retrieval). The choice is recorded
here because it determines the entire shape of SPEC-171.

#### Acceptance Criteria:

- [ ] `arcommon.config.ARCHIVE_STORAGE_CLASS` is the single definition of the storage class, and it
      is `"GLACIER"`. No verb hard-codes the literal.
- [ ] A comment at that constant records the two rejected alternatives and why: `GLACIER_IR` is
      readable in real time and would remove the restore machinery entirely, but is the most
      expensive Glacier class and would make "archive" mean little more than "moved to a cheaper
      bucket"; `DEEP_ARCHIVE` costs ~4x less but restores in 12–48 hours and bills a **180-day**
      minimum.
- [ ] The same comment records the **90-day minimum storage duration**: an object archived and
      restored a week later is still billed for 90 days. This is a property of the storage class, not
      a defect, and SPEC-172's confirm dialog must say so in user-facing wording.
- [ ] A test asserts the constant is one of the three Glacier classes and that changing it to
      `GLACIER_IR` does not silently bypass SPEC-171's restore path — the restore machinery is
      unconditional, because a class that needs no restore still tolerates one being requested.

### FR-003: The plane

#### Description:

The infrastructure, following the shared control-plane pattern.

#### Acceptance Criteria:

- [ ] A FIFO request queue and FIFO DLQ exist, with content-based dedup **off** (the request supplies
      an explicit `MessageDeduplicationId`), and a redrive policy onto the DLQ.
- [ ] An EventBridge Pipe delivers to a **Standard** state machine; `REQUEST_RESPONSE` is not used
      (impossible for a Standard machine — settled in SPEC-157).
- [ ] **One plane serves both archive and restore**, branching on `mode` in the request. This mirrors
      SPEC-143's create/refresh branch on the table-builder machine rather than standing up a sixth
      module: the two verbs share the bucket, the execution role, the key layout and the receipt, and
      a restore is meaningless without the archive that produced it.
- [ ] One execution role serves every verb; an `arcommon` layer holds archive wording and key layout,
      with `cpcommon` supplying the algorithm — no algorithm is forked into `arcommon` (SPEC-156).
- [ ] The machine carries a `NotifyFailure` state before `Fail`, reached on **every** failure path,
      decoding the raw `{Error, Cause}` through `cpcommon.errors.failure_reason` — the SPEC-152 fleet
      test covers the new machine with no exemption.
- [ ] Every catch carries `ResultPath` so the verified actor is not discarded (the shared-space
      defect SPEC-152 fixed).
- [ ] The `mode` branch is a `Choice` guarded by **`IsPresent` before the string comparison** — a
      `Choice` on an absent path raises uncatchable `States.Runtime`, and `Default` does not cover it
      (SPEC-143's recorded trap).
- [ ] The new request DLQ is in SPEC-126's swept list, so a dead-lettered archive becomes a user
      notification.
- [ ] `lambdas/test_deploy_matrix.py` covers every new function: the deploy matrix and what each
      function imports agree.

### FR-004: The request contract

#### Acceptance Criteria:

- [ ] The message carries `requestId`, `mode` (`"archive"`), `actor.idToken`, and `source` (space
      kind + name + the selected items); unknown top-level fields are rejected, not ignored.
- [ ] `requestId` is a **UUID v4 generated by the browser**, and it becomes the archive's permanent
      identity — the `{uuid}` in both the archive key and the receipt folder. It is validated as a
      well-formed UUID **before it is ever concatenated into an S3 key**, in `arcommon.paths`.
- [ ] `MessageGroupId` is the **SHA-256 hex digest** of `{bucket}/{sourceSpaceRoot}` — a hash, never
      the raw path (SQS caps the group id at 128 characters while S3 keys reach 1024, the reason
      recorded for data quality). Two archives from the same space therefore serialize, which is the
      wanted behaviour: they may select overlapping folders.
- [ ] `MessageDeduplicationId` is `requestId`; content dedup is off on the queue, so that id is the
      only double-submit guard.
- [ ] A malformed or unparseable body fails before any AWS call and reaches `NotifyFailure`.
- [ ] Nothing from the untrusted body is used to identify the actor.

### FR-005: Actor identity and source authorization

#### Description:

Archiving deletes the user's data. The authorization check is the same one `delete` already passes,
and must be at least as strict.

#### Acceptance Criteria:

- [ ] The ID token is verified against the pool's JWKS through the single `cpcommon` path
      (SPEC-156); an expired, unsigned or wrong-audience token is a terminal failure.
- [ ] `username` comes from the **verified claim** and from nowhere else.
- [ ] A `personal` source is authorized only when its name equals the verified username.
- [ ] A `shared` source is authorized only when the verified username is an **active** member of that
      space in the registry — `pending`, `leaving`, absent, or a non-existent space all fail. Any
      active member may archive, matching the space's existing write model, where every member
      already holds `DeleteObject` across the whole prefix.
- [ ] Every selected item's key is confirmed to sit **inside** the authorized source root, by the
      two rules SPEC-164 FR-003 establishes and for the same reasons: (a) containment is tested
      against a **trailing-slash-normalised** root, which is what refuses `alice2/…` against root
      `alice/`; and (b) any key containing a `.` or `..` **path segment** is refused outright.
      `arcommon` reuses `cpcommon`'s containment helper rather than reimplementing it.
- [ ] Each rule has its own test, including the `alice2/` case and the `alice/../bob/` case.
- [ ] These reserved roots are refused as archive sources, each with its own test and its own reason
      recorded at the constant: `archive/` (archiving an archive), `athenaresults/`,
      `user_settings/`, `_data-quality-reports/`, and `shared_tables/`. A selection containing
      `DO_NOT_DELETE.txt` is refused for the whole request, because archiving deletes the source and
      the marker is protected by an existing IAM Deny that would fail the run halfway through.
- [ ] The reserved list lives in `arcommon.config` as its **own** list with its own rationale — it is
      not `protectedFolders.ts` reused and not a union of the browser's three lists, whose own header
      comment warns that unioning them is the wrong repair.
- [ ] More than `ARCHIVE_MAX_ITEMS` selected items is a whole-request terminal failure naming the
      count and the cap. (Object and byte caps over the *expanded* selection land in SPEC-169.)

### FR-006: The `archive/` prefix is not writable by the user

#### Description:

The receipt is written by the execution role and must not be editable, forgeable or deletable by the
browser — a user who can rewrite a receipt can misreport what was archived.

#### Acceptance Criteria:

- [ ] A **Deny** on `s3:PutObject`, `s3:DeleteObject` and `s3:AbortMultipartUpload` is added for
      `${user_space_bucket_arn}/${aws:PrincipalTag/username}/archive/*`. It lives as a new statement
      in `infra/modules/data/policies/portal-role-permissions.json.tftpl` — the honest home, beside
      the Allow it narrows, rather than in the analytics template where the two existing personal
      denies happen to sit.
- [ ] The equivalent Deny for shared spaces is added to
      `infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl` using the
      **wildcard space segment** form its two existing denies use —
      `${shared_space_bucket_arn}/*/archive/*` — which applies to every membership slot without a
      per-slot loop.
- [ ] `s3:GetObject` and `s3:ListBucket` are untouched: the user can list the archive folder and
      download a receipt. Denying a *write* action does not perturb listing.
- [ ] The Deny includes `s3:AbortMultipartUpload` explicitly. A Deny on `PutObject` alone already
      blocks multipart uploads (every part is authorized as `PutObject`), but leaving abort out means
      a half-started upload cannot be tidied — the reason recorded at the statement.
- [ ] A rendered-policy test asserts both denies exist and that no new `Resource: "*"` statement
      appears, keeping the SPEC-139 plan scan's IAM findings flat.
- [ ] The delivery doc records that the **UI mirror is owed and lands in SPEC-172** — an IAM Deny
      with no UI counterpart produces a bare `AccessDenied` for a rule this app itself authored,
      which is exactly what `isUndeletableRootFolder` exists to prevent for `athenaresults/`.

### FR-007: Browser enqueue surface and the bucket-policy allowlists

#### Acceptance Criteria:

- [ ] The portal role's only positive archive privilege is `sqs:SendMessage` on the new queue ARN.
- [ ] `VITE_ARCHIVE_QUEUE_URL` is documented in `.env.example`, wired into `deploy-app.yml`'s build
      env, and set as a GitHub Actions repo variable (the recorded `VITE_*` trap).
- [ ] The archive execution role ARN is threaded into the **user-space bucket policy allowlist** —
      a new `variable` in `modules/data`, the `templatefile()` argument, and the root wiring, the
      same three-part change every existing plane's role made. An explicit resource-policy Deny beats
      an identity-policy Allow, so without it every personal-space archive fails `AccessDenied` while
      every shared-space archive succeeds, which reads like a code bug.
- [ ] The role ARN is derived the way its siblings are (constructed from `project_name` +
      `environment` in root locals), so no cycle is introduced between `modules/data` and the new
      module.
- [ ] A rendered-policy test asserts the new ARN appears in the user-space allowlist and in the
      archive bucket's own policy.

---

## Data Model

```python
# The enqueued archive request
{
  "requestId": "9f2c1b8e-…",                                # UUID v4, the archive's permanent id
  "mode": "archive",
  "actor":  { "idToken": "eyJ…" },
  "source": {
    "space": { "kind": "personal", "name": "alice" },        # or {"kind":"shared","name":"marketing"}
    "items": [ { "kind": "file",   "key": "alice/reports/q1.csv" },
               { "kind": "folder", "key": "alice/reports/2026/" } ]
  }
}

# validate-authorize output
{
  "requestId": "9f2c1b8e-…",
  "mode": "archive",
  "actor":  { "username": "alice" },
  "source": { "bucket": "dat-prod-user-space", "root": "alice/", "items": [ … ] },
  "archive": { "bucket": "dat-prod-archive", "root": "personal/alice/archive/9f2c1b8e-…/" }
}
```

```python
# lambdas/archive-common/arcommon
#   config.py    ARCHIVE_STORAGE_CLASS, ARCHIVE_MAX_ITEMS, RESERVED_SOURCE_ROOTS
#   paths.py     archive_root(kind, name, request_id)   — validates the UUID before concatenating
#                origin_key(archive_key, source_root)   — the inverse; no lookup required
#   authz.py     authorize_source(username, space) -> root prefix   (raises on denial)
#   messages.py  archive wording on cpcommon's Resolver
```

**Two keys, and only one of them can collide.**

| | Personal | Shared |
|---|---|---|
| Receipt (in the space bucket) | `{username}/archive/{uuid}/receipt.txt` | `{space}/archive/{uuid}/receipt.txt` |
| Archived data (archive bucket) | `personal/{username}/archive/{uuid}/…` | `shared/{space}/archive/{uuid}/…` |

The receipt path is the requested one exactly: the space's own root, then `archive/{uuid}`. It cannot
collide, because personal and shared spaces are different buckets.

The archive bucket is the first place both namespaces meet, and there they **must** be partitioned by
kind. Shared-space names are made unique by a create-if-absent write against the shared-space
registry (`lambdas/shared-space-common/registry.py`), which contains only spaces; **nothing anywhere
checks a proposed space name against the User Pool**. A user `alice` and a space `alice` can
therefore both exist today. Under a flat `{name}/archive/{uuid}/` they would share one archive
prefix, and since SPEC-170 authorizes a restore by *space* and then reads whatever sits at that
prefix, any member of a space named `alice` could restore the user `alice`'s archived files into the
shared space. The leading `personal/` / `shared/` segment is the whole fix, and it costs nothing
else — the rest of the key is the requested shape.

The alternative fix — refusing to create a shared space whose name matches an existing username — is
**rejected**: it is a change to a shipped, unrelated control plane, it cannot repair names that
already exist, and it would make space creation depend on the User Pool for a reason unrelated to
space creation.

## Implementation Phases

### Phase 1: The bucket

- The archive bucket, its lifecycle rules, SSE, public-access block and bucket policy; the deploy-role
  IAM expansion for a new bucket resource type.

### Phase 2: The plane

- The module (queue, DLQ, Pipe, Standard machine skeleton with the `mode` branch and `NotifyFailure`,
  execution role, layers), the user-space bucket-policy allowlist entry, DLQ registration with the
  drain sweep.

### Phase 3: The contract + validate-authorize

- `arcommon` config/paths/authz/messages; the verb; token verification through `cpcommon`.

### Phase 4: Browser grants

- Portal-role `sqs:SendMessage`, the two `archive/` denies, `.env.example`, `deploy-app.yml` and the
  repo variable.

### Phase 5: Verification

- Unit tests for every authorization branch — the containment cases (`alice2/` against `alice/`, a
  `..`-shaped key), each reserved root, the UUID validation, and the `mode` branch on an absent path.
- **Live check (owed):** enqueue one hand-crafted valid archive request and one with an unauthorized
  source; confirm the first reaches the placeholder terminal, the second notifies the actor, and both
  appear in `logs/service=archive/`. Separately, signed in as a real user, attempt a `PutObject` into
  your own `archive/` prefix and confirm `AccessDenied` — a shared layer's import-time failure only
  shows at **cold start** (PR #196), and an IAM Deny is only proven by a denied call.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, an `architecture.md` → *Control Planes → Archive* section (and the
  "Four features" count in that section's preamble becomes five), a `decisions.md` entry (the bucket
  and its browser-invisibility, `GLACIER` over the two alternatives, retention as a ceiling not a
  floor, the kind-partitioned key layout and the namespace collision it prevents, one plane with a
  `mode` branch), and one Key Decisions line. No user-facing surface yet — no Help change.
