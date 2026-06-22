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
| 040 — Query Editor Session Persistence + Clear Button | Completed |
| 041 — Multi-Tab Query Editor | Completed |
| 042 — Query History Pagination (7/page, Prev/Next) | Completed |
| 043 — Saved Queries + Global Workspace Bar | Completed |
| 044 — Schema Browser Table Options Menu | Completed |
| 045 — Automated Accessibility (axe) Test Suite | Completed |
| 046 — Refresh History Button | Draft |
| 047 — Workspace Database/Connection Selector | Draft |
| 048 — Create View from Query + Views in Schema Browser | Draft |
| 049 — Save Query Results to Workspace (replaces Download CSV) | Draft |
| 050 — Shared-Space Foundation Infrastructure (Bucket 2 + control plane) | Draft |
| 051 — Create Shared Connection | Draft |
| 052 — Shared Connections List, Selector Integration & Refresh | Draft |
| 053 — Shared-Space Member Management (Owner) | Draft |
| 054 — Leave & Delete a Shared Space | Draft |
| 055 — Shared-Space Query Results Routing & Save | Draft |
| 056 — Shared-Space Access Model & Request Contract (membership tags + portal slots + LF) | Draft |
| 057 — Shared Spaces in the File Browser | Draft |

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

**Query-editor UX follow-ups (040→042)** — refine the SPEC-035/036 workspace without touching the data
layer or IAM: 040 persists the un-run editor draft across tab switches/reloads (`sessionStorage`,
per-user) and adds a **Clear** button; 041 turns the editor into **query tabs** (`Query N`, monotonic
labels, closable-with-confirm, per-tab persisted text) and supersedes 040's single-draft storage;
042 paginates the history drawer (7/page, Prev/Next, newest-first, client-side). 041 needs a design
pass (new tab strip in `query-workspace.html` + §6) before code.

**Query-editor UX, round 2 (043→044, + 041 amend)** — builds on the tab model: 043 adds **saved
queries** (Save in the Run bar → named JSON store at `{username}/user_settings/saved-queries.json`,
same IAM as history; a saved-queries slide-out drawer; open-in-new-tab, re-save-in-place, delete-with-
confirm, dirty marker; History + Saved-queries buttons hoisted to a workspace-global bar; runs from a
saved query record its name in history). 044 adds a per-table **options menu** in the schema browser —
view source files (deep-links the file browser via new `/files?prefix=`), view DDL (`SHOW CREATE TABLE`
→ tab), view data (`SELECT * … LIMIT 10` → tab), drop table (confirm → background run + schema refresh +
toast). SPEC-041 was **amended** (pre-build): the 10-tab cap now raises a "close a tab first" dialog
(the `+` is no longer disabled) and `openTab` accepts a feature-supplied label/sql so 043/044 open
named tabs. No IAM/infra change across this round (043/044 reuse existing analytics + file-browser
access; the `?prefix=` deep-link is frontend-only).

**Query-editor UX, round 3 (046→049, one-offs)** — small, mostly independent additions on the
SPEC-034→044 workspace: 046 adds a **Refresh** control to the history drawer (manual re-read of
`query-history.json`); 047 introduces a **workspace database switcher** (the schema-browser rail lists the databases you can
query and switching one updates the tables/views + the Run target; the database is **workspace-global**;
the toolbar shows a read-only DB chip — via a new `useConnections` seam that returns only the personal DB
today and is the extension point the shared-spaces arc feeds shared connections into); 048 adds **Create view** (`CREATE OR REPLACE VIEW`
against the selected DB) and makes the schema browser **view-aware** (view badge; `SHOW CREATE VIEW`/
`DROP VIEW`; source-files disabled for views); 049 **replaces Download CSV** with **Save results to my
files** — a destination+filename prompt that server-side-copies Athena's complete result object into
the user's space (all rows, not just the loaded page). 047 is a dependency of 048; the rest are
independent. No IAM/infra change (all reuse existing user-scoped S3 + analytics access).

**Shared-connections arc (050+056→055)** — Bucket 2 (`dat-prod-shared-space`): user-created, uniquely-named,
non-renameable shared connections (name = shared S3 prefix = shared Glue DB), provisioned by an async
**SQS → EventBridge Pipe → Step Function** pipeline (validate → create → update permissions). Access is
gated by a **membership principal tag** on the shared role (10 bounded Cognito attribute slots; LF grants
the role per shared DB, IAM tag is the gate — same shape as the personal `username`-tag model). Source of
truth = an **S3 control-object registry** in the analytics admin bucket (`shared-spaces/` prefix,
pipeline-only); each user's `{username}/user_settings/shared-connections.json` is a UI **cache** the pipeline
writes (pending/active/failed status). Shared-DB query results route to the shared prefix. Decision record:
`docs/shared-spaces-architecture.md` (reverses the "no backend" decision for shared-space mutations only).
build order is **050 → 056 → 051 → 052 → 053 → 054 → 055 → 057**: 050 = foundation plumbing (buckets, SQS/Pipe/Step
Function skeleton, orchestrator role, deploy IAM); 056 = access model + request contract (membership tags,
portal-role slots, LF registration, actor binding) — split from 050 so the IAM/access wiring applies separately;
051 = create; 052 = the **Connections** top-level tab + `useConnections` (personal + shared in one list) + refresh,
feeding the Query schema-rail switcher (047) and the Files space list (057); 053 = owner member management as a
**slide-out drawer** (add/remove, bulk; User-Pool validity, unknowns ignored); 054 = member leave + owner
cascade-delete; 055 = shared-DB results routing + save; 057 = browse shared spaces in the **file browser** (the Files
sidebar lists personal + shared spaces). **Navigation:** a third top-level tab **Connections** (Files | Query |
Connections) manages spaces; shared connections also appear inline in the Query database list and the Files space
list; the workspace database is global. Three CONFIRM items in the decision record were resolved (cap = 10; valid
user = exists in the User Pool; registry reuses the admin bucket).
