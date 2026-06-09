# Architecture: S3 File Portal

**Last Updated:** 2026-05-23 (single shared role + session tags)  
**Status:** Living document — update as decisions are made.

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
control mechanisms. Bucket 1 (personal) is self-contained — IAM enforces per-user prefix
isolation using the Cognito username. Bucket 2 (shared) access is governed by IAM policies
that are managed by a separate IaC process. Access to these prefixes is dynamic and can change frequently.

**User-configured connections.** Users configure which Bucket 2 prefixes they connect to
themselves via the UI. The app validates access before saving. Connection configurations
are stored as JSON within the user's own prefix in Bucket 1 — no separate datastore
(DynamoDB, RDS, etc.) is needed.

---

## System Diagram

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
   │  (AD-fed)   │              │ (Personal)  │   │  (Shared)   │
   └──────┬──────┘              │             │   │             │
          │                     │ {username}/ │   │ {prefix}/   │
          │ JWT                 │  files/     │   │  files/     │
          ▼                     │  .config/   │   │             │
   ┌─────────────┐              │   connections│  │             │
   │     STS     │              │   .json     │   │             │
   │ AssumeRole  │              └─────────────┘   └──────┬──────┘
   │ WithWebId   │                                       │
   └──────┬──────┘                              ┌────────▼────────┐
          │                                     │   Terraform     │
          ▼                                     │   IaC Pipeline  │
   ┌─────────────┐                              │ (daily deploy)  │
   │  IAM Role   │                              │                 │
   │ (trust: UP) │──────────────────────────────│ manages IAM     │
   └─────────────┘                              │ prefix grants   │
                                                └─────────────────┘
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

> **MVP note:** Active Directory federation is the target production architecture but is not
> required for initial development. The MVP uses native Cognito User Pool users
> (username + password). The token shape and STS flow are identical — AD federation is an
> infrastructure concern that does not change any frontend code.

```
1. User lands on app → Amplify checks for active session
      │
      ├─ Session exists → Use cached/refreshed JWT → Re-assume IAM role → Load app
      │
      └─ No session → Redirect to Cognito Hosted UI

2. Cognito Hosted UI → User enters AD credentials
      │
      └─ Cognito federates to Active Directory via SAML/OIDC
             │
             └─ AD validates credentials → Returns group memberships as claims
                    │
                    └─ Cognito issues JWT (id_token, access_token, refresh_token)

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

### Bucket 1 — Personal Bucket

Each user has exactly one prefix, named after their Cognito username. IAM enforces strict
isolation — a user can only ever read, write, or list their own prefix.

```
s3://personal-bucket/
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
    "arn:aws:s3:::personal-bucket",
    "arn:aws:s3:::personal-bucket/${aws:PrincipalTag/username}/*"
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
const personalRootPrefix = `${username}/`;
const configKey = `${username}/.config/connections.json`;
```

---

### Bucket 2 — Shared Bucket

> **Status: access model under review.** The switch to a single shared role with session
> tags changes how per-user prefix grants on Bucket 2 can be expressed in IAM. This section
> will be updated when the shared bucket spec is written.

Users can access one or more prefixes in this bucket. Access is granted and revoked by a
Terraform IaC pipeline that runs on a daily deployment cycle.

```
s3://shared-bucket/
  project-alpha/                  ← alice and bob both have IAM access
    data/
      results.csv
  project-beta/                   ← only alice has IAM access
    reports/
      summary.pdf
  project-gamma/                  ← alice's access was revoked in last Terraform deploy
```

**Access cadence:** Changes to access take effect on the next daily Terraform deployment.
Real-time revocation is not supported in this architecture.

**Terraform-managed IAM policy statement example (per user, per prefix):**
```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::shared-bucket",
    "arn:aws:s3:::shared-bucket/project-alpha/*",
    "arn:aws:s3:::shared-bucket/project-beta/*"
  ],
  "Condition": {
    "StringLike": {
      "s3:prefix": ["project-alpha/*", "project-beta/*", ""]
    }
  }
}
```

**Frontend prefix discovery:** The user manually configures which Bucket 2 prefixes they
want to connect to via the Connection Manager UI. The app attempts to list the given prefix;
if IAM denies it, the connection is rejected and not saved. Saved connections are persisted
to `{username}/.config/connections.json` in Bucket 1.

This means the IAM policy is the source of truth for access — the frontend never assumes
a connection is valid, it always validates against the live bucket.

---

## Connection Configuration

User-configured Bucket 2 connections are stored as a single JSON file in the user's
personal prefix. The file is read on app load and written any time connections are
added, validated, or removed.

**S3 key:** `{username}/.config/connections.json`

**Schema:**
```ts
// src/types/connection.types.ts

export type BucketConnection = {
  id: string;               // uuid — stable identifier for this connection
  label: string;            // user-provided display name, e.g. "Project Alpha Data"
  bucket: string;           // S3 bucket name (always VITE_S3_SHARED_BUCKET for now)
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
const result = await getObject({ bucket: personalBucket, key });
const config: ConnectionConfig = result.success ? JSON.parse(result.data) : { version: 1, connections: [] };
```

**Write on change:**
```ts
// After adding/removing a connection
await putObject({
  bucket: personalBucket,
  key: `${username}/.config/connections.json`,
  body: JSON.stringify(config),
  contentType: 'application/json',
});
```

**Connection validation flow:**
```
User enters: bucket prefix → "project-alpha/"
      │
      └─ App attempts: ListObjectsV2 on shared-bucket with prefix "project-alpha/"
             │
             ├─ Success (even empty) → connection is valid → save to connections.json
             │
             └─ AccessDenied / error → connection rejected → show error, do not save
```

---

## AWS Resource Inventory

> Fill in actual values as resources are provisioned. Use placeholders until then.

| Resource | Name / ARN Pattern | Purpose | Notes |
|---|---|---|---|
| Cognito User Pool | `us-east-1_XXXXXXXXX` | Auth + AD federation | Hosts the login UI |
| Cognito User Pool Client | `XXXXXXXXXXXXXXXXXXXXXXXXXX` | App client for Amplify | No client secret (SPA) |
| IAM Role (shared) | `arn:aws:iam:::role/S3PortalRole` | S3 access for all authenticated users | Single role; per-user isolation via session tags |
| S3 Bucket — Personal | `personal-bucket-name` | Per-user private files + connection config | CORS required |
| S3 Bucket — Shared | `shared-bucket-name` | Terraform-managed shared prefixes | CORS required |
| S3 Bucket — Static Assets | `portal-static-assets` | Hosts built SPA files | Private; accessed via CloudFront OAC only |
| CloudFront Distribution | `*.cloudfront.net` / custom domain | Serves the SPA; routes all paths to index.html | OAC origin; custom error response 403/404 → index.html |
| ACM Certificate | `arn:aws:acm:us-east-1:...` | HTTPS for custom domain | Must be in us-east-1 for CloudFront |
| Terraform IaC Pipeline | External — daily deploy | Manages IAM prefix grants on Shared bucket; sets `custom:iamRoleArn` on users | Owned by same team |
| Active Directory | External — managed by IT | Identity provider | Federated via SAML/OIDC into Cognito |

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
| `VITE_S3_PERSONAL_BUCKET` | S3 service functions | `personal-bucket-name` | Bucket 1 — personal files + config |
| `VITE_S3_SHARED_BUCKET` | S3 service functions | `shared-bucket-name` | Bucket 2 — Terraform-managed |
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
Cognito token at runtime (see Cognito Custom Attributes section).

### Environments

| Environment | `VITE_APP_URL` | Notes |
|---|---|---|
| Local dev | `http://localhost:5173` | Uses static IAM credentials until auth spec lands |
| Production | `https://your-custom-domain.com` | Deployed via CI/CD; CloudFront + ACM cert |

Add staging environment here when it is provisioned.

---

## Known Constraints

- **No backend / API proxy.** All AWS calls come from the browser. If a use case arises
  that requires elevated permissions beyond what user-scoped IAM can express, a Lambda or
  API Gateway layer would need to be added — treat this as a significant architecture change.
- **Bucket 2 access is real-time.** Users whose access is revoked
  will lose it immediately. The UI should not present access as
  guaranteed; connection validation happens on load but reflects IAM state at that moment.
- **connections.json is the user's own data.** If a user manually deletes or corrupts it,
  their connections are lost. The UI should handle a missing config file as an empty state,
  not an error.
- **SPA with client-side routing.** If deployed to S3 + CloudFront, CloudFront must serve
  `index.html` for all routes (configure custom error response for 403/404).
- **Session tag username must satisfy RoleSessionName constraints.** Max 64 characters;
  allowed chars: `a-z A-Z 0-9 = , . @ - _`. Standard email-format usernames are within the
  allowed set. Validate this when real Cognito users are provisioned.
- **Shared bucket access model is TBD.** The single-role + session tag approach changes how
  per-user prefix grants on Bucket 2 can be expressed. To be resolved in the shared bucket spec.
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
- Shared bucket (Bucket 2) access model with single-role + session tag architecture
- AD federation via SAML/OIDC into Cognito (infrastructure concern; no frontend changes needed)

---

## Spec Roadmap

| Spec | Feature | Status |
|---|---|---|
| SPEC-001 | Personal bucket — file listing (no auth) | Completed |
| Future specs | TBD — defined incrementally as work is planned | Not yet written |