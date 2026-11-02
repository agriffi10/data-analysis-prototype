---
type: Spec
id: SPEC-033
title: "Per-User Glue Database Provisioning — Post-Confirmation Lambda + LF Grant"
description: "Creates a Glue database named exactly as the username for every new user, through a Cognito post-confirmation Lambda that grants the shared portal role access via Lake Formation."
spec_status: Completed
depends_on: [SPEC-006, SPEC-011, SPEC-012, SPEC-032]
arc: analytics
arc_order: 2
---

**Dependency notes:** SPEC-006 (User Pool), SPEC-011 (portal role + `username` principal tag), SPEC-012 (Lambda infra pattern + `deploy-lambdas.yml` + artifacts bucket; username rule amended here), SPEC-032 (workgroup, LF enforcement bootstrap, hybrid registration)
## Overview

Give every user their own Glue database the moment they finish signing up. A Cognito **post-confirmation** trigger Lambda creates a Glue database **named exactly as the user's username**, then issues a Lake Formation `GrantPermissions` granting the **shared portal role** full access to that database. Per-user isolation does *not* come from this grant (all users share the role) — it comes from the portal role's IAM policy scoping Glue to `database/${aws:PrincipalTag/username}` (SPEC-032 FR-006). The LF grant simply lets the role use the database at all under LF enforcement; IAM's principal tag is the per-user gate. For that gate to work, the database name must equal the username, so this spec also tightens the signup username rule to be a catalog-safe identifier (amending SPEC-012).

It follows the established trigger-Lambda pattern (SPEC-012's pre-signup validator): Terraform owns the function infrastructure, the Python source lives under `lambdas/`, and `deploy-lambdas.yml` deploys the code. Trigger Lambdas are permitted per the CLAUDE.md decision — auth-service configuration, not an API backend.

## Scope

### In Scope

- Tightening the signup username rule to a **catalog-safe identifier** (`^[a-z][a-z0-9_]{2,62}$`) so `username = S3 prefix = principal tag = Glue database name` — amends the SPEC-012 pre-signup Lambda
- A Cognito **post-confirmation** trigger Lambda (Python 3.12) that, idempotently, for the confirmed user: creates Glue database `<username>` if absent; issues an LF `GrantPermissions` of full database permissions to the **shared portal role** for that database
- Lambda **infrastructure** IaC in `infra/modules/auth/` (execution role, log group, trigger wiring, placeholder function) reusing SPEC-012's structure
- The Lambda execution role registered as a Lake Formation admin (resolves SPEC-032's `lambda_provisioner_role_arn` ordering question) and granted the portal role ARN to target in grants
- `deploy-lambdas.yml` extended to build + deploy this second function
- Deploy role permission expansion (function + exec role + logs + trigger config)
- A documented first-login backfill path for users confirmed before this Lambda existed (none in production yet)

### Out of Scope

- Tables / schema — users define tables via DDL (SPEC-034); no crawlers
- Workgroup, admin bucket, LF enforcement bootstrap, hybrid registration, portal-role IAM policy (all SPEC-032)
- LF-Tags / tag-based access control (not used anywhere — SPEC-032 Overview)
- Application code / UI (SPEC-034/035/036)
- Database deletion on account deletion (no deletion flow yet; future)

---

## Functional Requirements

### FR-001: Catalog-Safe Username Rule (Amends SPEC-012)

#### Description:

The `username` IAM principal tag scopes the Glue database ARN (`database/${aws:PrincipalTag/username}`, SPEC-032 FR-006), so the database name must equal the username, and the username must be a legal Glue/Athena identifier. The signup rule is tightened accordingly. (No production users exist yet, so this is a clean, one-time tightening.)

#### Acceptance Criteria:

- [ ] SPEC-012's pre-signup Lambda pattern is changed from `^[a-zA-Z0-9._@-]{3,64}$` to **`^[a-z][a-z0-9_]{2,62}$`**: lowercase, starts with a letter, only letters/digits/underscore, 3–63 chars — simultaneously S3-prefix-safe, IAM-tag-safe, **and** a valid Glue/Athena identifier
- [ ] The rejection message is updated to state the rule (e.g. "Username must be 3–63 characters, start with a letter, and use only lowercase letters, numbers, and underscores")
- [ ] SPEC-009's landing-page guidance text is updated to match (cross-spec consistency, as in SPEC-012 FR-001)
- [ ] The new pattern is defined once in the Lambda and quoted verbatim here and in the updated SPEC-012 doc; the SPEC-012 doc gets an amendment note pointing to this spec
- [ ] A comment cross-references that this single string is the S3 prefix (SPEC-013), the `username` principal/session tag (SPEC-011), and the Glue database name (FR-002) — they must never diverge

### FR-002: Post-Confirmation Lambda Behavior

#### Description:

Provision the user's database and grant the shared role access on first confirmation — idempotently, never blocking sign-up completion.

#### Acceptance Criteria:

- [ ] Python source at `lambdas/post-confirmation/post_confirmation.py` (handler `post_confirmation.handler`); shared deps in `lambdas/requirements.txt` (boto3 in the runtime; no new pip deps)
- [ ] On a `PostConfirmation_ConfirmSignUp` event, the Lambda: (1) reads `userName` (already catalog-safe per FR-001) and uses it **verbatim** as the database name; (2) `glue:CreateDatabase` if absent (catch `AlreadyExistsException` → success); (3) `lakeformation:GrantPermissions` granting the **shared portal role** (ARN from env) `DESCRIBE` + `CREATE_TABLE` + `ALTER` + `DROP` on the **database** and `SELECT` + `INSERT` + `DESCRIBE` + `ALTER` + `DROP` on its **tables** (`ALL TABLES` in the database) — read + table-DDL + **writes** (`INSERT INTO` / `CREATE TABLE AS SELECT`), per the Resolved open question. `DELETE` (row-level) is not granted in v1. Idempotent (catch already-granted → success)
- [ ] **Idempotent and non-fatal:** every step tolerates "already exists / already granted"; the handler **always returns the event** so a transient AWS error never blocks sign-up. Failures are logged at ERROR with the username + step for backfill (FR-004)
- [ ] The Lambda ignores non-signup events (e.g. `PostConfirmation_ConfirmForgotPassword`)
- [ ] No tables are created; the database is empty until the user runs DDL (SPEC-034)
- [ ] CloudWatch log group with 14-day retention (matches SPEC-012)

### FR-003: Lambda Infrastructure + Trigger Wiring

#### Description:

Terraform owns the function infrastructure and execution role, mirroring SPEC-012; code deployed by CI.

#### Acceptance Criteria:

- [ ] `infra/modules/auth/lambda.tf` declares the post-confirmation function, execution role, log group, and the `lambda:InvokeFunction` permission for the User Pool — reusing SPEC-012's conventions; Terraform bootstraps a placeholder zip with `ignore_changes` on the code
- [ ] Wired to `lambda_config.post_confirmation` on the User Pool (alongside the existing `pre_sign_up`)
- [ ] The execution role's permission policy (`.tftpl` under `infra/modules/auth/policies/`) grants exactly: `glue:CreateDatabase`, `glue:GetDatabase`; `lakeformation:GrantPermissions`, `lakeformation:GetDataLakeSettings`; and CloudWatch Logs. Glue scoped to the catalog + database ARN pattern; LF actions account-level
- [ ] The portal role ARN is provided to the Lambda via environment variable (the grant target); the Lambda role is exported as `post_confirmation_exec_role_arn` and consumed by `module.analytics` as `lambda_provisioner_role_arn` (added as an LF admin in SPEC-032 FR-004) — dependency stays one-directional (`analytics` consumes `auth`)
- [ ] `deploy-lambdas.yml` extended to build + `update-function-code` for this second function (parameterize the job over both functions)

### FR-004: Deploy Role Permissions + Backfill

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` extended for the new function: `lambda` actions scoped to the function name pattern, `iam` for its execution role (incl. `PassRole`, scoped), `logs` for its log group; `cognito-idp:UpdateUserPool` already granted (SPEC-012) — verify
- [ ] A documented, runnable **backfill** for already-confirmed users (none in production yet): a small admin script (`lambdas/post-confirmation/backfill.py` or a documented CLI sequence) that runs the same create-database + grant logic for a given username, reusing FR-002's logic (not duplicated). Idempotent. Documented in `docs/testing/e2e.md` or a `docs/runbooks/` note
- [ ] `deploy-infra.yml` PR plan succeeds with the deploy role

---

## Data Model

No application types. One identifier does everything:

```
Cognito username (catalog-safe, FR-001)   e.g. "alice"
        = S3 prefix            s3://<user-space>/alice/...        (SPEC-013)
        = principal tag value  ${aws:PrincipalTag/username}=alice (SPEC-011)
        = Glue database name   database/alice                     (FR-002)
```

## API / Interface Contract

```python
# lambdas/post-confirmation/post_confirmation.py (sketch)
import os, boto3

glue = boto3.client("glue")
lf = boto3.client("lakeformation")
PORTAL_ROLE_ARN = os.environ["PORTAL_ROLE_ARN"]   # grant target (shared role)

def handler(event, context):
    if event.get("triggerSource") != "PostConfirmation_ConfirmSignUp":
        return event
    db = event["userName"]                 # already catalog-safe (FR-001); == DB name
    try:
        _ensure_database(db)               # CreateDatabase, tolerate AlreadyExists
        _grant_role_full_access(db)        # GrantPermissions(principal=PORTAL_ROLE_ARN, db + tables)
    except Exception as e:                 # never block sign-up
        print(f"ERROR provisioning user={db}: {e}")
    return event
```

## Environment Variables

Lambda env (set in Terraform): `PORTAL_ROLE_ARN` (the shared portal role the grant targets). No `VITE_` app vars.

## File & Folder Structure

```
lambdas/
├── requirements.txt                              ← unchanged (boto3 in runtime)
├── pre-signup/pre_signup.py                      ← UPDATED regex (FR-001)
└── post-confirmation/
    ├── post_confirmation.py                      ← NEW handler
    └── backfill.py                               ← NEW (FR-004)

infra/modules/auth/
├── cognito.tf                                    ← + lambda_config.post_confirmation
├── lambda.tf                                     ← + post-confirmation function, exec role, log group, permission
├── outputs.tf                                    ← + post_confirmation_exec_role_arn (→ module.analytics lambda_provisioner_role_arn)
└── policies/                                     ← + post-confirmation exec-role trust + permissions .tftpl

infra/modules/base/policies/                       ← extended deploy role policy (2nd lambda)
.github/workflows/deploy-lambdas.yml               ← build + deploy both functions
docs/specs/SPEC-012-pre-signup-validation.md       ← amendment note (regex tightened)
```

## Implementation Phases

### Phase 1: Username rule + Lambda + wiring + deploy permissions

- FR-001 (regex tightening, SPEC-012/009 text), FR-002, FR-003, FR-004 (deploy perms)

#### Checkpoint

`deploy-infra.yml` PR plan shows the new function, exec role, log group, the `post_confirmation` trigger update, and the exec role added as an LF admin (SPEC-032). `deploy-lambdas.yml` deploys both functions. After apply: a brand-new signup with `alice` (valid) succeeds and confirming triggers the Lambda — CloudWatch shows success; `aws glue get-database --name alice` returns the database; `aws lakeformation list-permissions --principal <portal-role-arn>` shows the grant on `alice`. A signup with `alice@corp` or `Alice` is rejected by the tightened pre-signup rule. No tables exist.

### Phase 2: Isolation proof + backfill

- FR-004 (backfill), plus the end-to-end isolation proof deferred from SPEC-032

#### Checkpoint

The **per-user isolation property** (SPEC-032 FR-006) is proven, not assumed: with two confirmed users (`alice`, `bob`), alice signs in and — via a hand-crafted Athena/Glue SDK call in the dev console using her live session credentials — can `GetDatabase`/`GetTables`, run `CREATE EXTERNAL TABLE`/`SELECT` in `alice`, and write results only to `alice/athenaresults/`; she receives `AccessDenied` (IAM, Glue ARN scoping) for the same calls against `bob` and cannot delete anything under `alice/athenaresults/` (delete-deny). The backfill provisions a database for a manually-created pre-existing user. Both steps appended to `docs/testing/e2e.md`, executed and dated.

## Open Questions

- [x] **Resolved (2026-06-17, user decision):** grant breadth = **read + table-DDL + writes**. The Lambda grants the role `DESCRIBE`, `CREATE_TABLE`, `ALTER`, `DROP` on the **database**, and `SELECT`, `INSERT`, `DESCRIBE`, `ALTER`, `DROP` on its **tables** — so users can `SELECT`, define tables, and **materialize data via `CREATE TABLE AS SELECT` / `INSERT INTO`**. `DELETE` (row-level) is deferred. Two enabling pieces this requires (handled in SPEC-032): a Lake Formation **`DATA_LOCATION_ACCESS`** grant to the role on the registered user-space location (needed to create any table — external or CTAS — over that location), and S3 write to the user's prefix (already granted by SPEC-013's `s3:PutObject` on `${aws:PrincipalTag/username}/*`; CTAS/INSERT output must live under the user's own prefix).
- [ ] **Account deletion / deprovisioning.** Out of scope now; note that later removal should `DeleteDatabase`, revoke the LF grant, and clean `{username}/athenaresults/`. Track as a future spec.
- [x] **Resolved (2026-06-17):** the LF grant targets the **shared portal role** per-database; per-user isolation is the IAM `username` principal tag scoping the Glue ARN (SPEC-032 FR-006), not the grant and not LF-Tags.
- [x] **Resolved (2026-06-17):** database name = username **verbatim**; the signup username rule is tightened to a catalog-safe identifier (FR-001) so no sanitization/hash is needed and the IAM ARN scoping matches exactly.
- [x] **Resolved (2026-06-17):** provisioning = Cognito **post-confirmation** Lambda (mirrors SPEC-012/014); not IaC-static or app-on-login.
