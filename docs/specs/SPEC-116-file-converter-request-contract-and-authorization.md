---
type: Spec
id: SPEC-116
title: "File Converter — Request Contract, Browser Enqueue & `validate-authorize`"
description: "Would have delivered the file-converter request contract and validate-authorize, vetting the source and a user-chosen destination in the same space, unreserved and empty, cancelled before it was built."
spec_status: Cancelled
depends_on: [SPEC-107, SPEC-115, SPEC-056]
arc: file-converter
arc_order: 2
---

**Dependency notes:** SPEC-107 (`cpcommon`), SPEC-115 (file-converter foundation), SPEC-056 (shared-space access model)
> **Read `docs/file-converter-architecture.md` §2.3, §3.1 and §6 first.**

## Overview

Define the **request envelope**, grant the portal role permission to send it, and implement `validate-authorize`: verify the ID token, derive the actor server-side, authorize the **source**, and validate the **destination**.

**The destination validation is the security core of this arc.** The user chooses the destination — a deliberate product decision (`file-converter-architecture.md` §3.1) taken in preference to a locked-down reserved namespace — so this Lambda is the only thing standing between a typed path and a corrupted account. It enforces three rules, and the execution role adds a fourth as a hard backstop:

1. the destination resolves inside the **same space** as the source;
2. the destination is **not** a reserved prefix — and the list **must include `user_settings/`**, whose omission would let a conversion overwrite a user's notification inbox **permanently** (delete there is already IAM-denied, so they could not even clear the corrupt file);
3. the destination is **empty** — which also blocks the direct case of converting into a folder an existing Glue table already reads, since a live table's `LOCATION` is by definition non-empty. **This pre-check is the ONLY guard:** AWS requires an empty `UNLOAD` destination *"except when writing to partitions"*, and the partitioned path is exactly the one this pipeline uses for partitioned sources (`file-converter-architecture.md` §3.1). The engine will **not** catch what this Lambda misses;
4. and regardless of all three, the execution role carries an explicit **`Deny`** on the protected objects — **and holds `s3:DeleteObject` nowhere at all** (FR-006).

## Scope

### In Scope

- The **request envelope** (`requestId`, `idToken`, `space`, `source`, `destination`) + its TypeScript type.
- The SPA **enqueue service** (`fileConverter.service.ts` → `enqueueConversion`) with a **SHA-256 hashed `MessageGroupId`** (of the *destination*) and `MessageDeduplicationId = requestId`.
- **Portal-role IAM**: `sqs:SendMessage` on the file-converter request queue **only**.
- `VITE_FILE_CONVERTER_QUEUE_URL` — all **four** wiring points, including the manual GitHub repo variable.
- The **`validate-authorize`** Lambda: identity, source authorization, and the three destination rules.
- The **execution role's S3 grants** — source read; destination write **and list**; `_fc-work/` write **and read**; the Athena results prefix (incl. the multipart actions) — **with `s3:DeleteObject` granted NOWHERE** — plus the explicit **`Deny`** on `*/user_settings/*` and `*/DO_NOT_DELETE.txt`.
- The SFN `ValidateAuthorize` state wired to the real Lambda with its `Catch` → **`DropTempTable` (Glue-only)** → failure path.

### Out of Scope

- Listing, schema probing, reconciliation, DDL, UNLOAD, finalize — SPEC-117→119.
- The **Glue / Athena / Lake Formation** grants — SPEC-118.
- UI — SPEC-120. Notifications — SPEC-121.
- Any check against the **Glue catalog** (e.g. "is this destination under an existing table's LOCATION?"). The residual risk is accepted and surfaced as a **UI warning** in SPEC-120. (Note: once SPEC-118 gives the role Glue read, such a check becomes cheap — it is a deliberate follow-up, not a permanent exclusion.)

---

## Functional Requirements

### FR-001: The request envelope

#### Acceptance Criteria:

- [ ] The envelope is `{ requestId, idToken, space: { kind, bucket, prefix }, source, destination }`.
- [ ] `requestId` is a browser-minted UUIDv4, present on **every** request (SPEC-117 keys the manifest on it; SPEC-121 builds the notification dedup id from it).
- [ ] The envelope carries **no actor or username field** — the actor comes from the verified token claim.
- [ ] `destination` is user-supplied on the wire; the Lambda **never** trusts it without validating it.
- [ ] The type lives at `apps/portal/src/features/file-converter/fileConverter.types.ts`.

### FR-002: The enqueue service, with a hashed `MessageGroupId`

#### Acceptance Criteria:

- [ ] `MessageGroupId` = the **SHA-256 hex digest** (exactly 64 characters) of the canonical **destination** location `{bucket}/{normalizedDestination}` — so two conversions targeting the same destination serialize, and conversions to different destinations run in parallel. Both asserted.
- [ ] It is **never** the raw location. A test constructs a destination whose raw form exceeds **128 characters**, asserts the group id is exactly 64 characters, and asserts the send succeeds.
- [ ] A rationale comment records the failure this prevents: SQS caps `MessageGroupId` at 128 characters while S3 keys reach 1024, so a raw group id fails the send **in the browser** for exactly the users with the deepest folders.
- [ ] `MessageDeduplicationId` = `requestId`.
- [ ] The service returns `ServiceResult<T>` and never throws.

### FR-003: Portal-role grant + the env var (all four wiring points)

#### Acceptance Criteria:

- [ ] The portal role gains `sqs:SendMessage` on the file-converter request queue ARN **only**, delivered as a small `.tftpl` attached by name (following `table-share/policies/portal-role-table-share.json.tftpl`).
- [ ] `VITE_FILE_CONVERTER_QUEUE_URL` is added to (1) `outputs.tf`, (2) `.env.example`, (3) `deploy-app.yml`'s build env, **and (4) set as a GitHub Actions repo variable**.
- [ ] The PR description explicitly confirms step (4) — the documented "VITE_* deploy gotcha" (`apps/portal/.env.example:61-62`).

### FR-004: `validate-authorize` — identity and source

#### Acceptance Criteria:

- [ ] The ID token is verified via `cpcommon.auth`; the actor is the `cognito:username` claim, never a body value. A missing, malformed, expired, wrong-audience or non-ID token is a terminal `unauthorized`.
- [ ] **Personal source:** the bucket must be the user-space bucket and the normalized source must start with `{actor}/`.
- [ ] **Shared source:** the registry record must have `status == "active"` **and** the actor must be in `members`; the bucket must be the shared-space bucket; the source must start with `{spaceName}/`.
- [ ] The check is on the **space's** provisioning status, **not** SPEC-073's per-member join chip — a **Pending member passes**. A test asserts it.
- [ ] Path traversal cannot escape the space prefix (normalize before comparing; `..` neutralized).
- [ ] Event-shape validation uses `cpcommon.events` and yields a typed terminal, not a bare `KeyError`.

### FR-005: `validate-authorize` — the destination rules

#### Description

The security core of the arc. Each rule prevents a specific failure; the criteria name them so nobody relaxes a rule without understanding what it was holding back.

#### Acceptance Criteria:

- [ ] **Same space.** The destination must resolve inside the **same** bucket and space prefix as the source. A cross-space destination is a terminal `forbidden`. (Unlike Table Share, this pipeline never writes across spaces.)
- [ ] **Reserved-prefix blocklist.** A destination under `athenaresults/`, **`user_settings/`**, `shared_tables/`, `_data-quality-reports/`, or **`_fc-work/`** (this pipeline's own scratch prefix), or targeting the root `DO_NOT_DELETE.txt` object, is a terminal `forbidden_destination`.
- [ ] **`_data-quality-reports/` is on the list regardless of whether the data-quality arc has shipped** — blocklisting a not-yet-used prefix is free, and omitting it would leave a window in which a conversion could squat on the sibling arc's report prefix.
- [ ] The reserved-prefix list is an **`fccommon.config` constant**, with a cross-reference comment pointing at the data-quality arc's matching constant — the two arcs keep their lists in sync, and each side's comment names the other.
- [ ] A comment records why `user_settings/` is on that list: the user-space policy denies `s3:DeleteObject` there but leaves `s3:PutObject` **wide open** (`analytics/policies/portal-role-analytics.json.tftpl:67-72`), so a write would overwrite `notifications.json` and **permanently destroy the inbox — the user cannot even delete the corrupt file to recover.**
- [ ] A test asserts each blocklist entry is rejected — **including a destination inside `user_settings/` on an account where that prefix is still empty**, which the empty-destination rule alone would let through.
- [ ] A comment records why `_fc-work/` is on the list: it is where SPEC-117 writes the manifest and the target schema, and a destination pointing there would collide the pipeline's own scratch files with the output it is trying to verify.
- [ ] **Empty destination.** A destination with any existing object under it is a terminal `destination_not_empty` — no overwrite, matching Table Share's posture toward recipient targets.
- [ ] **A comment records that this pre-check is the ONLY enforcement of the rule, and must be treated as load-bearing.** AWS requires an empty `UNLOAD` destination **"except when writing to partitions"** — and the partitioned path is precisely the one this pipeline uses for partitioned sources. An earlier draft claimed the rule was "enforced twice, once by us and once by the engine"; it is not. Do not weaken this check on the assumption that Athena will catch what it misses (`file-converter-architecture.md` §3.1).
- [ ] A comment records that the rule is also the **replay interlock**: the pipeline holds no delete permission (FR-006), so partial output from a failed `UNLOAD` stays put, and this check is what stops a retry from running into a half-populated destination and **silently doubling every row**.
- [ ] A comment records the useful side-effect: a live Glue table's `LOCATION` is never empty, so this rule already blocks the *direct* "convert into my table's folder" case with **zero catalog calls**. The residual risk is a destination **nested under** a table's LOCATION, accepted and warned about in SPEC-120.
- [ ] All failures are terminal with **friendly** reasons via `cpcommon.messages` — never raw AWS text.

### FR-006: The execution role's S3 grants — NO delete, and the `Deny` backstop

#### Description

The single most important IAM decision in the arc: **this pipeline holds `s3:DeleteObject` nowhere.** An earlier draft granted it "scoped to the destination." That grant was both **unscopable** and **reachable from an unvalidated path**, and removing it — rather than trying to scope it better — is the fix.

#### Acceptance Criteria:

- [ ] The role gains `s3:GetObject` + `s3:ListBucket` on the source, in both buckets.
- [ ] The role gains `s3:PutObject` on the destination **and `s3:ListBucket` on the destination** — the empty-destination pre-check (FR-005) and SPEC-119's `finalize` both list it, and a policy without `ListBucket` fails both.
- [ ] The role gains `s3:PutObject` **AND `s3:GetObject`** on `_fc-work/`. **The read is not optional:** `reconcile-schema` reads the manifest and `start-unload` reads the target schema. A write-only grant fails at the second verb, after the listing work is done. A comment records that this is the exact bug the sibling data-quality arc caught on its own report prefix (SPEC-109 FR-006) — it was reproduced verbatim here.
- [ ] The role gains read/write on the **Athena results prefix**, **including `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads` and `s3:GetBucketLocation`** — a 250 GB `UNLOAD` is certainly multipart, and Athena cannot write its output *at all* without these. It also **writes the `UNLOAD` data manifest** there (`Statistics.DataManifestLocation`), which is what SPEC-119's `finalize` reads.
- [ ] **`s3:DeleteObject` is granted NOWHERE — not on the destination, not on `_fc-work/`, not anywhere.** A plan assertion confirms the rendered policy contains **no `s3:DeleteObject` action at all**.
- [ ] A comment records, in full, the vulnerability that removing it closes, because a future reader will otherwise "restore" it as a convenience:
  1. **The scope is not expressible in IAM.** The destination is arbitrary user-chosen text from the message body, so the policy resource can only be `{bucket}/*`. There is no such thing as a delete grant scoped to a prefix that *the request names*. The earlier "scoped to the destination prefix" was a description of intent, not of a policy that can be written.
  2. **The destructive path was reachable before validation.** The `Catch` covers **every** state, including `ValidateAuthorize` (SPEC-115 FR-001), so a failure *in the validator* still reached cleanup — acting on a `destination` that had **never been validated**.
  3. **Every portal user can enqueue.** Send a message with a garbage ID token and *another user's* path as the `destination`; validation fails; cleanup fires; **their files are deleted.** That is an authenticated **cross-user file-delete primitive**, handed out by the cleanup path.
- [ ] A comment records what is given up and why it is acceptable: **partial output after a failed `UNLOAD` is left in place.** SPEC-121's notification tells the user it may remain and names the path; FR-005's empty-destination rule then acts as an **interlock**, blocking a retry until they clear it — so it is impossible to retry into a half-populated destination and silently double the data. A manual step after a rare failure, in exchange for deleting a capability that could not be safely scoped on a queue every user can write to.
- [ ] The role carries an explicit **`Deny s3:PutObject`** on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` in **both** buckets (shape: `table-share/policies/execution.json.tftpl:59-68`). (There is no delete to deny — the role has none.)
- [ ] A comment records that the **`Deny` is what makes the guarantee**; FR-005's blocklist is defence in depth. A validation bug must not be able to reach the inbox.
- [ ] The role gains **no** Glue, Athena, or Lake Formation permission in this spec. A plan assertion confirms the rendered policy contains no `glue:`, `athena:`, or `lakeformation:` action.

---

## Data Model

```ts
// apps/portal/src/features/file-converter/fileConverter.types.ts

export type ConverterSpace = {
  kind: 'personal' | 'shared';
  bucket: string;
  prefix: string;           // `{username}/` or `{spaceName}/`
};

export type FileConversionRequest = {
  requestId: string;        // UUIDv4, browser-minted
  space: ConverterSpace;
  source: string;           // file or folder key
  destination: string;      // folder key; must be same-space, unreserved, and empty
};

export type FileConversionMessage = FileConversionRequest & { idToken: string };
```

## API / Interface Contract

```ts
// apps/portal/src/features/file-converter/fileConverter.service.ts

enqueueConversion(req: FileConversionRequest): Promise<ServiceResult<{ requestId: string }>>;

// MessageGroupId         = sha256Hex(`${req.space.bucket}/${normalize(req.destination)}`)  // 64 chars, ALWAYS
// MessageDeduplicationId = req.requestId
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
# SPEC-116: the file-converter request queue. NOTE: wire this into deploy-app.yml's build env
# AND set the GitHub repo variable, or production ships it undefined (the VITE_* deploy gotcha).
VITE_FILE_CONVERTER_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account>/<project>-prod-file-converter-requests.fifo
```

## File & Folder Structure

```
apps/portal/src/features/file-converter/
├── fileConverter.types.ts
├── fileConverter.service.ts
├── fileConverter.service.test.ts
└── index.ts
lambdas/file-converter-validate-authorize/fc_validate_authorize.py   (+ tests)
# ^ fc_-prefixed: the bare `validate_authorize` module name is already table-builder's, and
#   pytest shares ONE module namespace across every verb dir (see SPEC-115's structure note).
lambdas/file-converter-common/fccommon/destination.py             # the three rules (reserved-prefix
                                                                   #   constant lives in fccommon/config.py,
                                                                   #   cross-referenced with the DQ arc's)
infra/modules/file-converter/policies/execution.json.tftpl        # S3 grants + the Deny — and NO s3:DeleteObject
infra/modules/file-converter/policies/portal-role-file-converter.json.tftpl
infra/modules/file-converter/state-machine.asl.json.tftpl         # ValidateAuthorize → real Lambda
```

## Implementation Phases

### Phase 1: Contract + enqueue service

- Types; the service with the **hashed** group id; unit tests (a >128-character destination; same-destination serializes; different-destinations parallelize).

### Phase 2: `validate-authorize`

- Identity + source authorization (FR-004); the three destination rules in `fccommon.destination` (FR-005).
- Tests: valid personal; valid shared (active member); **valid shared (Pending member — must pass)**; non-member; cross-space destination; **each blocklist entry**; **`user_settings/` on an account where that prefix is empty**; `_fc-work/`; a non-empty destination; a traversal attempt; an expired token.

### Phase 3: IAM + wiring + SFN state

- Portal-role grant; execution-role S3 grants (source read; destination write **+ list**; `_fc-work/` write **+ read**; the Athena results prefix incl. the multipart actions) and the **`Deny`** (FR-006), with a **plan assertion that no `s3:DeleteObject` appears anywhere**; the four `VITE_*` wiring points including the manual repo variable; wire the SFN `ValidateAuthorize` state with its `Catch` → **`DropTempTable` (Glue-only)** → failure path. Completion ritual.
