# Architecture: S3 File Portal

**Last Updated:** 2026-06-10 (Cognito standalone — AD federation removed; bucket concepts renamed to user-space/shared-space)  
**Status:** Living document — update as decisions are made.

> **Implementation status as of 2026-06-08:**
> - **Built and working:** File browser (SPEC-001, SPEC-002) — React SPA in `apps/portal/`, browses a test bucket using static or anonymous credentials.
> - **IaC written, not yet applied:** OpenTofu config for static assets S3 bucket, CloudFront, and GitHub Actions OIDC role (SPEC-003). `tofu apply` has not been run against a real AWS account.
> - **Not yet built:** Authentication (Cognito + Amplify + STS), user-space/shared-space S3 data buckets, IAM portal role, shared-space access management, GitHub Actions CI/CD pipeline (SPEC-004).
> - **Under redesign:** Bucket 2 access model — see Key Decisions section in CLAUDE.md.

## System Overview

A single-page application (SPA) that allows authenticated users to manage files in AWS S3.
There is **no backend server**. All AWS API calls are made directly from the browser using
temporary IAM credentials obtained by assuming a single shared IAM role via Web Identity
federation from the Cognito User Pool JWT. No Cognito Identity Pool is required.

Per-user access isolation is achieved through **IAM session tags** — the app passes the
Cognito username as a session tag when assuming the role, and the role's permission policy
uses `${aws:PrincipalTag/username}` to scope each user to their own S3 prefix. No per-user
IAM roles are needed.

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
   │     STS     │              │   .json     │   │             │
   │ AssumeRole  │              └─────────────┘   └──────┬──────┘
   │ WithWebId   │                                       │
   └──────┬──────┘                              ┌────────▼────────┐
          │                                     │  Bucket 2 Access│
          ▼                                     │  Mgmt (TBD:     │
   ┌─────────────┐                              │  user-managed   │
   │  IAM Role   │                              │  keys, backend  │
   │ (trust: UP) │                              │  TBD)           │
   └─────────────┘                              └─────────────────┘
```

**Key architectural principles:**
- The browser holds temporary STS credentials issued by assuming a single shared IAM role
  via the Cognito User Pool JWT (Web Identity federation). No Identity Pool needed.
- All users assume the same role. Per-user isolation is enforced by passing the Cognito
  username as a session tag (`username`) on every `AssumeRoleWithWebIdentity` call. The
  role's permission policy uses `${aws:PrincipalTag/username}` to scope S3 access.
- The IAM role trust policy accepts tokens from this account's Cognito User Pool and
  explicitly permits `sts:TagSession` so session tags are accepted.
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

3. App reads Cognito username → calls STS AssumeRoleWithWebIdentity manually
      │    passing: id_token, shared role ARN (env var), username as session tag
      │
      └─ STS validates JWT against User Pool OIDC endpoint
             │
             └─ Trust policy on role confirms: issuer = this User Pool ✓
                    │
                    └─ STS stamps session tag { username: "alice" } onto credentials
                           │
                           └─ STS issues temporary credentials (1hr TTL)
                                  │
                                  └─ App stores credentials in memory
                                         │
                                         └─ Passed to S3Client on each request
                                                │
                                                └─ IAM evaluates ${aws:PrincipalTag/username}
                                                   scoping S3 access to alice's prefix only
```

### IAM Role Trust Policy

The role trust policy grants `sts:AssumeRoleWithWebIdentity` and `sts:TagSession` to tokens
issued by this account's Cognito User Pool, scoped to authenticated users only.
`sts:TagSession` is required — without it, STS will reject the call when session tags are
passed, causing auth to fail silently.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "cognito-idp.{region}.amazonaws.com/{userPoolId}"
      },
      "Action": [
        "sts:AssumeRoleWithWebIdentity",
        "sts:TagSession"
      ],
      "Condition": {
        "StringEquals": {
          "cognito-idp.{region}.amazonaws.com/{userPoolId}:aud": "{userPoolClientId}"
        },
        "ForAnyValue:StringLike": {
          "cognito-idp.{region}.amazonaws.com/{userPoolId}:amr": "authenticated"
        }
      }
    }
  ]
}
```

### Token lifecycle
- Amplify handles JWT refresh automatically via the refresh_token
- STS credentials must be re-assumed when they expire (1hr TTL) — handle this by
  calling `fetchAuthSession({ forceRefresh: true })` before SDK operations that fail
  with credential expiry errors
- No manual token management needed in application code outside of this pattern

### Relevant Amplify calls
```ts
// Get current session — use to extract the id token string for the STS call
import { fetchAuthSession } from 'aws-amplify/auth';
const session = await fetchAuthSession();
const idTokenString = session.tokens?.idToken?.toString(); // passed to STS

// Get current user — provides the username used as session tag and S3 prefix
import { getCurrentUser } from 'aws-amplify/auth';
const { username } = await getCurrentUser();

// Force JWT refresh (call when STS credentials have expired, then re-assume role)
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
session tag passed during `AssumeRoleWithWebIdentity`. This scopes every user to their own
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
| Cognito User Pool | `us-east-1_XXXXXXXXX` | Standalone auth (native users) | ✗ future spec | Hosts the login UI |
| Cognito User Pool Client | `XXXXXXXXXXXXXXXXXXXXXXXXXX` | App client for Amplify | ✗ future spec | No client secret (SPA) |
| IAM Role (shared) | `arn:aws:iam:::role/S3PortalRole` | S3 access for all authenticated users | ✗ future spec | Single role; per-user isolation via session tags |
| S3 Bucket — User Space | `user-space-bucket-name` | Per-user private files + connection config | ✗ future spec | CORS required |
| S3 Bucket — Shared Space | `shared-space-bucket-name` | Shared prefixes; access model TBD | ✗ future spec | CORS required |
| S3 Bucket — Static Assets | `portal-static-assets` | Hosts built SPA files | ✓ SPEC-003 | Private; accessed via CloudFront OAC only |
| CloudFront Distribution | `*.cloudfront.net` / custom domain | Serves the SPA; routes all paths to index.html | ✓ SPEC-003 | OAC origin; custom error response 403/404 → index.html |
| GitHub Actions OIDC Role | `arn:aws:iam:::role/S3PortalDeployRole` | Allows CI/CD to deploy without stored credentials | ✓ SPEC-003 | Scoped to main branch of repo |
| ACM Certificate | `arn:aws:acm:us-east-1:...` | HTTPS for custom domain | ✗ manual | Must be in us-east-1 for CloudFront; DNS validation is manual |


> Note: No Cognito Identity Pool is used. Web Identity federation is performed directly
> against a single shared IAM role using the User Pool JWT. Per-user S3 isolation is
> enforced via IAM session tags, not separate roles.

---

## Amplify Configuration

Amplify is initialized once in `src/lib/amplify.ts` and imported at the top of `src/main.tsx`
before the React tree mounts. No Identity Pool configuration is needed.

```ts
// src/lib/amplify.ts
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID,
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

The S3 client uses credentials from `fetchAuthSession()` post-auth. The client must be
reconstructed (or credentials refreshed) when STS credentials expire.

Amplify v6 does **not** populate `session.credentials` unless an Identity Pool is configured.
Since this architecture uses direct Web Identity federation (no Identity Pool), the STS call
must be made manually after obtaining the JWT from Amplify.

```ts
// src/lib/s3Client.ts — post-auth pattern
import { S3Client } from '@aws-sdk/client-s3';
import { STSClient, AssumeRoleWithWebIdentityCommand } from '@aws-sdk/client-sts';
import { fetchAuthSession, getCurrentUser } from 'aws-amplify/auth';

export async function getS3Client(forceRefresh = false): Promise<S3Client> {
  const [session, { username }] = await Promise.all([
    fetchAuthSession({ forceRefresh }),
    getCurrentUser(),
  ]);

  const idTokenString = session.tokens?.idToken?.toString();
  if (!idTokenString) throw new Error('No id token — user may not be authenticated');

  const sts = new STSClient({ region: import.meta.env.VITE_AWS_REGION });
  const { Credentials } = await sts.send(new AssumeRoleWithWebIdentityCommand({
    RoleArn: import.meta.env.VITE_IAM_ROLE_ARN,
    RoleSessionName: username,          // appears in CloudTrail — human-readable audit trail
    WebIdentityToken: idTokenString,
    Tags: [{ Key: 'username', Value: username }], // drives ${aws:PrincipalTag/username} in policies
  }));
  if (!Credentials) throw new Error('STS returned no credentials');

  return new S3Client({
    region: import.meta.env.VITE_AWS_REGION,
    credentials: {
      accessKeyId: Credentials.AccessKeyId!,
      secretAccessKey: Credentials.SecretAccessKey!,
      sessionToken: Credentials.SessionToken,
      expiration: Credentials.Expiration,
    },
  });
}
```

> **RoleSessionName constraint:** Max 64 characters, allowed chars: `a-z A-Z 0-9 = , . @ - _`.
> Standard email-format usernames (`alice.smith@company.com`) are within the allowed character
> set but verify length. If usernames can exceed 64 chars, truncate or hash before passing.
>
> Note: `@aws-sdk/client-sts` must be added as a dependency when this pattern is implemented.

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
| `VITE_IAM_ROLE_ARN` | STS role assumption | `arn:aws:iam::123456789:role/S3PortalRole` | Single shared role — same for all users |
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
- **Session tag username must satisfy RoleSessionName constraints.** Max 64 characters;
  allowed chars: `a-z A-Z 0-9 = , . @ - _`. Standard email-format usernames are within the
  allowed set. Validate this when real Cognito users are provisioned.
- **Shared bucket access model is TBD.** The single-role + session tag approach changes how
  per-user prefix grants on Bucket 2 can be expressed. To be resolved in the shared-space spec.
- **File size limits.** For files over ~5MB, multipart upload should be used. Initial upload
  spec will enforce a simple size cap; multipart is a later enhancement.

---

## Deferred / Future Scope

- Multipart upload for large files
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
| SPEC-004 | GitHub Actions deploy pipeline — SPA build+deploy, IaC plan/apply with approval gate | Draft |
| Future | Authentication — Cognito + Amplify + STS, personal prefix scoping | Not yet written |
| Future | Data infrastructure IaC — Cognito User Pool, IAM portal role, personal/shared S3 buckets | Not yet written |
| Future | Bucket 2 access management — user-managed keys, backend TBD | Not yet written |
| Future | File upload, download, delete | Not yet written |