# Spec: Pre-Signup Username Validation — Cognito Trigger Lambda

**ID:** SPEC-012
**Status:** Completed
**Last Updated:** 2026-06-12
**Depends On:** SPEC-006 (User Pool), SPEC-009 (signup flow this validates)

## Overview

Enforce at signup that every username is safe to use as an S3 prefix and IAM tag value. A small Cognito **pre-signup** trigger Lambda rejects registrations whose username falls outside the allowed pattern, with a clear error shown on the Hosted UI. This closes the gap left open by SPEC-009 (which only *displays* guidance) and protects the SPEC-013 access model, where the username literally becomes the user's storage prefix and `username` principal tag.

This spec replaces an earlier, larger draft ("Custom Attributes + Token Claims") whose pre-token-generation Lambda and `custom:portal_role_arn` attribute were made unnecessary by the Identity Pool ABAC design (SPEC-011). Trigger Lambdas remain permitted per the CLAUDE.md decision — they are auth-service configuration, not an API backend.

## Scope

### In Scope

- Pre-signup Lambda (Python 3.12) validating username length and charset
- Lambda **infrastructure** IaC in `infra/modules/auth/` (execution role, log group, trigger wiring, placeholder function); the Python source lives at the repo root under `lambdas/`
- A shared Lambda artifacts S3 bucket (`infra/modules/lambda-artifacts/`) and a `deploy-lambdas.yml` GitHub Actions workflow that builds + deploys the code
- Deploy role permission expansion (Lambda + execution role + logs + trigger config + artifacts bucket + `update-function-code`)
- Alignment of SPEC-009's landing-page guidance text with the enforced rule

### Out of Scope

- Custom attributes of any kind (superseded — see Overview)
- Pre-token-generation / post-confirmation Lambdas (superseded by SPEC-011)
- Email domain restrictions or invite gating (future spec if needed)
- Validating pre-existing users (none exist in production before this arc completes)

---

## Functional Requirements

### FR-001: Validation Rule

#### Description:

One authoritative username rule, enforced server-side and documented for users.

#### Acceptance Criteria:

- [x] Allowed pattern: `^[a-zA-Z0-9._@-]{3,64}$` (S3-prefix-safe and IAM-tag-safe; no `/`, no spaces, no `=` or `,` to keep prefixes clean)
- [x] The pattern is defined once in the Lambda and quoted verbatim in a code comment + this spec
- [x] SPEC-009's landing-page guidance text (FR-001 there) already states the same rule — verified, no change needed
- [x] Rejection raises an error from the Lambda whose message is user-readable on the Hosted UI signup page (e.g. "Username must be 3–64 characters using only letters, numbers, . _ @ -")

### FR-002: Pre-Signup Lambda

#### Description:

The trigger itself — validate and pass through, or reject.

#### Acceptance Criteria:

- [x] Python source at `lambdas/pre-signup/pre_signup.py` (handler `pre_signup.handler`); shared deps in `lambdas/requirements.txt`
- [x] Terraform owns the function infrastructure and bootstraps it with a placeholder zip + `ignore_changes` on the code; `deploy-lambdas.yml` builds the package, uploads it to the artifacts bucket, and runs `update-function-code` (code deploy lives entirely in CI)
- [x] Valid username: returns the event unchanged (does **not** auto-confirm or auto-verify — normal email verification flow proceeds)
- [x] Invalid username: raises with the FR-001 message; signup is blocked
- [x] No AWS API calls — pure validation; execution role grants logs only (trust + permissions as `.tftpl` templates under `policies/`)
- [x] Wired to `lambda_config.pre_sign_up` on the User Pool; pool granted `lambda:InvokeFunction`
- [x] CloudWatch log group with 14-day retention

### FR-003: Deploy Role Permissions

#### Acceptance Criteria:

- [x] `infra/modules/base/policies/` extended: `lambda` actions (incl. `UpdateFunctionCode`/`PublishVersion`) scoped to the function name pattern, `iam` for its execution role (scoped, incl. `PassRole`), `logs` for its log group (scoped), `s3` for the artifacts bucket (scoped), plus the `cognito-idp` trigger-config update actions (`UpdateUserPool`, already granted)
- [ ] `deploy-infra.yml` PR plan succeeds with the deploy role

---

## Data Model

None.

---

## API / Interface Contract

```python
# lambdas/pre-signup/pre_signup.py
import re

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._@-]{3,64}$")


def handler(event, context):
    if not USERNAME_PATTERN.fullmatch(event.get("userName", "")):
        raise Exception(
            "Username must be 3-64 characters using only letters, numbers, . _ @ -"
        )
    return event
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/                                ← NEW: Lambda source (repo root)
├── requirements.txt                    ← shared Python deps (empty for pre-signup)
└── pre-signup/pre_signup.py            ← handler `pre_signup.handler`

infra/modules/auth/
├── cognito.tf                          ← + lambda_config.pre_sign_up
├── lambda.tf                           ← NEW: placeholder function, exec role, permission, log group
└── policies/                           ← NEW: exec-role trust + permissions .tftpl

infra/modules/lambda-artifacts/         ← NEW: shared artifacts bucket (CI upload target)
infra/modules/base/policies/            ← extended deploy role policy (lambda/iam/logs/artifacts)

.github/workflows/deploy-lambdas.yml    ← NEW: build + update-function-code
```

## Implementation Phases

### Phase 1: Lambda + wiring + deploy permissions (single phase — small spec)

- FR-001 through FR-003

#### Checkpoint

`deploy-infra.yml` PR plan shows the Lambda, role, log group, and pool trigger update. After apply: Hosted UI signup with username `bad/name!` is rejected with the readable message; signup with a valid username proceeds to email verification normally (run the SPEC-009 E2E script's signup section). CloudWatch shows the invocation, no errors.

## Open Questions

- [x] **Resolved (2026-06-10):** custom attributes and the pre-token-generation tags Lambda are dropped — the Identity Pool (SPEC-011) maps the username claim to the principal tag server-side, and the app no longer needs a role ARN claim.
- [x] **Resolved (2026-06-10):** case sensitivity is handled at the pool level — SPEC-006 FR-002 now sets `username_configuration.case_sensitive = false`. No normalization needed here.
