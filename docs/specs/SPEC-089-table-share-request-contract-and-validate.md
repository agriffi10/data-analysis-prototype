# Spec: Table Share — Request Contract, Enqueue & Validate-Authorize

**ID:** SPEC-089
**Status:** Completed
**Last Updated:** 2026-07-04
**Depends On:** SPEC-088 (foundation), SPEC-056 (registry + ID-token actor), SPEC-067 (table-builder request-contract precedent), SPEC-033/048 (`CATALOG_IDENTIFIER_RE`)

> **Read `docs/table-share-architecture.md` §2–3 first.**

## Overview

Define the **share-request envelope**, grant the browser the single new permission it needs (`sqs:SendMessage` to the table-share queue), and implement the **validate-authorize** Lambda: verify the caller's Cognito ID token → derive the actor server-side, authorize that the actor may **read the source table** (personal = own DB; shared = active member), validate the catalog-safe **result table name**, and validate each **recipient exists** (users via Cognito, spaces via the registry). Downstream verbs stay stubbed.

## Scope

### In Scope

- The **request message contract** (`source`, `tableName`, `recipients[]`, `actor` ID token) + `MessageDeduplicationId`/`MessageGroupId` rules.
- Portal-role **`sqs:SendMessage`** to the table-share request queue; **`VITE_TABLE_SHARE_QUEUE_URL`** exported + deploy-wired (build env + GH repo var).
- A thin browser **enqueue** service (`enqueueTableShare`) — contract + client only; the UI is SPEC-093.
- The **validate-authorize** Lambda:
  - offline JWT verify against the User Pool JWKS → actor username (never trust a body username);
  - **source authorization** — personal source DB must equal the actor; shared source requires active membership in the source space (registry, SPEC-056);
  - **result name** must match `CATALOG_IDENTIFIER_RE`;
  - **recipient validation** — each `kind:'user'` must be an existing Cognito account; each `kind:'space'` must exist in the registry (membership **not** required — any space by name, per the decision doc);
  - normalize recipients (dedupe; strip a recipient equal to the source DB **only** when it would self-conflict — see SPEC-092) and emit `{ actor, source, tableName, recipients[] }` for the downstream `Map`.
- Execution-role grants this step needs: registry `GetObject`, Cognito `ListUsers`/`AdminGetUser`, Glue `GetTable` on the source (LF-admin dependency noted; the grant itself lands where first required — here for the source read).
- The SFN `validate` state + `Catch`→recorded-failure (whole-request failure — nothing copied).

### Out of Scope

- Source **shape** validation (view / catalog-partition rejection, object listing) — that's `inspect-source`, SPEC-090.
- The recipient `Map`, copy, and table creation — SPEC-091/092.
- Notifications — SPEC-094. (A validation failure is recorded in the SFN execution.)
- UI/modal — SPEC-093.

---

## Functional Requirements

### FR-001: Request contract + enqueue

#### Acceptance Criteria:

- [ ] The request envelope is exactly `{ actor: <idToken>, source: { database, table }, tableName, recipients: [{ kind: 'user'|'space', name }, …] }`.
- [ ] The browser sends with `MessageGroupId = "${source.database}.${source.table}"` and a stable `MessageDeduplicationId` (e.g. hash of actor+source+tableName+recipients+timestamp bucket) so an accidental double-submit dedupes.
- [ ] `enqueueTableShare(...)` returns a `ServiceResult` and never throws; it attaches the current ID token as `actor`.
- [ ] The portal role can `sqs:SendMessage` to **only** the table-share queue; `VITE_TABLE_SHARE_QUEUE_URL` is documented in `.env.example`, added to `deploy-app.yml` build env, and set as a GH repo var.

### FR-002: Actor derivation + source authorization

#### Acceptance Criteria:

- [ ] The Lambda verifies the ID token offline (JWKS, issuer/audience/expiry) and derives the actor username from the verified claim; a missing/invalid token is a terminal auth failure.
- [ ] A **personal** source (`source.database === actor`) is authorized; a personal source whose DB ≠ actor is denied.
- [ ] A **shared** source is authorized only if the actor is an **active member** of `source.database` per the registry; a non-member is denied.
- [ ] A denied source authorization fails the whole request (recorded terminal reason) — no recipient is processed.

### FR-003: Result-name + recipient validation

#### Acceptance Criteria:

- [ ] `tableName` not matching `CATALOG_IDENTIFIER_RE` is a whole-request terminal failure with a clear reason.
- [ ] Each `kind:'user'` recipient is validated to exist in the Cognito User Pool; each `kind:'space'` recipient is validated to exist in the registry.
- [ ] A recipient that fails validation is **not** fatal to the request — it is carried forward marked for a per-recipient terminal failure in the `Map` (unknown user / unknown space), so valid recipients still proceed. (Rationale: matches the per-recipient-independence decision; validate-authorize annotates rather than drops, so SPEC-094 can notify precisely.)
- [ ] Duplicate recipients (same kind+name) are collapsed to one.
- [ ] The empty-recipient-list case is a whole-request terminal failure ("no recipients").

---

## Data Model

```ts
// Request envelope (browser → SQS). No new browser domain types beyond:
type ShareRecipient = { kind: 'user' | 'space'; name: string };
type ShareRequest = {
  actor: string;                              // Cognito ID token
  source: { database: string; table: string };
  tableName: string;                          // catalog-safe result name (all recipients)
  recipients: ShareRecipient[];
};
```

```python
# lambdas/table-share/common/  (tscommon)
#   auth.py      verify_id_token(token) -> actor   (reuse the shared-spaces/tbcommon verifier)
#   registry.py  load_space(name), is_active_member(space, user)
#   cognito.py   user_exists(username)
#   glue.py      get_table(database, table)        (source read; LF-admin gated)
# validate-authorize emits: { actor, source, tableName, recipients:[{kind,name,valid,reason?}] }
```

## Implementation Phases

### Phase 1: Contract + enqueue + portal IAM

- Define the envelope + `enqueueTableShare`; add portal-role `sqs:SendMessage`, `VITE_TABLE_SHARE_QUEUE_URL`, deploy wiring.

### Phase 2: validate-authorize Lambda + SFN validate state

- JWT verify → actor; source authorization (personal/shared via registry); result-name + recipient validation; annotate recipients; SFN `validate` state + Catch→recorded-failure; execution-role grants (registry/Cognito/source Glue read).

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`enqueueTableShare`, `tscommon.auth/registry/cognito`).
