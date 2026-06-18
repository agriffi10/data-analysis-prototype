# Spec: Analytics Foundation IaC — Athena Workgroup, Lake Formation, Results Layout

**ID:** SPEC-032
**Status:** Completed
**Last Updated:** 2026-06-17
**Depends On:** SPEC-010 (user-space bucket), SPEC-011 (Identity Pool + portal role + `username` principal tag), SPEC-013 (prefix-scoped role policy)

## Overview

This spec lays the infrastructure foundation for the in-app Athena query feature (the SPEC-032→036 analytics arc). It provisions the single shared Athena workgroup every user queries through, a Lake Formation governance layer, the per-user results layout, and the Athena/Glue/LF permissions added to the existing shared portal role (SPEC-011/013).

**Isolation model (decided 2026-06-17):** per-user database isolation is enforced exactly like the file browser's S3 isolation — by the **`username` IAM principal tag**, *not* by Lake Formation LF-Tags. The portal role's policy scopes Glue to `arn:aws:glue:*:*:database/${aws:PrincipalTag/username}` (and the matching table ARN), so a session can only address the database whose name equals its own username. Lake Formation grants the **shared role** full access to each database (the grant is issued per-database by the SPEC-033 post-confirmation Lambda); LF therefore authorizes the role broadly, and IAM's principal-tag scoping is the per-user gate. This requires the database name to equal the username — guaranteed by the catalog-safe username rule (SPEC-033 amends SPEC-012). No LF-Tags / tag-based access control.

No per-user databases are created here (SPEC-033). No application code (SPEC-034+). Pure infrastructure in a new `infra/modules/analytics/` module plus the deploy-role expansion.

## Scope

### In Scope

- New `infra/modules/analytics/` module composed from root `main.tf`
- A single shared Athena workgroup (`${project_name}-prod-portal-wg`) all users query through
- An **admin-only** Athena workgroup-default results bucket (`${project_name}-prod-athena-admin`) — no user permissions; reserved for future admin/audit roles and as the workgroup's fallback output location
- The **per-user results layout**: user-facing query results land in `{username}/athenaresults/` inside the existing **user-space bucket** (SPEC-010); the portal role can read/write there but is **denied delete** so results can't be moved out or tampered with. Results are **retained indefinitely** (no lifecycle expiry) — user decision; they accumulate until a future admin process clears them
- Lake Formation bootstrap: data-lake admin (deploy role + the SPEC-033 Lambda role), removal of the default `IAMAllowedPrincipals` ("Super") grants so LF enforces, and registration of the user-space bucket as a Lake Formation location in **hybrid access mode**
- Expansion of the shared portal role's permission policy (SPEC-013) with Athena, Glue (read + DDL, scoped by `${aws:PrincipalTag/username}`), Lake Formation (`GetDataAccess`), and the `{username}/athenaresults/` results actions
- Deploy role permission expansion (Athena, Glue, Lake Formation grant/admin/registration, the admin results bucket)
- Outputs wired through root `outputs.tf`; `.env.example` updated for `VITE_ATHENA_WORKGROUP`

### Out of Scope

- Per-user database creation **and the per-database LF grant to the shared role** (SPEC-033 — the post-confirmation Lambda)
- Lake Formation **LF-Tags / tag-based access control** — explicitly not used; isolation is the IAM principal tag (this Overview)
- Any application code: query services, hooks, UI (SPEC-034/035/036)
- Table/schema creation — users define their own tables via DDL (SPEC-034+); no Glue crawlers
- Athena saved/named queries (history is app-side JSON in `{username}/athenaresults/` — SPEC-034)
- The catalog-safe username-rule amendment itself (SPEC-033 FR-001 owns it; this spec depends on its outcome)
- A staging environment (literal `prod` in names accepted, per SPEC-010 precedent)

---

## Functional Requirements

### FR-001: `analytics` Module Scaffold

#### Description:

A new bounded-context module at `infra/modules/analytics/` holds all Athena / Glue-catalog-config / Lake Formation infrastructure, composed from root `main.tf` (infrastructure domains get their own module — CLAUDE.md decision).

#### Acceptance Criteria:

- [ ] `infra/modules/analytics/` exists with at least `athena.tf`, `s3.tf` (admin results bucket), `lakeformation.tf`, `iam.tf` (portal-role policy additions + attachment), `variables.tf`, `outputs.tf`, and a `policies/` folder for `.tftpl` templates
- [ ] Root `main.tf` declares `module "analytics"`, passing `project_name`, `app_url`, the user-space bucket name/ARN, the portal role name/ARN (from `module.data`), the SPEC-033 Lambda role ARN (for LF admin — via variable, see Open Questions), and the `username` principal-tag key
- [ ] Dependency direction stays one-directional: `analytics` consumes `data`/`auth` outputs, no cycle; `module.analytics` declares `depends_on = [module.data, module.base]`
- [ ] `tofu validate` passes; no resources land in root-level `.tf` files

### FR-002: Shared Athena Workgroup

#### Description:

One workgroup every authenticated user runs queries through (product decision: same workgroup for all; per-user isolation is at the Glue/IAM layer and the per-user results prefix, not separate workgroups).

#### Acceptance Criteria:

- [ ] `aws_athena_workgroup` named `${var.project_name}-prod-portal-wg` (overridable via `workgroup_name`)
- [ ] `configuration.enforce_workgroup_configuration = false` — the app sets a **per-user** `OutputLocation` (`s3://<user-space-bucket>/{username}/athenaresults/`) on every `StartQueryExecution`; enforcement is off so the client supplies it. A comment notes the IAM scoping (FR-006) is the real boundary
- [ ] `configuration.result_configuration.output_location` set to the **admin-only** results bucket (`s3://<admin-results-bucket>/`) as the fallback/default only — so any query that ever omits an explicit location writes to an admin-only place, never a user-readable one; `encryption_configuration = SSE_S3`
- [ ] `configuration.publish_cloudwatch_metrics_enabled = true`
- [ ] `engine_version` pinned to "Athena engine version 3" (named, with a comment), not "AUTO"
- [ ] Optional cost guard `bytes_scanned_cutoff_per_query` from `query_scan_cutoff_bytes` (default 10 GiB), commented as a tunable guardrail
- [ ] Workgroup name exported as an output

> **Why enforcement is off + dual result locations:** Athena has no built-in per-user result prefix. With enforcement off, the app sets `OutputLocation` to the caller's own `{username}/athenaresults/` (which IAM, FR-006, restricts to the caller's prefix), so each user reads only their own results. The workgroup's *default* location is a separate admin-only bucket (FR-003), used only as a fallback and for future admin auditing — never user-readable.

### FR-003: Admin-Only Workgroup Results Bucket

#### Description:

A dedicated bucket for the workgroup's default/fallback output and future admin auditing — **no end-user access**.

#### Acceptance Criteria:

- [ ] Bucket `${var.project_name}-prod-athena-admin` (overridable via `athena_admin_bucket_name`), all four public-access-block settings on, SSE-S3 (AES256), `BucketOwnerEnforced`, versioning disabled (MVP comment)
- [ ] A lifecycle rule expires objects after `var.admin_results_retention_days` (default 30)
- [ ] **The portal role is NOT granted access to this bucket** (FR-006 grants the role only the user-space `athenaresults/` prefix). A comment states this bucket is reserved for future admin/audit roles, which are out of scope here
- [ ] No CORS needed (no browser access). A comment notes that user-facing result downloads read from the user-space `athenaresults/` prefix instead (SPEC-034)
- [ ] `aws s3api get-bucket-lifecycle-configuration` after apply returns the expected document

### FR-004: Lake Formation Bootstrap (Admin + Enforcement)

#### Description:

Make Lake Formation the enforcing authority for the Glue Data Catalog by removing the default catalog-wide `IAMAllowedPrincipals` ("Super") grants, and designate data-lake administrators (the deploy role for IaC, the SPEC-033 Lambda role for per-database grants).

#### Acceptance Criteria:

- [ ] `aws_lakeformation_data_lake_settings`: `admins` includes the deploy role and the SPEC-033 Lambda execution role ARN (passed in by variable — see Open Questions on ordering)
- [ ] `create_database_default_permissions = []` and `create_table_default_permissions = []` — new databases/tables get **no** automatic `IAMAllowedPrincipals` Super grant, so LF genuinely gates catalog access
- [ ] A comment documents that enabling LF enforcement is only safe once (a) the SPEC-033 Lambda grants the shared role per-database access and (b) FR-006's IAM Glue scoping is attached — order matters; without the role grants, all catalog access is denied
- [ ] `tofu validate` + `deploy-infra.yml` PR plan pass

### FR-005: Hybrid Access Mode Registration of the User-Space Bucket

#### Description:

Register the user-space bucket as a Lake Formation location in **hybrid access mode** so the same data is reachable two ways: the file browser keeps direct IAM S3 access (SPEC-013), while Athena (opted-in via the portal role) reads it through Lake Formation credential vending.

#### Acceptance Criteria:

- [ ] `aws_lakeformation_resource` registers the user-space bucket with `hybrid_access_enabled = true` (or equivalent), using a registration IAM role that can read the bucket
- [ ] A comment documents the two pathways: **non-opted-in** principals (the file browser using SPEC-013's direct S3 IAM grants) keep working unchanged; **opted-in** principals (the portal role for analytics) use LF + IAM
- [ ] A comment warns not to flip the registration to enforced (non-hybrid) mode without opting in every principal first — it would break the file browser's direct S3 access
- [ ] Registration role + `iam:PassRole` included in deploy-role/module IAM as needed
- [ ] **Data-location grant:** a static Lake Formation grant gives the **shared portal role** `DATA_LOCATION_ACCESS` on the registered user-space location. This is required for the role to create any table over that location — both `CREATE EXTERNAL TABLE` (read-only, over existing data) and `CREATE TABLE AS SELECT`/`INSERT INTO` (writes). It is a single location-level grant (not per-user); per-user gating still comes from IAM (the Glue database ARN principal-tag scoping in FR-006 and S3 `${aws:PrincipalTag/username}/*` from SPEC-013), so the role can only actually create/write within its own session's prefix. A comment records this

### FR-006: Portal Role — Athena / Glue / LF / Results Permissions

#### Description:

Extend the shared portal role's permission policy with everything a browser session needs to run a query and read its own results. **Glue is scoped by `${aws:PrincipalTag/username}` — this is the per-user isolation primitive.**

#### Acceptance Criteria:

- [ ] **Glue (the isolation gate):** `glue:GetDatabase`, `GetTable`, `GetTables`, `GetPartition(s)` and the DDL actions `CreateTable`, `UpdateTable`, `DeleteTable`, `BatchCreatePartition`/`BatchDeletePartition`, scoped to `arn:aws:glue:*:<acct>:catalog`, `arn:aws:glue:*:<acct>:database/${aws:PrincipalTag/username}`, and `arn:aws:glue:*:<acct>:table/${aws:PrincipalTag/username}/*`. A comment states this is what isolates users — a session tagged `username=alice` can only address `database/alice`; `GetDatabases` (the unscoped list) is **omitted** (the app addresses the user's DB by name; listing all DBs is neither needed nor wanted)
- [ ] **Athena** (workgroup-scoped to the FR-002 workgroup ARN): `athena:StartQueryExecution`, `GetQueryExecution`, `GetQueryResults`, `GetQueryResultsStream`, `StopQueryExecution`, `BatchGetQueryExecution`, `GetWorkGroup`. **`ListQueryExecutions` is omitted** — it is workgroup-scoped and would leak other users' executions; per-user history is the app-side store (SPEC-034). A comment records this
- [ ] **Lake Formation:** `lakeformation:GetDataAccess` (the analytical engine obtains temp credentials for the registered location)
- [ ] **Results S3 (user-space prefix):** `s3:GetObject` + `s3:PutObject` on `arn:aws:s3:::<user-space-bucket>/${aws:PrincipalTag/username}/athenaresults/*` (Athena writes results, the app reads them), plus an explicit **`Deny` of `s3:DeleteObject`/`s3:DeleteObjects`** on the same `athenaresults/*` path so results can't be deleted or moved out (the hard half of "users can't move files out of athenaresults/"; the "can't move *in*" half is UI-enforced, since Athena writes with the user's own credentials and IAM can't distinguish an app write from a manual upload). `ListBucket` for the prefix rides on SPEC-013's existing `${aws:PrincipalTag/username}/*` condition
- [ ] **Source data + CTAS/INSERT output:** confirm SPEC-013's existing `s3:GetObject`/`s3:PutObject`/`ListBucket` on `${aws:PrincipalTag/username}/*` already covers (a) Athena reading source data and (b) **`CREATE TABLE AS SELECT`/`INSERT INTO` writing output data** into the user's own prefix (writes are enabled — SPEC-033). No new S3 statement is needed if so; a comment notes CTAS/INSERT output is normal user-prefix data (visible and deletable in the file browser), distinct from the delete-protected `athenaresults/` results. The LF `INSERT` table permission for writes is granted by the SPEC-033 Lambda; the LF `DATA_LOCATION_ACCESS` for table creation is granted in FR-005
- [ ] No statement grants anything when the `username` tag is absent (same implicit-deny property as SPEC-013 FR-001)
- [ ] `tofu validate` + `deploy-infra.yml` PR plan pass

### FR-007: Deploy Role Permissions

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` extended with: `athena:*WorkGroup*` (scoped to the workgroup name pattern), Glue catalog/database management for apply, `lakeformation` actions (`PutDataLakeSettings`, `GetDataLakeSettings`, `GrantPermissions`/`RevokePermissions`, `RegisterResource`/`DeregisterResource`), `s3:*` scoped to the admin results bucket ARN (per SPEC-010 FR-004's provider-refresh rationale), and `iam:PassRole` for the LF registration role. **No LF-Tag actions** (LF-Tags are not used)
- [ ] The deploy role is added as a Lake Formation `admin` (FR-004) so it can grant/revoke and register
- [ ] `deploy-infra.yml` PR plan succeeds; apply ordering / IAM eventual-consistency handled as in SPEC-010 FR-004 (`depends_on` + `time_sleep` if a transient `AccessDenied` appears)

### FR-008: Outputs and Env Var Mapping

#### Acceptance Criteria:

- [ ] Module outputs: `athena_workgroup_name`, `athena_admin_bucket_name`
- [ ] Root `outputs.tf` exports `athena_workgroup_name` (and `athena_admin_bucket_name` for ops)
- [ ] `apps/portal/.env.example` adds `VITE_ATHENA_WORKGROUP` (cite `tofu output athena_workgroup_name`), consumed starting SPEC-034. **No results-bucket var** — the app derives the results location from `VITE_S3_USER_SPACE_BUCKET` + `{username}/athenaresults/`
- [ ] `.github/workflows/README.md` notes the new `VITE_ATHENA_WORKGROUP` Actions variable

---

## Variables

| Variable | Location | Type | Required | Description |
|---|---|---|---|---|
| `workgroup_name` | root + module (new) | string | no | Default `"${project_name}-prod-portal-wg"` |
| `athena_admin_bucket_name` | root + module (new) | string | no | Default `"${project_name}-prod-athena-admin"` — admin-only fallback/audit bucket |
| `admin_results_retention_days` | module (new) | number | no | Default `30` — admin bucket lifecycle expiry |
| `query_scan_cutoff_bytes` | module (new) | number | no | Default `10737418240` (10 GiB) — per-query scan guardrail |
| `principal_tag_key` | root + module (new) | string | no | Default `"username"` — matches SPEC-011 |
| `lambda_provisioner_role_arn` | root + module (new) | string | yes | SPEC-033 Lambda exec role, added as an LF admin (see Open Questions) |
| `app_url` | root (exists) | string | no | CORS origin (unused here; reserved) |

---

## Data Model

No application types. The `username` IAM principal tag (`${aws:PrincipalTag/username}`) is the cross-cutting identifier; the Glue database name equals it.

## File & Folder Structure

```
infra/
├── main.tf                         ← + module "analytics" block
├── outputs.tf                      ← + athena_workgroup_name, athena_admin_bucket_name
├── variables.tf                    ← + workgroup_name, athena_admin_bucket_name, retention, scan cutoff, principal_tag_key, lambda_provisioner_role_arn
└── modules/
    ├── base/policies/              ← extended deploy role policy (athena/glue/lakeformation/admin-bucket/passrole)
    └── analytics/                  ← NEW
        ├── athena.tf               ← workgroup (default output → admin bucket)
        ├── s3.tf                   ← admin-only results bucket (encryption, lifecycle, public-access-block)
        ├── lakeformation.tf        ← data-lake settings (admins, no Super), hybrid-mode registration
        ├── iam.tf                  ← portal-role permission additions + attachment, registration role
        ├── variables.tf
        ├── outputs.tf
        └── policies/
            └── portal-role-analytics.json.tftpl   ← NEW (Glue-by-tag / Athena / LF / athenaresults S3 + delete-deny)
```

## Implementation Phases

### Phase 1: Deploy-role permissions + module scaffold + workgroup/admin bucket

- Extend deploy role policy (FR-007); scaffold `analytics`; create the workgroup (FR-002) and admin results bucket (FR-003); wire outputs + env docs (FR-008, FR-001)

#### Checkpoint

`tofu validate` passes; `deploy-infra.yml` PR plan shows the workgroup, admin bucket, and deploy-role change, nothing unexpected. After apply: `tofu output athena_workgroup_name` returns the name; a manual `aws athena start-query-execution --work-group <wg> --query-string "SELECT 1" --result-configuration OutputLocation=s3://<admin-bucket>/smoketest/` (admin creds) succeeds.

### Phase 2: Lake Formation enforcement + portal-role analytics permissions

- LF data-lake settings + admins (FR-004), hybrid-mode registration (FR-005), portal-role Glue/Athena/LF/athenaresults policy (FR-006)

#### Checkpoint

`deploy-infra.yml` PR plan + apply succeed. After apply: the catalog's default `IAMAllowedPrincipals` Super grant is gone; the hybrid-mode registration is present (`aws lakeformation describe-resource`); the file browser (SPEC-013) still works against the now-registered user-space bucket (hybrid-mode regression check). **The end-to-end per-user query proof is deferred to SPEC-033's checkpoint** (it needs a real per-user database + the per-DB LF grant the Lambda issues).

## Open Questions

- [x] **Resolved (2026-06-17, implementation).** Data-lake admin / Lambda-role ordering: `lambda_provisioner_role_arn` is **optional (default `""`)** and the LF `admins` list is `compact([deploy_role_arn, lambda_provisioner_role_arn])`, so SPEC-032 deploys standalone with just the deploy role as admin. SPEC-033 fills the variable (its post-confirmation Lambda role) and a re-apply adds it as an LF admin — dependency stays one-directional. (Deviates from the spec's "Required: yes" for this var; necessary because 032 ships before 033.)
- [x] **Resolved (2026-06-17, user decision):** **no lifecycle expiry** on `{username}/athenaresults/` — results are kept **indefinitely**. The user can't delete them (delete-deny), so result objects + history accumulate in the user's prefix until a future admin/deprovisioning process clears them. (The admin-only workgroup bucket, FR-003, keeps its own short lifecycle.) Revisit if storage growth becomes a concern.
- [x] **Resolved (2026-06-17):** isolation is the **IAM `username` principal tag** scoping the Glue database/table ARN — **not** LF-Tags. LF grants the shared role full access per-database (issued by the SPEC-033 Lambda); IAM is the per-user gate. Requires DB name = username (SPEC-033 catalog-safe username rule).
- [x] **Resolved (2026-06-17):** single shared role retained (no per-user roles); same workgroup for all users.
- [x] **Resolved (2026-06-17):** user-facing results + history live in `{username}/athenaresults/` (user-space bucket, delete-denied); the workgroup default output is a separate **admin-only** bucket; user-space bucket registered in LF **hybrid access mode**.
