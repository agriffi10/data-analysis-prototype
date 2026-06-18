# Completed Spec — SPEC-033: Per-User Glue Database Provisioning

## What was completed?

Every user now gets a private Glue database (named exactly as their username) the moment
they confirm sign-up, via a Cognito **post-confirmation** trigger Lambda. Per-user isolation
remains the `username` IAM principal tag scoping the Glue ARN (SPEC-032 FR-006); this spec just
creates the database and LF-grants the shared portal role on it so the role can use it under LF
enforcement.

- **Username rule tightened (FR-001):** pre-signup Lambda regex → `^[a-z][a-z0-9_]{2,62}$`
  (catalog-safe identifier, so `username = S3 prefix = principal tag = Glue DB name` never
  diverges). Updated rejection message + SPEC-009 landing guidance + SPEC-012 amendment note.
- **`lambdas/post-confirmation/post_confirmation.py`** (handler `post_confirmation.handler`):
  on `PostConfirmation_ConfirmSignUp`, `CreateDatabase` (tolerate `AlreadyExists`) + LF
  `GrantPermissions` to the portal role — DB: `DESCRIBE/CREATE_TABLE/ALTER/DROP`; tables:
  `SELECT/INSERT/DESCRIBE/ALTER/DROP`. Idempotent, always returns the event (never blocks signup),
  ignores non-signup triggers.
- **`lambdas/post-confirmation/backfill.py`** — imports `provision_user` from the handler (no
  drift) for already-confirmed users; documented in `docs/testing/auth-e2e.md`.
- **`infra/modules/auth/lambda.tf`** — second function + exec role + 14-day log group + User Pool
  `lambda:InvokeFunction` permission; `cognito.tf` wires `lambda_config.post_confirmation`;
  `outputs.tf` exports `post_confirmation_exec_role_arn`. Exec-role `.tftpl` grants exactly
  `glue:CreateDatabase/GetDatabase`, `lakeformation:GrantPermissions/GetDataLakeSettings`, logs.
- **Deploy-role expansion** in `modules/base/policies/` for the second function (lambda, iam +
  scoped `PassRole`, logs).
- `deploy-lambdas.yml` parameterized over both functions.

## What changed from earlier specs?

- **SPEC-012 pre-signup Lambda** — regex narrowed (behavior change: previously-legal usernames like
  `Alice`/`alice@corp` are now rejected). Greenfield, no production users affected.
- **SPEC-032 `lambda_provisioner_role_arn`** — now filled by `module.auth`'s exec-role ARN, so the
  post-confirmation role joins the LF admins (resolves SPEC-032's open ordering question).
- Root `main.tf` wires `module.auth.post_confirmation_exec_role_arn` → `module.analytics`.

## Verification

`tofu fmt`/`validate` clean; changed `.tftpl` rendered via `tofu console`/`jsondecode`. Deployed
across PRs #64–69. Two deploy-time bugs surfaced and were fixed: (1) first apply hit an IAM
propagation race (re-run cleared it); (2) the LF-admin add silently dropped because the exec-role
ARN was unknown-at-plan inside `compact()` — fixed by constructing the ARN as a known-at-plan string
(PR #65). Both pre-existing users (`themrandrew`, `agriffith`) backfilled via Lambda invoke; logs
confirm DB + grant, re-invoke idempotent. The deploy-gated provisioning checks + the SPEC-032
per-user isolation proof (alice/bob) were verified live and checked off in `docs/testing/auth-e2e.md`
(2026-06-18).

**Durable learning:** the AWS account root user cannot assume IAM roles, so the only way to give
*root* LF authority is a direct `DataLakeAdmins` entry. Final LF admins = deploy-role +
post-confirmation exec-role only (PR #69).
