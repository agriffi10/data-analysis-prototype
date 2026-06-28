# Architecture Decision: Shared Connections (Bucket 2 — `dat-prod-shared-space`)

**Status:** Proposed — pending review, then drives the shared-connections spec arc (SPEC-050+).
**Last Updated:** 2026-06-21
**Supersedes:** the abandoned "daily-IAM-pipeline" model and the placeholder "user-managed access keys"
note for Bucket 2 in `architecture.md` (both never built).

> Read this before writing or implementing any shared-connections spec. It records *why* the shared-space
> model looks the way it does and the constraints that shaped it. The implementation detail lives in the
> arc specs (SPEC-050+) and the code; this doc is the durable decision record.

---

## 1. What we're building

Any authenticated user can create a **shared connection**: a named, collaborative space backed by a
prefix in a new bucket (`dat-prod-shared-space`) and a Glue database of the same name. The creator is the
**owner**; they add/remove **members** (by username, individually or in bulk), and members can **leave**.
Everyone with access sees the **same** objects and tables (a single shared copy — not per-user copies).
The owner can **delete** the space, cascading to all its files, tables, and the database. The name is
**globally unique** and **non-renameable** (it is simultaneously the S3 prefix and the Glue DB name, exactly
as a username is for a personal space).

This is a deliberate **reversal of the "no backend" key decision** for this feature only: shared spaces
require *privileged, cross-user* operations (grant another user access; provision a database whose name is
not the caller's username; record membership a user cannot self-assert) that browser-scoped credentials
cannot and must not perform. The rest of the app stays browser-direct; shared-space *mutations* go through
a privileged async pipeline.

## 2. Orchestration — the async provisioning pipeline (decided)

User actions that change shared-space state (create space, add/remove member, leave, delete space) are
**requests**, not synchronous operations. The browser, using its existing scoped credentials, **enqueues a
request message** onto an **SQS queue**. From there:

```
Browser (scoped creds: sqs:SendMessage only)
   │  request: { action, actor, space, payload }
   ▼
SQS ──▶ EventBridge Pipe ──▶ Step Function  (orchestrates single-task Lambdas)
                               │
                               ├─ validate-authorize Lambda   (verify ID token → actor; load registry; authorize)
                               │
                               └─ Choice(action) ──▶ one verb Lambda:
                                     • create-space     (S3 prefix + Glue DB + registry + creator slot + cache)
                                     • add-members      (Cognito slots + registry + caches)
                                     • remove-members   (clear slots + registry + caches)
                                     • leave            (clear caller slot + registry + cache)
                                     • delete-space     (cascade: files + tables + DB + all slots/caches + registry)
                                   (Retry/Catch live in the state machine; each verb emits its own notifications)
```

> **Orchestration shape (decided — SPEC-062 refactor):** the control plane is **multiple single-task Lambdas
> orchestrated by the Step Function**, not one monolithic provisioner. The state machine runs a
> **validate-authorize** Lambda, then a **`Choice`** routes by `action` to exactly **one verb Lambda**; shared
> code (auth/registry/clients/cache/notify) lives in a common module/layer and each verb has its **own
> least-privilege role**. The original implementation (SPEC-050→054) shipped as a single 711-line provisioner
> with an `action`-switch; SPEC-062 decomposes it to this shape (the §7 "provisioning Lambda(s)" intent).
> Behavior, the request contract, the membership-tag model, and the registry/cache shapes are unchanged.

- The **only** new permission the browser/portal role gets is `sqs:SendMessage` to this one queue. It cannot
  create databases, grant access, or write another user's data — the Step Function does, under its own
  privileged role.
- The **Step Function** is the single privileged broker. Every state change is **validated server-side**
  (e.g. "is `actor` the owner of `space`?", "is the name already taken?") before anything is provisioned.
  A non-owner request to manage/delete a space fails validation and is a no-op.
- The pipeline is **idempotent** and **non-fatal** in the same spirit as the SPEC-033 post-confirmation
  Lambda: steps tolerate "already exists / already granted / already absent", and a failure is recorded as a
  terminal `failed` status on the request, never a partial silent success.

### Why SQS → Pipe → Step Function (not a direct API)

It keeps the privileged surface **off the user's credentials** entirely (no API the browser calls with
elevated rights), gives durable ret/replay + dead-letter handling for multi-step AWS provisioning, and lets
the orchestration (validate → create → grant → cache) be expressed as explicit, observable states. It also
matches the "trigger/auth-service config, not an API backend" spirit already accepted in CLAUDE.md, extended
to an event-driven control plane.

## 3. Access enforcement — membership principal tag (decided, with one constraint to confirm)

Personal isolation today = the single shared portal role + the **`username` principal tag** scoping S3 and
Glue ARNs. Shared spaces extend the **same idea**: access is gated by a **membership principal tag**, kept
in sync by the Step Function. The role stays shared; the tag is the per-user gate.

### The hard AWS constraint

Cognito Identity Pool "attributes for access control" (the enhanced flow we use) maps each token claim to
**exactly one, single-valued** principal tag. There is **no native multi-valued session tag** through this
flow, and IAM cannot iterate a delimited list inside a `Resource` ARN. So a single tag cannot, by itself,
express "member of an arbitrary set of spaces."

### Resolution (recommended): bounded membership slots

Define a small fixed cap **`MAX_SHARED_MEMBERSHIPS = N`** (proposed **N = 10**). Each user has N Cognito
custom attributes `custom:shared_space_1 … custom:shared_space_N`; the Identity Pool maps each to a principal
tag `shared_space_1 … shared_space_N`. The portal role's permission policy gains N templated statement-pairs:

```jsonc
// per slot k ∈ 1..N  (S3 objects in the shared bucket)
{ "Effect": "Allow",
  "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],
  "Resource": "arn:aws:s3:::dat-prod-shared-space/${aws:PrincipalTag/shared_space_k}/*" }
// + a ListBucket statement conditioned on s3:prefix ${aws:PrincipalTag/shared_space_k}/*
// + Glue: catalog/database/${aws:PrincipalTag/shared_space_k} (+ its tables)
```

- An **unset** slot tag is simply not stamped, so its templated statement expands to nothing and matches
  nothing — an implicit deny, exactly like a session with no `username` tag (architecture.md Authorization
  Model). No "empty tag grants the bucket root" risk as long as the policy templates the tag into the
  resource path (verify with `aws iam simulate-custom-policy`).
- **Lake Formation reuses the established pattern:** the Step Function issues an LF grant on each shared DB to
  the **shared portal role** (same as SPEC-033 does per personal DB); IAM's membership tag is the per-user
  gate, **not** the LF grant and **not** LF-Tags. Querying a shared DB therefore needs both: the LF grant
  (role can use the DB at all under enforcement) **and** a matching membership-slot tag (IAM lets *this* user
  address it).

**Tradeoffs to confirm:**
1. **Cap.** A user can be in at most **N** shared spaces at once. N = 10 keeps the role policy bounded and
   readable. Raising N enlarges the policy; it is not unbounded.
2. **Propagation is not instant.** A membership change updates Cognito attributes; the new principal tag is
   stamped at the *next* credential vend, i.e. when the user gets a fresh ID token (token refresh or
   re-login). So **grant/revoke takes effect on the next session refresh, not immediately** — the documented
   "real-time access revocation needs a backend" constraint (architecture.md Deferred Scope) applies. The UI's
   **refresh-connections** control (§6) forces a credential/token refresh so the change is picked up on demand.

**Alternative if unbounded membership is ever required:** replace the Identity Pool enhanced flow with a
**token-vending Lambda** that calls `sts:AssumeRole` with a true multi-valued `Tags` array and IAM
`ForAnyValue:StringEquals` conditions. This removes the cap but replaces the credential path for the whole
app — a much larger change. Recorded as the escape hatch, not the v1 choice.

## 4. Source of truth — S3 control-object registry (decided)

The **existing analytics admin bucket** (SPEC-032, `{project_name}-prod-athena-admin`), under a
`shared-spaces/` prefix — pipeline-writable only; **not** user-writable, no browser CORS — holds the
authoritative registry:

- **Per-space object** `s3://<admin-bucket>/shared-spaces/{name}.json` — the space record: `name`, `owner`,
  `members[]`, `createdAt`, `status`. Global **name uniqueness** is enforced by the Step Function creating
  this object with a conditional `PutObject` (`If-None-Match: *`) — an atomic create-if-absent; a collision
  fails validation.
- **Per-user UI cache** `s3://<user-space>/{username}/user_settings/shared-connections.json` — written by the
  Step Function into **each** member's own prefix (the privileged role can write any prefix). This is what the
  app reads to render a user's connections; it is a **cache of the registry**, never the source of truth, and
  it carries a per-entry `status` (`provisioning` / `active` / `failed` / `leaving`) for the pending UX (§6).

Users never write either store directly. The per-user JSON being only a cache resolves the impossibility of
the owner writing into a member's bucket from the browser — the **pipeline** does it.

## 5. Data layout & results routing (decided: results in the shared prefix)

```
dat-prod-shared-space/
└── {name}/
    ├── DO_NOT_DELETE.txt                      # space marker (mirrors SPEC-014)
    ├── <user data + table LOCATIONs>          # shared, single copy
    └── athenaresults/
        └── {username}/{queryExecutionId}.csv  # per-member results, under the shared space
```

- Shared **table data** and **`LOCATION`s** live under `dat-prod-shared-space/{name}/`. Tables are created in
  the shared Glue DB `{name}` and are visible to all members (single copy).
- **Query results route to the shared prefix** (user decision): when the active connection is a shared space,
  the client sets the per-query `OutputLocation` to
  `s3://dat-prod-shared-space/{name}/athenaresults/{username}/`, so collaborators can see each other's outputs.
  Each member writes only under their own `{username}/` sub-prefix within the space's results area (membership
  tag + a `${aws:PrincipalTag/username}` sub-scope), and **delete is denied** there (mirrors the personal
  `athenaresults/` lock, SPEC-032). Querying a **personal** DB still routes to the personal
  `{username}/athenaresults/` (SPEC-034) — unchanged.
- Lake Formation registers `dat-prod-shared-space` in **hybrid** mode (as the user-space bucket is, SPEC-032)
  so the file browser keeps direct-IAM S3 access while Athena reads via LF, plus a `DATA_LOCATION_ACCESS`
  grant on the registered shared location so members can create tables/CTAS over it (as SPEC-033 does for the
  personal location).

## 6. Async UX — pending state + manual refresh (decided)

Because provisioning is eventual, the UI never blocks on it:

- A submitted create/add/leave/delete shows the affected connection (or member) in a **pending** state
  (`provisioning…` / `leaving…`), driven by the per-entry `status` in the per-user JSON cache that the Step
  Function flips to `active` / removes / `failed` when it finishes.
- A **Refresh connections** control (mirroring the SPEC-046 history-refresh button) re-reads the per-user
  cache **and forces a credential/token refresh** so newly-granted membership tags take effect on demand
  (§3 propagation). `useConnections` (SPEC-047) gains this refresh + surfaces pending/failed entries.
- A `failed` entry surfaces the reason (from the request's terminal state) and can be dismissed/retried.

## 7. New infrastructure (summary; detailed in SPEC-050)

- **`dat-prod-shared-space`** bucket (CORS for the browser, hybrid LF registration, lifecycle for
  abort-incomplete-multipart as SPEC-016). The registry **reuses the existing analytics admin bucket**
  (SPEC-032) under `shared-spaces/`; its `expire-admin-results` lifecycle rule is scoped to exclude that
  prefix so registry objects don't expire (§4).
- **SQS** request queue (+ DLQ), **EventBridge Pipe** (SQS source → Step Function target), **Step Function**
  state machine, and the **provisioning Lambda(s)** it invokes (validate / create / grant / cache-write /
  cascade-delete). Code under `lambdas/` per the SPEC-012 code/infra split; the state machine + roles in a new
  `infra/modules/shared-spaces/` bounded-context module.
- **Cognito** custom attributes `custom:shared_space_1..N` + Identity Pool principal-tag mappings; the Step
  Function's orchestrator role gets `cognito-idp:AdminUpdateUserAttributes`, LF admin + `GrantPermissions`,
  Glue create/delete, S3 on both buckets, and `iam`/`states`/`logs` as needed.
- **Portal role policy**: N membership-slot statement-pairs (§3) + `sqs:SendMessage` to the request queue.
- **Deploy-role IAM** expanded for every new resource type (SQS, Pipes, Step Functions, the new buckets, the
  Cognito attribute changes) — per the CLAUDE.md infra rule and architecture.md "adding a new resource type"
  traps (self-grant propagation, non-scopable actions, LF enforcement visibility).

## 8. Proposed spec arc (to write after this doc is approved)

UI/screens + design-system additions are **folded into each feature spec** (no standalone UI spec). Build order
is **050 → 056 → 051 → 052 → 053 → 054 → 055 → 057** (056 is the access-model half of the original SPEC-050, split
out so the buckets/pipeline apply and review separately from the IAM/access wiring that trips the most deploy-role
self-grant traps).

**Navigation model (user decision):** a third **top-level tab — Connections** (Files | Query | Connections) is the
place to *manage* spaces (create/delete, member management as a **slide-out drawer**). Shared connections also appear
**inline** where they're *used*: in the **Query** schema-rail database list (switching the workspace-global active
database — SPEC-047) and in the **Files** space list (browsing the space's files — SPEC-057). One `useConnections`
hook (SPEC-052) feeds all three surfaces.

| Spec | Scope |
|---|---|
| SPEC-050 | Shared-space **foundation infrastructure**: `dat-prod-shared-space` bucket + admin-bucket registry prefix (lifecycle-excluded), SQS + DLQ, EventBridge Pipe, Step Function **skeleton**, provisioning Lambda infra, **orchestrator role** + its permission policy, deploy-role IAM. Plumbing only — no access model, no action semantics. |
| SPEC-056 | Shared-space **access model & request contract**: Cognito membership attributes (`shared_space_1..10`) + Identity-Pool tag mappings (`MAX_SHARED_MEMBERSHIPS=10`), portal-role membership-slot policy + `sqs:SendMessage` + shared delete-denies, LF hybrid registration + orchestrator LF admin, the **request-message contract** + registry/cache shapes, and **trusted-actor binding** + the Step Function `validate` state. (Action verbs still stubbed.) |
| SPEC-051 | **Create shared connection** — name prompt/validation, enqueue `create` request, SFN validate(unique)+create(prefix+DB+registry)+grant(creator slot)+cache-write; pending → active UI. |
| SPEC-052 | **Connections tab + lists + refresh** — add the top-level **Connections** tab (`PrimaryNav`); extend `useConnections` with shared entries + pending/failed status + Refresh-connections (force token refresh); one list feeds the Connections tab, the Query schema-rail switcher (SPEC-047), and the Files space list (SPEC-057). |
| SPEC-053 | **Member management (owner)** — a **slide-out drawer** (opened via Manage on the Connections tab): add/remove by username, individually + in bulk; validate against the User Pool + ignore unknowns; updates membership slots + per-user caches; non-owner denied at SFN validation. |
| SPEC-054 | **Leave & delete** — member **leave** (self-service slot+cache revoke; owner can't leave); owner **delete** (cascade: files, tables, DB, all members' slots/caches, registry object). |
| SPEC-055 | **Shared-space results routing + save** — route Athena results to `dat-prod-shared-space/{name}/athenaresults/{username}/` (§5) when the active (workspace-global) DB is shared; Save-results (SPEC-049) within a shared space. |
| SPEC-057 | **Shared spaces in the file browser** — the Files sidebar lists personal + shared spaces in one list; selecting a shared space browses `dat-prod-shared-space/{name}/` with the existing (bucket-parameterized) file operations under the membership-slot IAM. |

## 9. Decisions

- [x] **Reverses "no backend"** for shared-space mutations only, via an **SQS → EventBridge Pipe → Step
  Function** control plane; the browser only gains `sqs:SendMessage`. (User decision.)
- [x] **Enforcement = membership principal tag** on the shared role (not per-user roles, not LF-Tags),
  consistent with the personal `username`-tag model; LF grants the role per shared DB, IAM tag is the gate.
  (User decision.)
- [x] **Source of truth = S3 control-object registry** (pipeline-writable only); per-user
  `shared-connections.json` is a UI **cache** the pipeline writes. Name uniqueness via conditional `PutObject`.
  (User decision.)
- [x] **Query results route to the shared prefix** (`dat-prod-shared-space/{name}/athenaresults/{username}/`,
  delete-denied) when querying a shared DB; personal queries unchanged. (User decision.)
- [x] **Async UX = pending state + manual Refresh-connections** (which forces a token refresh so new
  membership tags apply). (User decision.)
- [x] **Resolved (2026-06-21, user decision):** **`MAX_SHARED_MEMBERSHIPS = 10`** via bounded Cognito
  attribute slots (§3); grant/revoke takes effect on the **next token refresh** (forced by the
  Refresh-connections button), not instantly. The unbounded token-vending-Lambda path is the recorded escape
  hatch only.
- [x] **Resolved (2026-06-21, user decision):** when adding members, the Step Function validates each
  submitted username against the **Cognito User Pool** (`ListUsers`/`AdminGetUser`) and silently drops
  unknowns — "valid user" = exists in the User Pool (not "has signed in" / "has a personal DB").
- [x] **Resolved (2026-06-21, user decision):** **reuse the existing analytics admin bucket** (SPEC-032,
  `{project_name}-prod-athena-admin`, e.g. `dat-prod-athena-admin`) for the registry, under a
  **`shared-spaces/`** prefix. It is already pipeline/admin-only, encrypted, public-access-blocked, and has no
  browser CORS — the designated "admin/audit store." **Caveat:** its lifecycle rule
  (`expire-admin-results`, currently `filter {}` = all objects) must be **scoped to exclude `shared-spaces/`**
  so registry objects never expire (SPEC-050 work). Reversible to a dedicated control bucket if ever desired.
- [x] **Resolved (2026-06-27, user decision — SPEC-062 refactor):** the control plane is **single-task
  Lambdas orchestrated by the Step Function** (validate-authorize → `Choice(action)` → one verb Lambda), not a
  single `action`-switch provisioner; shared code in a common module/layer; **per-verb least-privilege roles**.
  Realigns the implementation with §7's "provisioning Lambda(s)" intent and the Lambda best-practices guide
  (`docs/best-practices/lambdas/lambdas.md`). Behavior/contract/tag-model/registry shapes unchanged. Also
  confirmed: **create is creator-only** — members are added only post-creation via `add-members` (SPEC-053)
  from the Connections tab; there is no create-time bulk-add.
