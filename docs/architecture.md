# Architecture: S3 File Portal

**Last Updated:** 2026-06-11 (added the file-operations arc SPEC-015→020: download/upload/metadata/delete/move/rename/multipart; state management → TanStack Query + Context)  
**Status:** Living document — update as decisions are made.

> **Implementation status as of 2026-06-08:**
> - **Built and working:** File browser (SPEC-001, SPEC-002) — React SPA in `apps/portal/`, browses a test bucket using static or anonymous credentials.
> - **IaC written, not yet applied:** OpenTofu config for static assets S3 bucket, CloudFront, and GitHub Actions OIDC role (SPEC-003). `tofu apply` has not been run against a real AWS account.
> - **Not yet built:** Authentication (Cognito User Pool + Identity Pool + Amplify), user-space/shared-space S3 data buckets, IAM portal role, shared-space access management. (Specced in drafts SPEC-006–014.)
> - **Under redesign:** Bucket 2 access model — see Key Decisions section in CLAUDE.md.

## System Overview

A single-page application (SPA) that allows authenticated users to manage files in AWS S3.
There is **no backend server**. All AWS API calls are made directly from the browser using
temporary IAM credentials for a single shared IAM role, issued by a **Cognito Identity Pool**
that federates the Cognito User Pool token (Amplify v6 handles this exchange natively).

Per-user access isolation is achieved through **IAM principal tags** — the Identity Pool's
*attributes for access control* maps the user's username claim to a `username` principal tag
**server-side** on every credential issuance, and the role's permission policy uses
`${aws:PrincipalTag/username}` to scope each user to their own S3 prefix. The browser never
asserts its own identity to STS, so tags cannot be spoofed. No per-user IAM roles are needed.

**Two-bucket model:** Users interact with two distinct S3 buckets with different access
control mechanisms. Bucket 1 (user-space) is self-contained — IAM enforces per-user prefix
isolation using the Cognito username. Bucket 2 (shared-space) access is governed by a
user-managed access key model — see Bucket 2 section below.

**User-configured connections.** Users configure which Bucket 2 prefixes they connect to
themselves via the UI. The app validates access before saving. Connection configurations
are stored as JSON within the user's own prefix in Bucket 1 — no separate datastore
(DynamoDB, RDS, etc.) is needed.

---

## System Diagram

> **This diagram shows the target vision.** Authentication, the Connection Manager, and the two-bucket S3 model are not yet implemented. Current state: a single file browser hitting a test bucket with static or anonymous credentials.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser (React SPA)                                                 │
│                                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  ┌─────────────┐   │
│  │  Auth UI    │  │ File Browser │  │  Upload/  │  │  Connection │   │
│  │  (Amplify)  │  │  Component   │  │  Download │  │   Manager   │   │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  └──────┬──────┘   │
│         │                └────────────────┴─────────────-─┘          │
│         │                            │                               │
│         │                   ┌────────▼───────┐                       │
│         │                   │   src/lib/     │                       │
│         │                   │  s3Client.ts   │                       │
│         │                   │  amplify.ts    │                       │
│         │                   └────────┬───────┘                       │
└─────────┼────────────────────────────┼──────────────────────────────-┘
          │                            │
          ▼                            ├──────────────────┐
   ┌─────────────┐                     ▼                  ▼
   │   Cognito   │              ┌─────────────┐   ┌─────────────┐
   │  User Pool  │              │  Bucket 1   │   │  Bucket 2   │
   │ (Standalone)│              │(User Space) │   │(Shared Spc) │
   └──────┬──────┘              │             │   │             │
          │                     │ {username}/ │   │ {prefix}/   │
          │ JWT                 │  files/     │   │  files/     │
          ▼                     │  .config/   │   │             │
   ┌─────────────┐              │   connections│  │             │
   │  Identity   │              │   .json     │   │             │
   │    Pool     │              └─────────────┘   └──────┬──────┘
   │ (tag: user- │                                       │
   │  name claim)│                              ┌────────▼────────┐
   └──────┬──────┘                              │  Bucket 2 Access│
          │                                     │  Mgmt (TBD:     │
          ▼                                     │  user-managed   │
   ┌─────────────┐                              │  keys, backend  │
   │  IAM Role   │                              │  TBD)           │
   │ (trust: IdP │                              └─────────────────┘
   │   pool)     │
   └─────────────┘
```

**Key architectural principles:**
- The browser holds temporary credentials for a single shared IAM role, issued by the
  Cognito Identity Pool (enhanced flow) in exchange for the User Pool token. Amplify v6
  returns them from `fetchAuthSession()` — no manual STS calls, no STS SDK dependency.
- All users assume the same role. Per-user isolation is enforced by the Identity Pool
  mapping the username claim to the `username` principal tag (attributes for access
  control). The role's permission policy uses `${aws:PrincipalTag/username}`.
- **Tags are asserted server-side, never by the client** (SPEC-011): client-supplied
  session tags would be spoofable by any authenticated user. The Identity Pool stamps
  them from the verified token. (This is why the original "No Identity Pool" decision
  was reversed — see CLAUDE.md Key Decisions.)
- The app never handles the role ARN — role binding is Identity Pool configuration.
  Per-user role variation, if ever needed, comes via Identity Pool role-mapping rules.
- The IAM role trust policy federates from `cognito-identity.amazonaws.com`, scoped to
  this Identity Pool and authenticated identities, and explicitly permits
  `sts:TagSession` so principal tags are accepted.
- Bucket 2 prefix access model is under review — to be defined in a future spec.
- No long-lived credentials exist anywhere in the frontend.

---

## Authentication Flow

> **Note:** This app uses native Cognito User Pool users (username + password). There is no
> external IdP — no Active Directory or SAML/OIDC federation.

```
1. User lands on app → Amplify checks for active session
      │
      ├─ Session exists → Use cached/refreshed JWT → Re-assume IAM role → Load app
      │
      └─ No session → Redirect to Cognito Hosted UI

2. Cognito Hosted UI → User enters credentials (username + password)
      │
      └─ Cognito validates credentials → Issues JWT (id_token, access_token, refresh_token)

3. Amplify exchanges the User Pool token with the Identity Pool (enhanced flow)
      │    GetId → GetCredentialsForIdentity — no app code, no role ARN involved
      │
      └─ Identity Pool validates the User Pool token
             │
             └─ Principal tag mapping stamps { username: "alice" } from the token claim
                    │
                    └─ Trust policy on portal role confirms: aud = this Identity Pool,
                       amr = authenticated ✓ (sts:TagSession permitted)
                           │
                           └─ Temporary credentials issued (1hr TTL)
                                  │
                                  └─ Amplify caches credentials; app reads via fetchAuthSession()
                                         │
                                         └─ Passed to S3Client on each request
                                                │
                                                └─ IAM evaluates ${aws:PrincipalTag/username}
                                                   scoping S3 access to alice's prefix only
```

### IAM Role Trust Policy

The portal role trusts the **Identity Pool** (not the User Pool directly). It grants
`sts:AssumeRoleWithWebIdentity` and `sts:TagSession` to authenticated identities from this
pool. `sts:TagSession` is required — without it, credential issuance fails once the
principal tag mapping is configured.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "cognito-identity.amazonaws.com"
      },
      "Action": [
        "sts:AssumeRoleWithWebIdentity",
        "sts:TagSession"
      ],
      "Condition": {
        "StringEquals": {
          "cognito-identity.amazonaws.com:aud": "{identityPoolId}"
        },
        "ForAnyValue:StringLike": {
          "cognito-identity.amazonaws.com:amr": "authenticated"
        }
      }
    }
  ]
}
```

The `username` principal tag is configured on the Identity Pool itself (*attributes for
access control* — `aws_cognito_identity_pool_provider_principal_tag`), mapping the User
Pool username claim to the tag key `username`.

### Token lifecycle
- Amplify handles JWT refresh automatically via the refresh_token
- Amplify also caches and refreshes the AWS credentials from the Identity Pool; on SDK
  operations failing with credential expiry errors, call
  `fetchAuthSession({ forceRefresh: true })` and retry once
- No manual token or credential management needed in application code outside this pattern

### Relevant Amplify calls
```ts
// Get current session — credentials come from the Identity Pool exchange
import { fetchAuthSession } from 'aws-amplify/auth';
const session = await fetchAuthSession();
const credentials = session.credentials; // AWS credentials for the portal role

// Get current user — provides the username used as the S3 prefix
import { getCurrentUser } from 'aws-amplify/auth';
const { username } = await getCurrentUser();

// Force refresh (when AWS credentials have expired)
const session = await fetchAuthSession({ forceRefresh: true });

// Sign out
import { signOut } from 'aws-amplify/auth';
await signOut();
```

---

## Authorization Model

The application uses two S3 buckets with different access control mechanisms.
Both are enforced at the IAM layer — no application-level access control exists.

---

### Bucket 1 — User Space

Each user has exactly one prefix, named after their Cognito username. IAM enforces strict
isolation — a user can only ever read, write, or list their own prefix.

```
s3://user-space/
  alice/                          ← alice's root, only alice can access
    documents/
      report.pdf
    .config/
      connections.json            ← alice's saved Bucket 2 connection configs
  bob/                            ← bob's root, only bob can access
    images/
      photo.png
    .config/
      connections.json
```

**IAM policy statement (on the shared portal role):**

`${aws:PrincipalTag/username}` expands at evaluation time to the value of the `username`
principal tag stamped by the Identity Pool at credential issuance. This scopes every user to their own
prefix with a single policy statement — no per-user policy changes needed.

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::user-space",
    "arn:aws:s3:::user-space/${aws:PrincipalTag/username}/*"
  ],
  "Condition": {
    "StringLike": {
      "s3:prefix": ["${aws:PrincipalTag/username}/*", ""]
    }
  }
}
```

**How file operations map onto these actions (SPEC-015→020):**

The four actions above already cover almost the entire filesystem experience —
only multipart needs more:

- **Download** (SPEC-015): presigned `GetObject` — covered by `s3:GetObject`.
- **Metadata** (SPEC-017): `HeadObject` — authorized by `s3:GetObject`.
- **Upload / create folder** (SPEC-016): uses the managed `@aws-sdk/lib-storage`
  `Upload` — single `PutObject` below a 5 MiB part-size threshold, **automatic
  multipart above it**. `CreateMultipartUpload`/`UploadPart`/`CompleteMultipartUpload`
  are authorized by `s3:PutObject`, but the policy must **additionally** grant
  `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads`, and
  `s3:ListMultipartUploadParts` — added in SPEC-016. SPEC-016 also adds a bucket
  lifecycle rule aborting incomplete multipart uploads after 7 days (the first
  lifecycle rule on the user-space bucket; SPEC-010 deferred these).
- **Delete** (SPEC-018): `DeleteObject` / `DeleteObjects` — covered (except the
  `*/DO_NOT_DELETE.txt` deny in SPEC-013 FR-001).
- **Move / rename** (SPEC-019): `CopyObject` + `DeleteObject`. A same-bucket copy
  needs `s3:GetObject` (source) + `s3:PutObject` (destination), both inside the
  user's own prefix — **no new IAM**. There is no S3 move/rename; the app presents
  them but performs copy-then-delete (recursive and non-atomic for folders).
- **Upload queue** (SPEC-020): multi-file queue + per-file cancel on top of the
  SPEC-016 uploader — **no new IAM** (`s3:AbortMultipartUpload` already granted in
  SPEC-016 covers cancel).

**Frontend prefix derivation:**
```ts
import { getCurrentUser } from 'aws-amplify/auth';
const { username } = await getCurrentUser();
const userSpaceRootPrefix = `${username}/`;
const configKey = `${username}/.config/connections.json`;
```

---

### Bucket 2 — Shared Space

> **Status: access model redesigned — not yet specced or built.**
>
> The original design (daily Terraform-managed IAM policy deployment) has been replaced.
> The new model is **user-managed access keys**: a user can create a key for a prefix
> and grant or revoke access to that key for other users. This will likely require a
> backend service or cloud process. The exact design, spec, and implementation are pending.
>
> **Do not build anything referencing the old daily-IAM-pipeline model.** When the shared
> bucket spec is written it will define the new access mechanism from scratch.

The prefix structure remains the same concept — users access named prefixes in a shared
bucket — but the mechanism for controlling that access is TBD.

```
s3://shared-space/
  project-alpha/                  ← example prefix; access control model TBD
    data/
      results.csv
  project-beta/
    reports/
      summary.pdf
```

**Frontend prefix discovery** will work similarly to the original design — users configure
which prefixes they connect to via the Connection Manager UI, and the app validates access
before saving — but the underlying IAM or key-based mechanism that enforces this is part
of the future spec.

---

## Connection Configuration

User-configured Bucket 2 connections are stored as a single JSON file in the user's
user-space prefix. The file is read on app load and written any time connections are
added, validated, or removed.

**S3 key:** `{username}/.config/connections.json`

**Schema:**
```ts
// src/types/connection.types.ts

export type BucketConnection = {
  id: string;               // uuid — stable identifier for this connection
  label: string;            // user-provided display name, e.g. "Project Alpha Data"
  bucket: string;           // S3 bucket name (always VITE_S3_SHARED_SPACE_BUCKET for now)
  prefix: string;           // e.g. "project-alpha/"
  region: string;           // AWS region of the bucket
  validatedAt: string;      // ISO timestamp of last successful validation
  createdAt: string;        // ISO timestamp of initial save
};

export type ConnectionConfig = {
  version: 1;
  connections: BucketConnection[];
};
```

**Read on load:**
```ts
// On app init, after auth — load saved connections
const key = `${username}/.config/connections.json`;
const result = await getObject({ bucket: userSpaceBucket, key });
const config: ConnectionConfig = result.success ? JSON.parse(result.data) : { version: 1, connections: [] };
```

**Write on change:**
```ts
// After adding/removing a connection
await putObject({
  bucket: userSpaceBucket,
  key: `${username}/.config/connections.json`,
  body: JSON.stringify(config),
  contentType: 'application/json',
});
```

**Connection validation flow:**
```
User enters: bucket prefix → "project-alpha/"
      │
      └─ App attempts: ListObjectsV2 on shared-space with prefix "project-alpha/"
             │
             ├─ Success (even empty) → connection is valid → save to connections.json
             │
             └─ AccessDenied / error → connection rejected → show error, do not save
```

---

## AWS Resource Inventory

> Fill in actual values as resources are provisioned. Use placeholders until then.
> **IaC coverage note:** Resources marked ✓ IaC are managed by `infra/` (SPEC-003). Resources marked ✗ IaC must be provisioned manually or via a future IaC spec before the app can run in production.

| Resource | Name / ARN Pattern | Purpose | IaC | Notes |
|---|---|---|---|---|
| Cognito User Pool | `us-east-1_XXXXXXXXX` | Standalone auth (native users) | ✓ SPEC-006 (draft) | Hosts the login UI; pre-signup Lambda (SPEC-012) |
| Lambda — Pre-Signup Trigger | `{project}-{env}-pre-signup` | Validates username `^[a-zA-Z0-9._@-]{3,64}$` at signup | ✓ SPEC-012 | python3.12; logs-only exec role; 14-day log retention; no AWS API calls. TF bootstraps a placeholder; CI (`deploy-lambdas.yml`) deploys the real code |
| S3 Bucket — Lambda Artifacts | `{project}-lambda-artifacts-{accountId}` | Staging for Lambda code packages built by CI | ✓ SPEC-012 | Private; 30-day expiry; `deploy-lambdas.yml` uploads zips, `update-function-code` reads them |
| Cognito User Pool Client | `XXXXXXXXXXXXXXXXXXXXXXXXXX` | App client for Amplify | ✓ SPEC-006 (draft) | No client secret (SPA) |
| Cognito Identity Pool | `us-east-1:xxxx-...` | Exchanges User Pool token for AWS credentials; maps username claim → `username` principal tag | ✓ SPEC-011 (draft) | Authenticated identities only; enhanced flow |
| IAM Role (shared) | `arn:aws:iam:::role/{project}-portal-user-role` | S3 access for all authenticated users | ✓ SPEC-011 (draft) | Single role; trusts the Identity Pool; per-user isolation via principal tags |
| S3 Bucket — User Space | `dat-prod-user-space` | Per-user private files + connection config | ✓ SPEC-010 (draft) | CORS required |
| S3 Bucket — Shared Space | `shared-space-bucket-name` | Shared prefixes; access model TBD | ✗ future spec | CORS required |
| S3 Bucket — Static Assets | `portal-static-assets` | Hosts built SPA files | ✓ SPEC-003 | Private; accessed via CloudFront OAC only |
| CloudFront Distribution | `*.cloudfront.net` / custom domain | Serves the SPA; routes all paths to index.html | ✓ SPEC-003 | OAC origin; custom error response 403/404 → index.html |
| GitHub Actions OIDC Role | `arn:aws:iam:::role/S3PortalDeployRole` | Allows CI/CD to deploy without stored credentials | ✓ SPEC-003 | Scoped to main branch of repo |
| ACM Certificate | `arn:aws:acm:us-east-1:...` | HTTPS for custom domain | ✗ manual | Must be in us-east-1 for CloudFront; DNS validation is manual |


> Note: A Cognito Identity Pool performs the token-for-credentials exchange and stamps
> the `username` principal tag server-side (attributes for access control). Per-user S3
> isolation is enforced via that tag on a single shared role, not separate roles.

---

## Amplify Configuration

Amplify is initialized once in `src/lib/amplify.ts` and imported at the top of `src/main.tsx`
before the React tree mounts. The `identityPoolId` makes Amplify perform the Identity Pool
credential exchange automatically.

```ts
// src/lib/amplify.ts
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID,
      identityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID,
      loginWith: {
        oauth: {
          domain: import.meta.env.VITE_COGNITO_DOMAIN,
          scopes: ['openid', 'email', 'profile'],
          redirectSignIn: [import.meta.env.VITE_APP_URL],
          redirectSignOut: [import.meta.env.VITE_APP_URL],
          responseType: 'code',
        },
      },
    },
  },
});
```

```ts
// src/main.tsx
import './lib/amplify'; // must be first import
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
```

---

## S3 Client Configuration

The S3 client uses credentials from `fetchAuthSession()` post-auth. With the Identity Pool
configured in Amplify, `session.credentials` is populated automatically — no STS SDK and no
manual role assumption (SPEC-011).

```ts
// src/lib/s3Client.ts — post-auth pattern (SPEC-011)
import { S3Client } from '@aws-sdk/client-s3';
import { fetchAuthSession } from 'aws-amplify/auth';

export async function getS3Client(
  forceRefresh = false
): Promise<ServiceResult<S3Client>> {
  const session = await fetchAuthSession({ forceRefresh });
  if (!session.credentials) {
    return {
      success: false,
      error: { message: 'No AWS credentials — sign in required' },
    };
  }
  return {
    success: true,
    data: new S3Client({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: session.credentials,
    }),
  };
}
```

> On S3 calls failing with credential-expiry errors, retry once with
> `getS3Client(true)` — Amplify refreshes the underlying session and credentials.
>
> **Username constraint:** the username is the S3 prefix and `username` tag value. It is
> enforced at signup as `^[a-zA-Z0-9._@-]{3,64}$` by the SPEC-012 pre-signup Lambda, and
> the User Pool is case-insensitive (SPEC-006).

---

## Environment Variables

Full map of all `VITE_` variables. Every variable must also appear in `.env.example`.

| Variable | Used By | Dev Value | Notes |
|---|---|---|---|
| `VITE_AWS_REGION` | S3 client, STS, Amplify | `us-east-1` | Must match all resource regions |
| `VITE_AWS_ACCESS_KEY_ID` | S3 client (SPEC-001 dev only) | IAM user key | Temporary — removed when auth spec lands |
| `VITE_AWS_SECRET_ACCESS_KEY` | S3 client (SPEC-001 dev only) | IAM user secret | Temporary — removed when auth spec lands |
| `VITE_S3_USER_SPACE_BUCKET` | S3 service functions | `user-space-bucket-name` | Bucket 1 — user files + config |
| `VITE_S3_SHARED_SPACE_BUCKET` | S3 service functions | `shared-space-bucket-name` | Bucket 2 — shared-space |
| `VITE_COGNITO_IDENTITY_POOL_ID` | Amplify config (credential exchange) | `us-east-1:xxxx-...` | Identity Pool — replaces the former `VITE_IAM_ROLE_ARN` |
| `VITE_COGNITO_USER_POOL_ID` | Amplify config | `us-east-1_XXXXXX` | — |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | Amplify config | `XXXXXXXXXX` | — |
| `VITE_COGNITO_DOMAIN` | Amplify OAuth config | `your-domain.auth.us-east-1.amazoncognito.com` | — |
| `VITE_APP_URL` | Amplify redirect URLs | `http://localhost:5173` | Changes per environment |

---

## S3 CORS Configuration

**Both buckets** require CORS configuration before any browser SDK calls will work.
Apply this in the AWS Console or via Terraform for each bucket.

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
    "AllowedOrigins": [
      "http://localhost:5173",
      "https://your-production-domain.com"
    ],
    "ExposeHeaders": [
      "ETag",
      "x-amz-server-side-encryption",
      "x-amz-request-id",
      "x-amz-id-2"
    ],
    "MaxAgeSeconds": 3000
  }
]
```

> ⚠️ Without this CORS config, all S3 SDK calls will fail in the browser with a network
> error. This is the most common first-time setup issue. Verify it before debugging SDK code.

---

## Deployment

The SPA is deployed as static files to S3 and served via CloudFront. There is no server to
manage — all compute runs in the browser.

### Build and release flow

```
Git push (main / release branch)
        ↓
CI/CD pipeline (GitHub Actions or CodePipeline + CodeBuild)
        ↓  npm run build
        │    VITE_ vars injected from pipeline secrets or SSM Parameter Store
        ↓  aws s3 sync dist/ s3://portal-static-assets/ --delete
        ↓  aws cloudfront create-invalidation --paths "/*"
CloudFront distribution (serves index.html for all routes)
        ↓
Users (corporate browsers)
```

### CloudFront configuration requirements

| Setting | Value | Why |
|---|---|---|
| Origin | S3 bucket via OAC (not public) | Prevents direct S3 access; only CloudFront can read |
| Viewer protocol | Redirect HTTP to HTTPS | Security |
| Custom error response | 403 → `/index.html`, HTTP 200 | Enables SPA client-side routing on direct URL or refresh |
| Custom error response | 404 → `/index.html`, HTTP 200 | Same |
| Default root object | `index.html` | Serves the app at the root path |

> ⚠️ Without the custom error responses for 403/404, any page refresh or direct URL navigation
> will return a raw S3 error rather than the app.

### Environment-specific config

Build-time `VITE_*` env vars (Cognito pool ID, bucket names, region, app URL) are the same
for all users of a given environment. They are injected once per build and baked into the JS
bundle. Store them in your CI/CD system's secret store or AWS SSM Parameter Store — do not
commit values to the repository.

The per-user IAM role ARN is **not** a build-time variable — it is read from the user's
Cognito token at runtime. (A Cognito Custom Attributes section will be written as part of
the auth spec — not yet documented.)

### Environments

| Environment | `VITE_APP_URL` | Notes |
|---|---|---|
| Local dev | `http://localhost:5173` | Uses static IAM credentials or anonymous (unsigned) requests against a test bucket. Auth not implemented. |
| Production | `https://your-custom-domain.com` | Deployed via CI/CD; CloudFront + ACM cert |

Add staging environment here when it is provisioned.

---

## Known Constraints

- **No backend / API proxy.** All AWS calls come from the browser. If a use case arises
  that requires elevated permissions beyond what user-scoped IAM can express, a Lambda or
  API Gateway layer would need to be added — treat this as a significant architecture change.
- **Bucket 2 access model is TBD.** The original daily-IAM-pipeline design has been abandoned. The replacement is user-managed access keys with a backend service or cloud process. Do not implement anything for Bucket 2 access management until the spec is written.
- **connections.json is the user's own data.** If a user manually deletes or corrupts it,
  their connections are lost. The UI should handle a missing config file as an empty state,
  not an error.
- **SPA with client-side routing.** If deployed to S3 + CloudFront, CloudFront must serve
  `index.html` for all routes (configure custom error response for 403/404).
- **Usernames are constrained at signup.** The username is the S3 prefix and `username`
  principal tag value; the SPEC-012 pre-signup Lambda enforces `^[a-zA-Z0-9._@-]{3,64}$`
  and the pool is case-insensitive (SPEC-006).
- **Shared bucket access model is TBD.** The single-role + principal-tag approach changes how
  per-user prefix grants on Bucket 2 can be expressed. To be resolved in the shared-space spec.
- **File size limits.** SPEC-016 uploads via the managed `@aws-sdk/lib-storage`
  `Upload` (single request below a 5 MiB part-size threshold, automatic multipart
  above it), with a configurable max (default 5 GiB, `VITE_MAX_UPLOAD_BYTES`).
  SPEC-020 adds the multi-file queue + cancel on top — no new size mechanics.
- **Move and rename are non-atomic.** S3 has neither operation. The portal presents them
  but performs `CopyObject` + `DeleteObject` (rename = move within the same parent). For a
  folder this is *recursive* over every contained key and can *partially fail* — a per-key
  copy failure must never delete that source and must never abort the remaining keys
  (SPEC-019). The same is true of recursive folder delete (SPEC-018). There is no
  transactional rollback; the UI reports which keys succeeded and which failed.
- **No overwrite protection from S3.** Versioning is off (SPEC-010), so writing an existing
  key destroys the prior object. The app guards this in the UI with warn-and-confirm
  (HEAD-check → Overwrite or Rename) on upload and move/rename (SPEC-016/019) — there is no
  server-side safety net.
- **Listing pagination.** `ListObjectsV2` returns at most 1,000 keys per call. The browser
  paginates with `ContinuationToken` via TanStack Query's `useInfiniteQuery` and a "Load
  more" control (SPEC-015); code must never assume a single page is the whole folder.

---

## Deferred / Future Scope

- File preview (PDF, image rendering in-browser)
- Admin UI (user management, access audit)
- Audit logging (S3 access logs, CloudTrail)
- Staging environment and environment promotion pipeline
- Real-time access revocation (would require backend)
- Shared-space (Bucket 2) access model with single-role + session tag architecture

---

## Spec Roadmap

| Spec | Feature | Status |
|---|---|---|
| SPEC-001 | File listing against test bucket (no auth) | Completed |
| SPEC-002 | Public bucket file browser — root prefix scoping, anonymous client fallback | Completed |
| SPEC-003 | OpenTofu IaC — static assets S3, CloudFront, GitHub Actions OIDC role | Completed (not yet applied to AWS) |
| SPEC-004 | GitHub Actions CI — test + build | Completed |
| SPEC-005 | Deploy app to AWS — GitHub Actions deploy workflows (app + infra) | Completed |
| SPEC-006 | Cognito User Pool IaC — `infra/modules/auth/` (pool, SPA client, Hosted UI domain) | Draft |
| SPEC-007 | Login flow — Hosted UI redirect + Amplify v6 session management | Draft |
| SPEC-008 | Auth-gated layout — react-router, protected `/files` route | Draft |
| SPEC-009 | Sign-up end to end — Hosted UI signup, email verification, E2E acceptance script | Draft |
| SPEC-010 | User-space bucket IaC — `infra/modules/data/` (bucket, CORS, encryption) | Draft |
| SPEC-011 | Scoped credentials — Identity Pool ABAC + portal role (trust only, no S3 perms) | Draft |
| SPEC-012 | Pre-signup username validation — Cognito trigger Lambda | Completed |
| SPEC-013 | Prefix-scoped role policy + file browser switchover to user-space bucket | Completed |
| SPEC-014 | User prefix marker — app writes `{username}/DO_NOT_DELETE.txt` on first login | Completed |
| SPEC-015 | File download + data foundation (TanStack Query, pagination, presigned URLs) | Completed |
| SPEC-016 | File upload (managed, auto-multipart + progress) + create folder | Draft |
| SPEC-017 | File metadata panel (HeadObject) | Draft |
| SPEC-018 | Delete files and folders (multi-select, recursive) | Draft |
| SPEC-019 | Move & rename (files and folders) — copy+delete | Draft |
| SPEC-020 | Upload queue (multi-file, concurrency, cancel) | Draft |
| Future | Shared-space bucket (Bucket 2) — user-managed access keys, model TBD | Not yet written |