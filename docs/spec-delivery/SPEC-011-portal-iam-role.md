# Completed Spec - Scoped AWS Credentials — Identity Pool ABAC + Shared Portal Role

## What was completed from this spec?

Authenticated users now receive temporary, identity-tagged AWS credentials. A
Cognito **Identity Pool** (enhanced flow) exchanges the User Pool token for STS
credentials against a single shared **portal role**, stamping the user's
`username` as an IAM **principal tag server-side**. Verified end-to-end against
the live account on 2026-06-12. The role deliberately has **no S3 permissions
yet** — those arrive in SPEC-013; until then sessions are tagged but can access
nothing.

**Phase 1 — IaC (merged in [#16](https://github.com/agriffi10/data-analysis-prototype/pull/16)):**
- **`infra/modules/auth/identity-pool.tf`** — `aws_cognito_identity_pool` (authenticated only, `allow_classic_flow = false`, `server_side_token_check = true`, provider = the SPEC-006 User Pool + SPA client) and the `aws_cognito_identity_pool_provider_principal_tag` mapping. Output `identity_pool_id`; root exports `cognito_identity_pool_id`.
- **`infra/modules/data/iam.tf`** + `policies/portal-role-trust.json.tftpl` — the shared `dat-portal-user-role`, trust only (federates `cognito-identity.amazonaws.com`, `sts:AssumeRoleWithWebIdentity` + `sts:TagSession`, `aud` = pool, `amr` = authenticated), and the roles attachment binding it as the pool's authenticated role. Output `iam_role_arn`.
- **`infra/modules/base/`** — deploy role extended with `cognito-identity` (pool/tag/roles) and `iam` portal-role management incl. `iam:PassRole`, scoped to constructed ARNs. Cycle-free wiring (role name as a root `local`, ARN passed to `base` as a string) and fresh `time_sleep` propagation guards in both `auth` and `data`.

**Phase 2 — frontend + docs (merged in [#17](https://github.com/agriffi10/data-analysis-prototype/pull/17)):**
- **`src/lib/amplify.ts`** — adds `identityPoolId` to the Cognito config (optional, so login still works without it; two-branch `configure` to satisfy Amplify's strict union type).
- **`src/lib/s3Client.ts`** — `getS3Client(forceRefresh?)`: builds an `S3Client` from `fetchAuthSession()` credentials, returns `ServiceResult`, never throws; one `forceRefresh` retry hook for credential expiry. **No `@aws-sdk/client-sts`, no role ARN** in app code. The SPEC-002 anonymous/static client stays for the test bucket until SPEC-013.
- `.env.example`, `deploy-app.yml`, and `.github/workflows/README.md` gained `VITE_COGNITO_IDENTITY_POOL_ID` and dropped the superseded `VITE_IAM_ROLE_ARN`. architecture.md + CLAUDE.md already carried the design.
- Tests: `s3Client.test.ts` (4 — construction, credentials-absent, refresh passthrough, no-throw).

**FR-002 claim key — resolved during verification (2026-06-12, [#19](https://github.com/agriffi10/data-analysis-prototype/pull/19)):**
- The mapping value must be **`cognito:username`**, not `username`. With `username`, the CloudTrail `AssumeRoleWithWebIdentity` event had **no `principalTags`** (that claim doesn't exist in a Cognito User Pool ID token). After switching to `cognito:username`, the event shows `"principalTags": { "username": "agriffith" }`.

### Verification (live, 2026-06-12)

- `tofu validate`/`fmt` clean; `tsc -b`, `npm run lint`, `npm run build` clean; `npm run test` → 60 passed.
- CloudTrail `AssumeRoleWithWebIdentity` (`sts.amazonaws.com`): `roleArn` = `dat-portal-user-role`, `audience` = the identity pool, `provider` = `cognito-identity.amazonaws.com`, and **`principalTags.username` == `agriffith`** (FR-002 proof). Credentials issued (`GetCredentialsForIdentity` 200).
- The verification procedure is recorded in `docs/testing/owed.md` §2.6 ("Verifying Scoped Credentials & the `username` Principal Tag").

## What has changed?

- **New infra**: `infra/modules/auth/identity-pool.tf`, `infra/modules/data/iam.tf` + `policies/portal-role-trust.json.tftpl`; deploy-role policy + root wiring (`cognito_identity_pool_id` output, portal-role-name local/ARN).
- **`src/lib/amplify.ts` / `src/lib/s3Client.ts`** — Identity Pool wiring + `getS3Client`. The SPEC-007 email lookup was switched from `fetchUserAttributes()` (GetUser) to the **ID token claim** ([#18](https://github.com/agriffi10/data-analysis-prototype/pull/18)) — GetUser was 400ing because the Hosted UI access token lacks the `aws.cognito.signin.user.admin` scope; reading the claim avoids the failed request and incidentally triggers the credential exchange on load.
- **Env/CI**: `VITE_COGNITO_IDENTITY_POOL_ID` added everywhere; `VITE_IAM_ROLE_ARN` removed (the app never handles a role ARN).

### Follow-ups / notes

- **The portal role still has no S3 permissions** — an S3 call with these credentials returns `AccessDenied`. SPEC-013 attaches the prefix-scoped policy (`${aws:PrincipalTag/username}`) and the user-space bucket policy, and switches the file browser onto the authenticated client.
- GitHub Actions **variable** `VITE_COGNITO_IDENTITY_POOL_ID` must stay set (`tofu output cognito_identity_pool_id`); the `VITE_IAM_ROLE_ARN` secret is obsolete and can be deleted.
- The credential exchange only fires when the app calls `fetchAuthSession()`; today that happens via the auth-session email read, and will also happen through `getS3Client()` once SPEC-013 wires it.
