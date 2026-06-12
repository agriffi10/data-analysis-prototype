# Spec: Scoped AWS Credentials — Identity Pool ABAC + Shared Portal Role

**ID:** SPEC-011
**Status:** Completed
**Last Updated:** 2026-06-12
**Depends On:** SPEC-006 (User Pool), SPEC-007 (login/session), SPEC-010 (data module exists)

> **Note:** This spec deliberately grants the role **no S3 permissions** — those arrive in SPEC-013. Until then, sessions are tagged but can access nothing.

## Overview

Give each authenticated user temporary, identity-tagged AWS credentials. A **Cognito Identity Pool** with *attributes for access control* exchanges the User Pool token for STS credentials against a single shared IAM role, mapping the user's username claim to an IAM principal tag **server-side** — the browser never asserts its own identity, so tags cannot be spoofed. SPEC-013's S3 policy then scopes access by `${aws:PrincipalTag/username}`.

This design replaces two earlier ideas after design review: (1) client-passed STS `Tags` (spoofable by any authenticated user) and (2) a pre-token-generation Lambda embedding a tags claim in the JWT (works, but requires the Cognito Essentials plan's V2 trigger and adds Lambda machinery the Identity Pool provides for free). It **reverses the original "No Cognito Identity Pool" decision** — recorded in CLAUDE.md. There are still no per-user IAM roles: one shared role, isolated by tag. Per-user role variation remains possible later via Identity Pool role-mapping rules.

Frontend impact is a simplification: Amplify v6 supports Identity Pools natively, so `fetchAuthSession()` returns scoped credentials directly — no `@aws-sdk/client-sts` dependency, no manual `AssumeRoleWithWebIdentity` call, no role ARN handling in the app.

## Scope

### In Scope

- Cognito Identity Pool in `infra/modules/auth/` (authenticated identities only, User Pool as the sole provider)
- Principal tag mapping (attributes for access control): tag key `username` ← User Pool username claim
- Portal IAM role in `infra/modules/data/` with a trust policy federating from `cognito-identity.amazonaws.com` (`sts:AssumeRoleWithWebIdentity` + `sts:TagSession`), **no permission policy** (SPEC-013)
- Identity Pool ↔ role attachment (in `infra/modules/data/`, keeping module dependency one-directional: `data` consumes `auth` outputs)
- Deploy role permission expansion (Identity Pool + IAM role management)
- Frontend: `identityPoolId` added to Amplify config; `getS3Client()` built on `fetchAuthSession()` credentials with refresh handling
- `VITE_COGNITO_IDENTITY_POOL_ID` env var; **removal** of `VITE_IAM_ROLE_ARN` from `.env.example`
- Architecture doc + CLAUDE.md updates for the design change

### Out of Scope

- Any S3 permissions on the role (SPEC-013)
- Switching the file browser off the test bucket (SPEC-013)
- Unauthenticated (guest) identities — disabled
- Identity Pool role-mapping rules / per-user role variation (future, if ever needed)
- Pre-signup username validation (SPEC-012)

---

## Functional Requirements

### FR-001: Identity Pool

#### Description:

An Identity Pool federating only this app's User Pool, issuing credentials for authenticated users only.

#### Acceptance Criteria:

- [ ] `aws_cognito_identity_pool` in `infra/modules/auth/`: `allow_unauthenticated_identities = false`, `allow_classic_flow = false` (enhanced flow), provider = the SPEC-006 User Pool + client, `server_side_token_check = true`
- [ ] Module outputs `identity_pool_id`; root `outputs.tf` exports `cognito_identity_pool_id`
- [ ] `tofu validate` passes

### FR-002: Principal Tag Mapping

#### Description:

The username claim becomes the `username` principal tag on every credential issuance — asserted by AWS, not the client.

#### Acceptance Criteria:

- [ ] `aws_cognito_identity_pool_provider_principal_tag` maps tag key `username` to the User Pool username claim (`use_defaults = false`; verify the exact claim key — `username` vs `cognito:username` — at implementation and document it in the resource comment)
- [ ] After apply, a CloudTrail `AssumeRoleWithWebIdentity` event from a real login shows `principalTags.username` equal to the Cognito username
- [ ] Resource lives in `infra/modules/auth/` (needs only pool/provider identifiers, no role ARN)

### FR-003: Portal IAM Role (Trust Only)

#### Description:

The single shared role all users receive, trusting the Identity Pool.

#### Acceptance Criteria:

- [ ] Role `${var.project_name}-portal-user-role` in `infra/modules/data/` (name via `portal_role_name` variable; exported as `iam_role_arn`). This supersedes the `S3PortalRole` placeholder name in older docs
- [ ] Trust policy (`.tftpl` under `infra/modules/data/policies/`): federated principal `cognito-identity.amazonaws.com`, actions `sts:AssumeRoleWithWebIdentity` **and** `sts:TagSession`, conditions `cognito-identity.amazonaws.com:aud` = identity pool ID and `ForAnyValue:StringLike` `cognito-identity.amazonaws.com:amr` = `authenticated`
- [ ] `aws_cognito_identity_pool_roles_attachment` in `infra/modules/data/` binds the authenticated role to the identity pool (pool ID passed in from `auth` outputs — dependency stays `data` → `auth`, no cycle)
- [ ] No permission policies attached; comment cites SPEC-013

### FR-004: Deploy Role Permissions

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` extended: `cognito-identity` actions for pool/tag/attachment management, and `iam` actions for the portal role (scoped to its name pattern)
- [ ] `deploy-infra.yml` PR plan succeeds with the deploy role

### FR-005: Frontend Credential Integration

#### Description:

Amplify hands the app scoped credentials; the S3 client consumes them.

#### Acceptance Criteria:

- [ ] `src/lib/amplify.ts` adds `identityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID` to the Cognito config
- [ ] `getS3Client(forceRefresh?)` in `src/lib/s3Client.ts`: calls `fetchAuthSession({ forceRefresh })`, errors descriptively via `ServiceResult` if `session.credentials` is absent, returns an `S3Client` configured with those credentials
- [ ] Credential refresh: on an S3 call failing with an expired-credentials error, one transparent retry with `getS3Client(true)` (Amplify refreshes the underlying session)
- [ ] **No `@aws-sdk/client-sts` dependency is added** — the earlier draft's manual STS integration is superseded
- [ ] No role ARN appears anywhere in app code or env vars
- [ ] The existing anonymous/static-credential client path (SPEC-002) remains untouched for the test bucket until SPEC-013
- [ ] Unit tests: credentials-absent error path, client construction, refresh path

### FR-006: Docs Update

#### Acceptance Criteria:

- [ ] `docs/architecture.md`: auth flow, trust policy example, `s3Client.ts` example, env var table, and resource inventory updated for the Identity Pool design
- [ ] CLAUDE.md Key Decisions Log: "No Cognito Identity Pool" decision replaced with the reversal and rationale (spoofable client tags; Identity Pool ABAC is the managed fix)
- [ ] `.env.example`: `VITE_COGNITO_IDENTITY_POOL_ID` added; `VITE_IAM_ROLE_ARN` removed
- [ ] `.github/workflows/README.md`: `VITE_COGNITO_IDENTITY_POOL_ID` added to required Actions variables

---

## Data Model

No new app types — Amplify's `AuthSession.credentials` is consumed as-is.

---

## API / Interface Contract

```ts
// src/lib/s3Client.ts
getS3Client(forceRefresh?: boolean): Promise<ServiceResult<S3Client>>;

// Implementation sketch
const session = await fetchAuthSession({ forceRefresh });
if (!session.credentials) {
  return { success: false, error: { message: 'No AWS credentials — sign in required' } };
}
return { success: true, data: new S3Client({ region, credentials: session.credentials }) };
```

## Environment Variables

Add to `.env.example` (source: `tofu output cognito_identity_pool_id`):
```
VITE_COGNITO_IDENTITY_POOL_ID=us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
Remove: `VITE_IAM_ROLE_ARN` (the app never needs the role ARN).

## File & Folder Structure

```
infra/modules/auth/
├── identity-pool.tf            ← NEW: identity pool + principal tag mapping
└── outputs.tf                  ← + identity_pool_id

infra/modules/data/
├── iam.tf                      ← NEW: portal role + roles attachment
└── policies/
    └── portal-role-trust.json.tftpl   ← NEW

apps/portal/src/lib/
├── amplify.ts                  ← + identityPoolId
├── s3Client.ts                 ← reworked: session-credential client
└── s3Client.test.ts            ← NEW
```

## Implementation Phases

### Phase 1: IaC — identity pool, role, attachment, deploy permissions

- FR-001 through FR-004

#### Checkpoint

`deploy-infra.yml` PR plan shows identity pool, principal tag mapping, role (trust matches FR-003 exactly — verify `sts:TagSession`), and attachment. After apply: `tofu output cognito_identity_pool_id` returns the ID; signing in to the deployed app and calling `fetchAuthSession()` in the browser console returns credentials; CloudTrail shows `AssumeRoleWithWebIdentity` with `principalTags.username` = the signed-in username (FR-002 proof).

### Phase 2: Frontend integration + docs

- FR-005, FR-006

#### Checkpoint

Unit tests pass. Manual: signed in, `getS3Client()` returns a client; an S3 call against the user-space bucket is **denied** (no permissions yet — expected, SPEC-013 flips it). Signed out, `getS3Client()` returns the error result. Docs updated per FR-006.

## Open Questions

- [x] **Resolved (2026-06-12):** the claim key is **`cognito:username`**. Mapping the tag value to `username` produced a CloudTrail `AssumeRoleWithWebIdentity` event with **no `principalTags`** (that claim doesn't exist in a Cognito User Pool ID token), so the tag was never stamped. Switched the mapping value to `cognito:username` in `infra/modules/auth/identity-pool.tf`; re-verify the principal tag in CloudTrail after the next apply.
- [x] **Resolved (2026-06-10):** role lives in `modules/data/`; identity pool and tag mapping in `modules/auth/`; roles attachment in `data` — dependency stays one-directional, no cycle.
- [x] **Resolved (2026-06-10):** `RoleSessionName` sanitization is moot — the Identity Pool sets the session name itself; usernames are constrained at signup instead (SPEC-012).
