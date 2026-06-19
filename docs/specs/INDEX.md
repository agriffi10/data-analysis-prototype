# Spec Index

One row per spec. Files are `docs/specs/SPEC-<NN>-<slug>.md`; each file's header carries the
authoritative `Status`. Delivery write-ups (completed specs) are in `docs/spec-delivery/`.
Add a row when a spec is created; update its status on completion (status only — keep it terse).

| Spec | Status |
|---|---|
| 001 — S3 File Listing | Completed |
| 002 — Browse Prefixes (public bucket file browser) | Completed |
| 003 — Project IaC (OpenTofu) | Completed |
| 004 — GitHub Actions CI (test + build) | Completed |
| 005 — Deploy App to AWS (GitHub Actions + OpenTofu) | Completed |
| 006 — Cognito User Pool IaC (`auth` module) | Completed |
| 007 — Login Flow (Hosted UI + Amplify) | Completed |
| 008 — Auth-Gated Layout (react-router) | Completed |
| 009 — Sign-Up End to End | Completed |
| 010 — User-Space Bucket IaC (`data` module) | Completed |
| 011 — Scoped Credentials (Identity Pool ABAC + portal role) | Completed |
| 012 — Pre-Signup Username Validation (Lambda) | Completed |
| 013 — Prefix-Scoped S3 Access + Browser Switchover | Completed |
| 014 — User Prefix Marker (DO_NOT_DELETE.txt) | Completed |
| 015 — File Download + Data Foundation (TanStack Query) | Completed |
| 016 — File Upload (managed, auto-multipart + progress) + Create Folder | Completed |
| 017 — File Metadata Panel | Completed |
| 018 — Delete Files and Folders (recursive) | Completed |
| 019 — Move & Rename (files and folders) | Completed |
| 020 — Upload Queue (multi-file, concurrency, cancel) | Completed |
| 021 — Design Token Baseline (Tailwind v4 @theme) | Completed |
| 022 — Landing Page Visual Polish | Completed |
| 023 — App Shell Visual Polish (Header + Layouts) | Completed |
| 024 — File Browser Visual Polish | Completed |
| 025 — Upload Dropzone Visual Polish | Completed |
| 026 — Dialogs Visual Polish | Completed |
| 027 — Metadata Panel Visual Polish | Completed |
| 028 — Shared UI Primitives (Button, Input, Badge, Banner, BrandMark) | Completed |
| 029 — Landing Page Full Design | Completed |
| 030 — Cognito Bot Signup Protection (WAF + ASF) | Completed |
| 031 — Document Title Management | Completed |
| 032 — Analytics Foundation IaC (Athena workgroup + admin bucket + Lake Formation) | Completed |
| 033 — Per-User Glue Database Provisioning (post-confirmation Lambda + LF grant) | Completed |
| 034 — Query Engine Data Layer (Athena/Glue services + per-user history) | Completed |
| 035 — Tabbed Dashboard + Query Workspace UI (Monaco editor) | Completed |
| 036 — Query History Panel UI | Completed |
| 037 — File Browser Pagination (25/page, Load more) | Completed |
| 038 — Query Results Pagination (20 rows/page, Prev/Next) | Completed |
| 039 — Copy Files and Folders (recursive) | Completed |

## Arcs

**File-operations arc (015→020, +039 copy)** — turns the read-only browser into a filesystem:
download, upload, create-folder, metadata, delete, move, rename, large-file upload, copy. All
build on SPEC-013 (authenticated user-space bucket). Move/rename = copy-then-delete; copy (039)
reuses the same `copyObject` minus the delete (additive, same-folder auto-suffix). Folder ops are
recursive + non-atomic. See architecture.md Known Constraints.

**Analytics arc (032→036)** — a second portal surface: an in-app Athena query workspace beside the
file browser. Each user gets a private Glue database **named exactly as their username** (created by
a Cognito **post-confirmation** Lambda, which also LF-grants the shared role on it), queries through
**one shared Athena workgroup**, and sees only their own results/history. Isolation reuses the single
shared role + `username` **IAM principal tag** (the role's policy scopes Glue to
`database/${aws:PrincipalTag/username}`) — **no LF-Tags**. Requires `username = S3 prefix = principal
tag = Glue DB name` (catalog-safe username rule, SPEC-033). User-space bucket registered in LF
**hybrid** mode (file browser keeps direct-IAM S3; Athena reads via LF). Results + history live in
`{username}/athenaresults/` (user reads; IAM denies delete; UI-locked); workgroup default output is a
separate admin-only bucket. Query history is app-side JSON (`query-history.json`), read-only to the
user. Users define tables via DDL and may write (CTAS/INSERT) into their own prefix. SPEC-035/036 are
design-led (`docs/design/query-workspace.html` + `design-system.md` §6). New deps at implementation:
`@aws-sdk/client-athena`, `@aws-sdk/client-glue`, Monaco.
