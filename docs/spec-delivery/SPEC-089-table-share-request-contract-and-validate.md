# Completed Spec — SPEC-089: Table Share Request Contract, Enqueue & Validate-Authorize

## What was completed?

- **Request contract**: `{ actor: <idToken>, source: {database, table}, tableName, recipients: [{kind, name}] }`; FIFO `MessageGroupId` = `"{database}.{table}"`, `MessageDeduplicationId` = SHA-256 of token + content + a 1-minute bucket (stable double-submit guard — the queue has content dedup OFF).
- **Browser enqueue**: new `features/table-share/` — `enqueueTableShare` (`ServiceResult`, never throws, ID token attached internally) + types; no UI (SPEC-093).
- **Portal-role grant**: inline `table-share-enqueue` policy (`sqs:SendMessage`, request queue ARN only); `VITE_TABLE_SHARE_QUEUE_URL` in `.env.example` + `deploy-app.yml` + **GH repo var set**.
- **Real `validate-authorize`**: offline JWKS ID-token → actor; source authz (personal = own DB, else active membership in the source space via the registry); `CATALOG_IDENTIFIER_RE` result name; recipient normalization (dedupe on kind+name) + **annotation** (`valid`/`reason: unknown_user | unknown_space` — not fatal, per-recipient independence); whole-request terminals `unauthorized` / `forbidden` / `invalid_table_name` / `invalid_recipients` / `no_recipients`.
- **tscommon filled**: `errors` (Terminal/Transient), `config` (fail-fast env), `clients` (s3/cognito/jwks), `auth`, `registry` (`load`/`is_active`/`is_active_member`), new `cognito.user_exists` (AdminGetUser; throttle → `TransientError`).
- **SFN**: ValidateAuthorize Catch → `ValidateFailureSeed → ParseError → RecordFailure → Failed` (structured `{actor, source, tableName, status:'failed', reason}`); InspectSource/Map whole-request Catches route to the same path; `TransientError` added to the validate/inspect Retry lists.
- **Execution-role grants**: registry `GetObject` (`shared-spaces/*`), `cognito-idp:AdminGetUser`/`ListUsers` (pool ARN), `glue:GetDatabase`/`GetTable` (catalog-wide — LF-admin wiring that makes it resolve on LF-gated DBs lands with SPEC-092).

In-session decisions (reversible, documented):

- **Verb module names carry a `table_share_` prefix** (`table_share_validate_authorize.py` …) — bare `validate_authorize.py` would collide with the table-builder's identically-named module/test on `sys.modules` under one `pytest lambdas/` run (TF handlers updated to match).
- **A recipient space must be ACTIVE** (`status == 'active'`) to be valid — a provisioning/deleting/failed space annotates `unknown_space` (tightens "exists in the registry" to a usable target).
- **Self-conflict recipients are NOT stripped** at validate — sharing a table back into its own DB under the same name fails naturally at `check-target-absent` (architecture §12), keeping validate annotation-only.

## What changed from earlier specs?

- SPEC-088's placeholder `validate_authorize.py` replaced; the other four placeholders renamed (`table_share_*` modules) with TF handler strings updated; the module gained `portal_role_name`/`user_pool_id`/`app_client_id`/`admin_bucket_name` vars + validate's env.

## Verification

15 validate unit tests (direct-run + pytest-compatible), full vitest suite 1011 (8 new `enqueueTableShare` tests incl. dedup-id stability/order-insensitivity), `tofu fmt`/`validate`, ASL + policy templates render valid. Live post-merge check: forged/absent token → execution `Failed` with `RecordFailure.reason = unauthorized…` (documented in `docs/testing/table-share-e2e.md`); the valid path isn't CLI-testable (no CLI-mintable ID token — same as SPEC-051/067). No Help change (no user-facing surface until SPEC-093).
