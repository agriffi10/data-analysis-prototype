# Completed Spec - Prefix-Scoped S3 Access + File Browser Switchover

## What was completed from this spec?

Real, isolated per-user S3 access is now on. The shared portal role carries a
prefix-scoped permission policy driven by the `username` principal tag (stamped
server-side by the Identity Pool, SPEC-011), a defense-in-depth bucket policy
locks the user-space bucket to that role, and the file browser now shows the
authenticated user their own space — rooted at `{username}/`, with the username
hidden from the UI.

**Phase 1 — IaC (merged [#26](https://github.com/agriffi10/data-analysis-prototype/pull/26)):**
- **`infra/modules/data/policies/portal-role-permissions.json.tftpl`** + attachment in `iam.tf` (FR-001): `s3:GetObject/PutObject/DeleteObject` on `<bucket>/${aws:PrincipalTag/username}/*`; `s3:ListBucket` gated by `s3:prefix ∈ ["${aws:PrincipalTag/username}/", "${aws:PrincipalTag/username}/*"]`; explicit `Deny s3:DeleteObject` on `<bucket>/*/DO_NOT_DELETE.txt` (protects the SPEC-014 marker). The tag var is escaped `$${…}` so `templatefile()` emits it literally.
- **`infra/modules/data/policies/user-space-bucket-policy.json.tftpl`** + `aws_s3_bucket_policy` in `s3.tf` (FR-002): denies S3 **data** actions (object CRUD + `ListBucket`) to every principal except the portal role and account root (`aws:PrincipalArn` `StringNotLike`). Bucket **configuration** actions are left ungated so the deploy role keeps managing the bucket and a bad policy can't lock out the IaC (root is break-glass).
- No deploy-role change needed — `iam:PutRolePolicy` + `s3:*` on the bucket were already granted (SPEC-010/011).

**Phase 2 — App switchover (merged [#27](https://github.com/agriffi10/data-analysis-prototype/pull/27)):**
- **`fileBrowser.service.ts`** — `listFiles` uses the authenticated `getS3Client()` (Identity Pool creds) with **one transparent retry** via `getS3Client(true)` on a credential-expiry error; listing logic extracted into a client-taking helper.
- **`FilesPage.tsx`** — `VITE_S3_USER_SPACE_BUCKET` + `rootPrefix = "{username}/"` from `useAuth()`.
- **`FileBrowser.tsx`** — new `rootLabel` prop; the root crumb reads **"My Files"** so the raw `{username}/` segment is never shown (FR-003). Empty prefix → existing empty state.
- **Dev-only fallback** — the SPEC-001/002 static/anonymous path is gated behind `VITE_S3_DEV_UNAUTH` **and** `import.meta.env.DEV` (in `fileBrowser.service.ts`, `FilesPage.tsx`, and a matching `ProtectedLayout.tsx` auth-gate bypass), so it is stripped from production builds. Documented in `.env.example`.
- Tests reworked onto `getS3Client` (+ retry-path, credential-error, no-retry-on-`AccessDenied`) and new `FileBrowser` `rootLabel` tests. 64 pass; `tsc`/`lint` clean.

**Follow-up — build wiring ([#28](https://github.com/agriffi10/data-analysis-prototype/pull/28)):**
- `VITE_S3_USER_SPACE_BUCKET` is now injected into the `deploy-app.yml` build from a GitHub Actions **variable** (`dat-prod-user-space`); without it the deployed `/files` showed a configuration error. Workflows README updated.

## What has changed?

- **New infra**: `infra/modules/data/policies/portal-role-permissions.json.tftpl` + `user-space-bucket-policy.json.tftpl`; role inline policy + bucket policy in the data module.
- **Frontend**: file-browser service now authenticated (Identity Pool) with expiry retry; `/files` scoped to the user-space bucket + `{username}/`; username hidden via `rootLabel`; SPEC-001/002 static/anon path demoted to a dev-only flag.
- **CI/env**: `VITE_S3_USER_SPACE_BUCKET` wired into `deploy-app.yml` + set as a GitHub variable.
- **Docs**: the auth acceptance script gained the FR-004 isolation procedure + an execution-log entry; `.env.example`, CLAUDE.md, architecture roadmap updated.

## Verification

- **FR-001 (role policy)** — `aws iam simulate-principal-policy` against the **live** `dat-portal-user-role`: own-prefix Get/Put/Delete **allowed**; cross-prefix all **implicitDeny**; `*/DO_NOT_DELETE.txt` delete **explicitDeny**; `ListBucket` with own prefix allowed, other/empty-prefix (root) **denied**; no-`username`-tag session **denied**.
- **FR-002 (bucket policy)** — live policy confirms the Deny excludes exactly the portal role ARN + account root. `aws:PrincipalArn` for a Cognito-assumed session resolves to the **role IAM ARN** (AWS docs), which is excluded — so user sessions are not blocked (confirmed live in FR-003). A regular IAM admin (`tofu-deploy-user`) is correctly denied bucket data access (`HeadBucket` → 403).
- **FR-003 (browser switchover)** — **live, deployed app, 2026-06-12**: a signed-in test user lists their own seeded object (seeded via root) in `/files` with no errors; username hidden; authenticated path + prefix scoping + bucket policy all work end to end. Unit tests cover the retry path and `rootLabel`.
- **FR-004 (isolation)** — cross-user/root-list denial proven at the policy layer via the simulator (above) and enforced by the same `${aws:PrincipalTag/username}` scoping demonstrated working for the allow case. The **live** cross-user negative-path run (dev-server console, per `e2e.md`) is the remaining manual step; the production bundle's console can't exercise it (no `import()` of bare specifiers / no `import.meta`).

### Follow-ups / notes

- **Seeding test data:** because the bucket policy locks data writes to the portal role + root, seed via **account root** (a regular IAM admin is denied — that's the policy working) or have the user write their own prefix from the signed-in app once upload exists.
- **First-login prefix marker** (`{username}/DO_NOT_DELETE.txt`) is **SPEC-014** — until then a brand-new user's prefix is implied-only and renders the empty state (handled, no error).
- **Upload from the app** is **SPEC-016**; the browser is read/list only for now.
- The dev-only unauth path (`VITE_S3_DEV_UNAUTH`) also bypasses the `/files` auth gate in dev — guarded by `import.meta.env.DEV`, so never present in production.
