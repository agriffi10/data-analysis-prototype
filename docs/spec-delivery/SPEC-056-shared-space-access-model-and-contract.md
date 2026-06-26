# Completed Spec — SPEC-056: Shared-Space Access Model & Request Contract

The access-model half of the shared-space foundation (built on SPEC-050). Wires membership tags, portal-role slots, LF registration, the request contract, and trusted-actor binding. **No per-action behavior** — verbs stay stubs (SPEC-051→055). All infra + the provisioner Lambda; no app code.

## What was completed?

- **Membership tags (FR-001):** `custom:shared_space_1..10` user-pool attributes (dynamic `schema` block → in-place `AddCustomAttributes`, **not** a pool replacement) + the single Identity-Pool `principal_tags` map extended with `shared_space_k → custom:shared_space_k`. `max_shared_memberships = 10` is the single root variable driving everything.
- **Portal-role slots (FR-002):** a third inline policy on the portal role (`shared-space-membership`, attached from the shared-spaces module) — consolidated resource-list statements (S3 object CRUD + multipart, `ListBucket` by slot prefix, Glue db/table) scoped to `${aws:PrincipalTag/shared_space_k}`, the shared delete-denies (`athenaresults/`, `DO_NOT_DELETE.txt`), and the **only** browser grant `sqs:SendMessage` to the request queue.
- **Lake Formation (FR-003):** `dat-prod-shared-space` registered in **hybrid** mode via a new shared-space LF-registration role; the SPEC-050 orchestrator role added to the LF `admins` list (in `module.analytics`, constructed-string ARN; `module.analytics depends_on module.shared_spaces`).
- **Request contract (FR-004):** `schemaVersion`-guarded SQS body + `idToken` transport field; registry/cache shapes (Data Model in the spec).
- **Trusted-actor binding + validate (FR-005):** the provisioner Lambda verifies the caller's **Cognito ID token** (JWKS + claims) → trusted `actor` from `cognito:username` (body `actor` ignored), then `authorize()` against the registry (create=any; add/remove/delete=owner-only; leave=member-not-owner). Forged/unauthorized → `AuthorizationError` → SFN `Catch → Fail`, no side effects. Adds `PyJWT[crypto]`. Lambda env: `COGNITO_USER_POOL_ID`/`COGNITO_APP_CLIENT_ID`/`ADMIN_BUCKET`.

Deviations (spec "Implementation Decisions"): ID-token verification over the spec's message-attributes default (user decision); token in body (Pipe-robust); validate lives in the Lambda, not a separate SFN state (single-Lambda model); slots consolidated + kept inline.

## What changed from earlier specs?

- **SPEC-006 auth**: user pool gains 10 custom attributes; the principal-tag map gains 10 keys (in-place updates — plan confirmed no replacement).
- **SPEC-011/013 portal role**: third inline policy added (aggregate 6,491 < 10,240).
- **SPEC-032 analytics**: orchestrator role added to LF admins; `module.analytics depends_on module.shared_spaces`.
- **SPEC-050**: provisioner Lambda gains validate/authorize + env vars; deploy role gained `cognito-idp:AddCustomAttributes` (PR #108, IAM-first). Shipped as 3 PRs (IAM → resources → validate) per the "PR deploy-role IAM before the resources" rule.

## Verification

`tofu fmt`/`validate` clean; templates render to valid JSON; 13 Lambda unit tests pass. **Deployed**; verified live: FR-002 slot allow/deny via `aws iam simulate-custom-policy` (set→allow, unset/empty/other-space→deny **no root leak**, athenaresults delete-denied); FR-005 forged-token request → Step Function **FAILED** with `AuthorizationError` (token verification), no side effects. Authorized-success live test deferred until SPEC-051+ produces real ID tokens (documented in `docs/testing/shared-spaces-e2e.md`). Cognito pool updated **in-place** (no replacement; deletion-protection intact).
