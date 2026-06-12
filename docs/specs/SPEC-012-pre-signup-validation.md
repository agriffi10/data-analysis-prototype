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

- Pre-signup Lambda (Node.js 20.x) validating username length and charset
- Lambda IaC in `infra/modules/auth/` (code, execution role, log group, trigger wiring)
- Deploy role permission expansion (Lambda + execution role + logs + trigger config)
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

- [ ] Allowed pattern: `^[a-zA-Z0-9._@-]{3,64}$` (S3-prefix-safe and IAM-tag-safe; no `/`, no spaces, no `=` or `,` to keep prefixes clean)
- [ ] The pattern is defined once in the Lambda and quoted verbatim in a code comment + this spec
- [ ] SPEC-009's landing-page guidance text (FR-001 there) is updated to state the same rule
- [ ] Rejection raises an error from the Lambda whose message is user-readable on the Hosted UI signup page (e.g. "Username must be 3–64 characters using only letters, numbers, . _ @ -")

### FR-002: Pre-Signup Lambda

#### Description:

The trigger itself — validate and pass through, or reject.

#### Acceptance Criteria:

- [ ] Code at `infra/modules/auth/lambda/pre-signup/index.mjs`, packaged with `archive_file` — no build step
- [ ] Valid username: returns the event unchanged (does **not** auto-confirm or auto-verify — normal email verification flow proceeds)
- [ ] Invalid username: throws with the FR-001 message; signup is blocked
- [ ] No AWS API calls — pure validation; execution role grants logs only
- [ ] Wired to `lambda_config.pre_sign_up` on the User Pool; pool granted `lambda:InvokeFunction`
- [ ] CloudWatch log group with 14-day retention

### FR-003: Deploy Role Permissions

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` extended: `lambda` actions scoped to this function name pattern, `iam` for its execution role (scoped), `logs` for its log group (scoped), plus the `cognito-idp` trigger-config update actions
- [ ] `deploy-infra.yml` PR plan succeeds with the deploy role

---

## Data Model

None.

---

## API / Interface Contract

```js
// infra/modules/auth/lambda/pre-signup/index.mjs
const USERNAME_PATTERN = /^[a-zA-Z0-9._@-]{3,64}$/;

export const handler = async (event) => {
  if (!USERNAME_PATTERN.test(event.userName)) {
    throw new Error(
      'Username must be 3-64 characters using only letters, numbers, . _ @ -'
    );
  }
  return event;
};
```

## Environment Variables

None.

## File & Folder Structure

```
infra/modules/auth/
├── cognito.tf                  ← + lambda_config.pre_sign_up
├── lambda.tf                   ← NEW: function, execution role, permission, log group
└── lambda/
    └── pre-signup/index.mjs    ← NEW

infra/modules/base/policies/    ← extended deploy role policy
```

## Implementation Phases

### Phase 1: Lambda + wiring + deploy permissions (single phase — small spec)

- FR-001 through FR-003

#### Checkpoint

`deploy-infra.yml` PR plan shows the Lambda, role, log group, and pool trigger update. After apply: Hosted UI signup with username `bad/name!` is rejected with the readable message; signup with a valid username proceeds to email verification normally (run the SPEC-009 E2E script's signup section). CloudWatch shows the invocation, no errors.

## Open Questions

- [x] **Resolved (2026-06-10):** custom attributes and the pre-token-generation tags Lambda are dropped — the Identity Pool (SPEC-011) maps the username claim to the principal tag server-side, and the app no longer needs a role ARN claim.
- [x] **Resolved (2026-06-10):** case sensitivity is handled at the pool level — SPEC-006 FR-002 now sets `username_configuration.case_sensitive = false`. No normalization needed here.
