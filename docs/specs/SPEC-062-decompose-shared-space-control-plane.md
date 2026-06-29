# Spec: Decompose Shared-Space Control Plane into Single-Task Lambdas

**ID:** SPEC-062
**Status:** Completed
**Last Updated:** 2026-06-29
**Depends On:** SPEC-050 (control-plane infra: SQS + Pipe + Step Function + orchestrator role + deploy IAM), SPEC-056 (request contract + actor binding + validate state), SPEC-051 (create verb), SPEC-053 (add/remove-members verbs), SPEC-054 (leave + delete verbs), SPEC-012 (Lambda code/infra split + `deploy-lambdas.yml`)

> **Refactor, not a feature.** The shared-space control plane shipped (SPEC-050→054) as a **single
> 711-line provisioner Lambda** (`shared_space_provisioner.py`) with an `action`-switch
> (`create`/`add_members`/`remove_members`/`leave`/`delete`) plus inline JWT verification and every
> S3/Glue/LF/Cognito helper. That violates the "small, single-task Lambda" rule
> (`docs/best-practices/lambdas/lambdas.md` §1) and was always meant to be **multiple** provisioning
> Lambdas (shared-spaces-architecture.md §7 says "the provisioning Lambda(s) it invokes (validate / create /
> grant / cache-write / cascade-delete)"). This spec realigns the implementation with that intent: the
> **Step Function orchestrates several single-task Lambdas** — it receives the request, runs a
> **validate/authorize** step, then a **`Choice`** routes by `action` to the one verb Lambda that does that
> job. Behavior, the request contract, the membership-tag model, and the registry/cache shapes are
> **unchanged**; only the code/orchestration structure changes (plus two clarifications: create stays
> creator-only, and per-verb least-privilege roles replace the single broad role).

## Overview

Today one Lambda does five unrelated jobs behind an `if action == …` ladder, under one broad orchestrator
role, with one 683-line test suite. It is hard to reason about, over-privileged, and slow to change. This
refactor splits it into single-task Lambdas orchestrated by the Step Function: a **validate-authorize**
Lambda (verify the Cognito ID token, derive the caller, load the registry, authorize the action) followed by
a **`Choice`** state that routes each request to exactly one **verb Lambda** — *create-space*,
*add-members*, *remove-members*, *leave*, or *delete-space*. Shared concerns (auth/JWKS, registry read/write,
client factories, per-user cache writes, and the SPEC-061 notification emit) move into a **common
module/layer** that each verb Lambda imports — sharing *code*, not a fat function. Each verb gets its **own
execution role** scoped to just that task. The browser still enqueues the same request messages (SPEC-056),
and every end state (S3 prefix, Glue DB, registry, membership slots, per-user caches, notifications) is
identical — this is structure, observable behavior is preserved.

## Scope

### In Scope

- **A validate-authorize Lambda** — the Step Function's first task: verify the ID token against the User
  Pool JWKS (issuer/audience/expiry/signature), derive the caller `username`, load the space registry, and
  authorize the action (owner-only verbs; leave = member-not-owner; create = no existing space). Emits a
  small **validated context** for the downstream verb; a failed check terminates the execution (no verb
  runs).
- **One Lambda per verb** — `create-space`, `add-members`, `remove-members`, `leave`, `delete-space` — each
  doing only its task, each idempotent, each **emitting its own notifications inline** via the shared helper
  (SPEC-061, decided: inline per verb).
- **Step Function redesign** — `entry → validate-authorize → Choice(action) → <verb> → success/failure`,
  with `Retry` (backoff) on transient errors and `Catch` → a recorded-failure state for terminal errors;
  an unknown action fails. (Mirrors "event → validate jwt → create space" / "event → validate jwt → add
  users".)
- **Shared common module/layer** — `auth` (JWKS verify / `verified_username`), `registry` (load/save/finalize
  + conditional create), `clients` (boto3 client factories), `cache` (per-user `shared-connections.json`
  upsert/remove + owner projection), and `notify` (`emit_notification`, SPEC-061) — imported by each verb
  Lambda; no duplication, no monolith.
- **Per-verb least-privilege roles** — replace the single broad orchestrator role with a role per function
  scoped to that task (validator ≈ no AWS mutate; create = registry conditional-put + Glue create + LF grant
  + Cognito slot + cache; add/remove = Cognito attrs + registry + cache; leave = same subset; delete =
  recursive S3 delete + drop tables/DB + LF revoke + all members' slots/caches + registry delete). Each
  verified with `simulate-custom-policy`; the Step Function's `iam:PassRole` scoped to exactly these roles.
- **Deploy plumbing** — `deploy-lambdas.yml` gains a matrix row per new function and **drops the
  provisioner row**; deploy-role IAM (`infra/modules/base/policies/`) expands for the new functions/roles
  (incl. the new `iam:PassRole` targets); the old `shared-space-provisioner` function + role + tests are
  **removed** at cutover.
- **Behavior parity + e2e** — `docs/testing/shared-spaces-e2e.md` re-validated: create/add/remove/leave/
  delete produce the same end state as before; per-verb Python test suites replace the monolith's single
  suite.
- **Architecture record update** — `docs/shared-spaces-architecture.md` §2/§7 + CLAUDE.md Key Decision
  updated to the multi-Lambda orchestration.

### Out of Scope

- **Any behavior/feature change to the verbs** — same semantics as SPEC-051/053/054 (owner-only rules,
  unknown-user drop, at-limit skip, cascade order, idempotency). This is a structural refactor.
- **The request contract / message envelope** (SPEC-056), the **membership-tag model** (§3), the
  **registry/cache shapes** (§4), and the **SQS → Pipe → Step Function** front (only the state machine's
  *internals* + the Lambdas change).
- **Notification content** (SPEC-061) — only *where* the emit call lives (now inside each verb Lambda via
  the shared helper); the seven events, recipients, and messages are unchanged.
- **Any UI / browser change** — the app still enqueues the same requests; `useConnections`, the Connections
  tab, etc. are untouched.

---

## Functional Requirements

### FR-001: Validate-authorize Lambda (first state)

#### Description:

Authentication + authorization is one task, run once, before any verb.

#### Acceptance Criteria:

- [ ] A dedicated `validate-authorize` Lambda verifies the message's Cognito **ID token** offline against
  the User Pool JWKS (issuer, audience, expiry, signature) and derives the caller `username` from the
  verified `cognito:username` claim — **ignoring any body-asserted actor** (SPEC-056 actor binding).
- [ ] It loads the space registry and authorizes the action: `create` requires the space **not** to exist;
  `add_members`/`remove_members`/`delete` are **owner-only**; `leave` requires the actor to be a
  **member and not the owner**. A failed check resolves to a **terminal failure** (recorded reason) and the
  state machine does **not** invoke any verb.
- [ ] It outputs a small **validated context** `{ action, actor, space, payload, registry }` for the
  downstream verb (so verbs don't re-verify the token or re-authorize).
- [ ] It performs no provisioning side effects (read-only: JWKS + registry); its role needs no
  mutate permissions (§FR-005).

### FR-002: One single-task Lambda per verb

#### Description:

Each action verb is its own function doing only that job.

#### Acceptance Criteria:

- [ ] Separate Lambdas exist for `create-space`, `add-members`, `remove-members`, `leave`, and
  `delete-space`; none contains an `action` switch or another verb's logic.
- [ ] Each verb is **idempotent / replay-safe** (tolerates already-exists/already-absent), preserving the
  SPEC-051/053/054 semantics exactly (conditional registry create; slot assign/clear; cascade order with the
  registry object removed last; unknown-user drop; at-limit skip).
- [ ] Each verb **emits its own notifications inline** through the shared `emit_notification` helper
  (SPEC-061): create → success/failure to creator; add → added-user / owner at-limit / owner unknown; leave
  → owner; delete → fan-out to deleter + all members. Emit is best-effort and never fails the verb.
- [ ] Each verb returns a small structured terminal result (status + reason) for the state machine.

### FR-003: Step Function routes by action

#### Description:

The orchestration — not the code — decides which verb runs.

#### Acceptance Criteria:

- [ ] The state machine is `entry → validate-authorize → Choice(action) → <verb Task> → success | failure`;
  the **`Choice`** state is the router (one branch per action), not an in-Lambda ladder.
- [ ] Transient errors use the state machine's **`Retry`** (backoff); terminal errors use **`Catch`** → a
  recorded-failure state that writes the request's `failed` status (no DLQ for validation failures); an
  **unknown/unsupported action** routes to failure.
- [ ] State-passed payloads stay **small** (ids/keys + the validated context), not large blobs; each verb
  fetches what else it needs.
- [ ] The end-to-end flow for each action produces the **same** result as the pre-refactor monolith
  (parity, FR-007).

### FR-004: Shared common code (no duplication)

#### Acceptance Criteria:

- [ ] Auth (JWKS/`verified_username`), registry I/O (load/save/finalize/conditional-create), client
  factories, per-user cache helpers, and the notification emit helper live in a **shared Lambda layer**
  (`shared-space-common`, decided over per-zip vendoring so each verb zip stays tiny and the shared code is
  published once) imported by every verb Lambda — extracted from the monolith, not copy-pasted into each
  function.
- [ ] No verb Lambda re-implements JWT verification, registry parsing, or cache writes; the validator owns
  verification, verbs own their mutation using shared I/O helpers.

### FR-005: Per-verb least-privilege roles

> **DESCOPED at build (user decision, 2026-06-29).** The user chose to **keep the single shared
> `orchestrator` role** for the Step Function and all six Lambdas rather than split into per-verb roles. The
> decomposition is structural only (code + Step Function orchestration); the orchestrator role's policy is the
> **union** of every verb's permissions plus `lambda:InvokeFunction` on the six functions, and its Lambda
> log-group grant is widened to `…-shared-space-*`. The acceptance criteria below (own role per function,
> retiring the orchestrator role, scoped `iam:PassRole`, `simulate-custom-policy` per verb) are therefore
> **not** implemented; per-verb least-privilege roles remain a possible future hardening step. All other FRs
> (FR-001→004, FR-006→008) are delivered as written.

#### Acceptance Criteria (not implemented — see note above):

- [ ] Each Lambda has its **own execution role** scoped to exactly the actions/resources that task needs
  (validator: read registry + logs, no mutate; create/add/remove/leave/delete scoped to their specific
  S3/Glue/LF/Cognito calls), with non-scopable actions isolated to their own `"*"` statements
  (architecture.md trap list).
- [ ] The single broad **orchestrator role is retired** (or reduced to the Step Function's own
  execution/PassRole needs); `simulate-custom-policy` confirms each verb role can do its task and **cannot**
  do another verb's (e.g. the validator cannot delete; add-members cannot drop a database).
- [ ] The Step Function's `iam:PassRole` is scoped to **exactly** the verb/validator roles it invokes; the
  deploy role's IAM (`infra/modules/base/policies/`) is expanded for every new function + role (+ PassRole).

### FR-006: Create stays creator-only (no member-add at create)

#### Description:

Creating a space provisions only the creator; members are added afterward from the UI.

#### Acceptance Criteria:

- [ ] The `create-space` Lambda provisions **only the creator's** membership (`members:[actor]`) and takes
  **no member list** in its payload; if a `create` message carries a members array, the member portion is
  **ignored** (create never adds other users).
- [ ] Adding users happens **only** post-creation via `add-members` (SPEC-053), invoked from the
  **Connections tab** member-management drawer — there is no create-time bulk-add path in the backend or UI.
- [ ] (Confirmation of current behavior: the shipped create path already sets `members:[actor]` and the
  create dialog has no member input — this FR makes the guarantee explicit and prevents a future regression.)

### FR-007: Behavior parity + monolith removal

#### Acceptance Criteria:

- [ ] The browser still enqueues the **same** request messages (SPEC-056) — no client change — and each of
  the five actions yields the **identical** end state (S3 prefix/marker, Glue DB + tables, registry object,
  membership slots, per-user caches, notifications) as before.
- [ ] The old `lambdas/shared-space-provisioner/` function, its IAM role, and its single test suite are
  **removed** at cutover; `deploy-lambdas.yml` drops the provisioner matrix row and adds the new ones.
- [ ] `docs/testing/shared-spaces-e2e.md` is re-run/updated to prove parity across create/add/remove/leave/
  delete.

### FR-008: Tests + lint

#### Acceptance Criteria:

- [ ] Per-verb Python test suites (`test_*` co-located with each function) replace the monolith's suite;
  each covers happy path, terminal failures, authorization rejection, and **idempotency** (run twice → same
  end state); the validator has its own tests (valid/expired/forged token; owner/non-owner; leave rules).
- [ ] `tofu -chdir=infra validate` + `plan` clean; `simulate-custom-policy` asserts each verb role's scope
  (FR-005); the state machine definition validates.
- [ ] Conforms to `docs/best-practices/lambdas/lambdas.md` (§1 single responsibility, §7 IAM, §10
  orchestration, §11 testing, §12 code/infra split) — consult it before writing.

---

## Data Model

No new persisted types; the request envelope (SPEC-056) and registry/cache shapes (architecture.md §4) are
unchanged. The only new artifact is the **validated context** passed between Step Function states
(in-memory, small):

```jsonc
// validate-authorize output → verb task input
{
  "action": "add_members",          // discriminator (SPEC-056)
  "actor": "alice",                 // VERIFIED username (from the ID token), not the body
  "space": "salesdata",
  "payload": { "members": ["bob","cara"] },
  "registry": { "owner": "alice", "members": ["alice"], "status": "active" }
}
```

## File & Folder Structure

```
lambdas/
├── shared-space-common/            ← shared code (or a Lambda layer): auth.py (JWKS/verified_username),
│   ├── auth.py                       registry.py (load/save/finalize/conditional-create), clients.py,
│   ├── registry.py                   cache.py (per-user cache upsert/remove + owner projection),
│   ├── clients.py                    notify.py (emit_notification — SPEC-061)
│   ├── cache.py
│   ├── notify.py
│   └── test_*.py
├── shared-space-validate/          ← validate-authorize Lambda (FR-001) + tests
├── shared-space-create/            ← create-space verb (FR-002, FR-006) + tests
├── shared-space-add-members/       ← add-members verb + tests
├── shared-space-remove-members/    ← remove-members verb + tests
├── shared-space-leave/             ← leave verb + tests
├── shared-space-delete/            ← delete-space verb (cascade) + tests
└── shared-space-provisioner/       ← REMOVED at cutover (FR-007)

infra/modules/shared-spaces/
├── stepfunction.tf                 ← validate → Choice(action) → verb tasks + Retry/Catch (FR-003)
├── lambda.tf                       ← one function per verb + validator (+ layer); retire provisioner
├── iam.tf + policies/              ← per-verb roles (FR-005); retire orchestrator monolith role; scoped PassRole
└── variables.tf/outputs.tf         ← function/role ARNs as needed

infra/modules/base/policies/        ← deploy-role IAM for the new functions + roles + PassRole (FR-005)
.github/workflows/deploy-lambdas.yml← matrix rows per new function; drop provisioner row (FR-007)
docs/testing/shared-spaces-e2e.md   ← parity re-validation (FR-007)
docs/shared-spaces-architecture.md  ← §2/§7 updated to multi-Lambda orchestration
```

## Implementation Phases

### Phase 1: Extract shared common code (parity, no structural change yet)

- Pull auth/registry/clients/cache/notify out of `shared_space_provisioner.py` into
  `shared-space-common/` (or a layer) with their own tests; the monolith imports them so behavior is
  unchanged. This de-risks the split by proving the shared helpers in isolation first.

### Phase 2: Validator + verb Lambdas + per-verb IAM

- Create the `validate-authorize` Lambda and the five verb Lambdas, each importing the common code; write
  per-verb roles (least privilege, `simulate-custom-policy`) and deploy-role IAM; add `deploy-lambdas.yml`
  matrix rows. Verbs are not yet wired into the state machine (the monolith still serves traffic).

### Phase 3: Rewire the Step Function + cut over + remove the monolith

- Replace the state machine body with `validate → Choice(action) → verb` (+ Retry/Catch); cut traffic over;
  run the e2e parity suite; then **remove** the provisioner function/role/tests and its deploy row, and
  update the architecture record + CLAUDE.md.
