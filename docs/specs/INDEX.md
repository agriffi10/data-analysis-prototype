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
| 046 — Refresh History Button | Completed |
| 047 — Workspace Database/Connection Selector | Completed |
| 048 — Create View from Query + Views in Schema Browser | Completed |
| 049 — Save Query Results to Workspace (replaces Download CSV) | Completed |
| 050 — Shared-Space Foundation Infrastructure (Bucket 2 + control plane) | Completed |
| 051 — Create Shared Connection | Completed |
| 052 — Shared Connections List, Selector Integration & Refresh | Completed |
| 053 — Shared-Space Member Management (Owner) | Completed |
| 054 — Leave & Delete a Shared Space | Completed |
| 055 — Shared-Space Query Results Routing & Save | Completed |
| 056 — Shared-Space Access Model & Request Contract (membership tags + portal slots + LF) | Completed |
| 057 — Shared Spaces in the File Browser | Completed |
| 058 — Notifications Foundation Infrastructure (Write Pipeline + IAM) | Completed |
| 059 — Notifications Data Layer (Read Service + Hook) | Completed |
| 060 — Notifications UI (Header Bell Link + Notifications Page) | Completed |
| 061 — Shared-Workspace Notification Producer | Completed |
| 062 — Decompose Shared-Space Control Plane into Single-Task Lambdas | Completed |
| 063 — Schema Rail: Collapsible Databases with Tables/Views Groups | Completed |
| 064 — Resizable Query-Result Columns | Completed |
| 065 — Schema-Aware Editor Autocomplete (Table & Column Names) | Completed |
| 066 — Table Builder: Foundation Infrastructure + polars Runtime | Completed |
| 067 — Table Builder: Request Contract, Enqueue & Validate-Authorize | Completed |
| 068 — Table Builder: Name Uniqueness + Source Inspection & Format Validation | Completed |
| 069 — Table Builder: Schema Inference & DDL Generation (polars) | Completed |
| 070 — Table Builder: Execute DDL & Terminal States | Completed |
| 071 — Table Builder: "Create Table from this Folder" (File Browser UI) | Completed |
| 072 — Table Builder: Notification Producer (per-step failure + success) | Completed |
| 073 — Shared-Space Member Join Status (Pending / Active) | Completed |
| 074 — Help & Guides Page (Top-Bar Icon + Documentation Page) | Completed |
| 075 — Shared-Space Member Roster for Members (read-only) | Completed |
| 076 — Per-Tab Query Database (+ Saved Query Targets Its Database) | Superseded (by SPEC-077) |
| 077 — Cross-Database Querying (drop the active-database session) | Completed |
| 078 — Multiple SQL Statements in One Editor | Completed |
| 079 — Editor / Results Layout Presets | Completed |
| 080 — Total Row Count in Query Stats | Completed |
| 081 — Double-Click a File to Download | Completed |
| 082 — Shared-Space Registry Write Concurrency (optimistic CAS) | Completed |
| 083 — Code-Quality Hardening (Lambda config/shape/types + Lambda & SPA cleanup smells) | Completed |
| 084 — Query Editor Autocomplete Lifecycle Fix (Monaco completion provider) | Completed |
| 085 — Collapsible Side Nav (shared base rail + collapse control) | Completed |
| 086 — Per-Database Schema Refresh (look for new tables/views) | Completed |
| 087 — Configurable Query-Results Page Size (default 100, user-adjustable, workspace-wide) | Completed |
| 088 — Table Share: Foundation Infrastructure + Common Layer | Completed |
| 089 — Table Share: Request Contract, Enqueue & Validate-Authorize | Completed |
| 090 — Table Share: Source Resolution & Copy Plan (inspect-source) | Completed |
| 091 — Table Share: Recipient Map + Copy (check-target-absent + copy-objects) | Completed |
| 092 — Table Share: Recipient Table Creation & Terminal States (create-table) | Completed |
| 093 — Table Share: "Share table" UI (Query Schema Rail) | Completed |
| 094 — Table Share: Notification Producer (sender + recipients) | Completed |
| 095 — Responsive Foundation & App Shell | Completed |
| 096 — Files: Selection Toolbar → Copy/Move/Delete | Completed |
| 097 — Files: Object Details Panel Gains Download & Rename | Completed |
| 098 — Files: Parent-Folder (`..`) Row | Completed |
| 099 — Files Responsive Layout | Completed |
| 100 — Query Workspace Responsive | Draft |
| 101 — Connections Responsive | Completed |
| 102 — Notifications Responsive | Completed |
| 103 — Help & Guides Responsive | Completed |
| 104 — Landing / Sign-In Responsive | Completed |
| 105 — View Data: Full Table, Paginated (drop 10-row preview limit) | Completed |
| 106 — User-Facing Error Messaging (friendly, no AWS leaks) | Completed |
| 107 — Shared `control-plane-common` Lambda Layer | Completed |
| 108 — Data Quality: Foundation Infrastructure + Common Layer + Athena Workgroup | Completed |
| 109 — Data Quality: Request Contract, Enqueue & validate-authorize | Completed |
| 110 — Data Quality: Source Inspection | Completed |
| 111 — Data Quality: Temp Tables + the Athena Profile Query | Draft |
| 112 — Data Quality: byte-scan + Report Assembly | Draft |
| 113 — Data Quality: File-Browser UI + Report View | Draft |
| 114 — Data Quality: Notification Producer | Draft |
| 115 — File Converter: Foundation Infrastructure + Layers + Athena Workgroup | Draft |
| 116 — File Converter: Request Contract, Enqueue & validate-authorize | Draft |
| 117 — File Converter: Source Inspection + Schema Reconciliation | Draft |
| 118 — File Converter: The Athena UNLOAD Path | Draft |
| 119 — File Converter: finalize + Terminal States | Draft |
| 120 — File Converter: File-Browser UI | Draft |
| 121 — File Converter: Notification Producer | Draft |
| 122 — File Converter: Create Table From Converted Files (chain to Table Builder) | Draft |
| 123 — Data Quality: Runs Dashboard (`/data-quality` list + nav + runs index) | Draft |
| 124 — Data Quality: Start a Check from the Dashboard (space + folder/file target picker) | Draft |

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

**Notifications arc (058 → 059 → 060 → 061)** — a per-user notifications inbox. A notification is `{id, message, read,
timestamp}`; the inbox is one JSON array at `{username}/user_settings/notifications.json` in the existing user-space
bucket. **Single-writer model:** every mutation — system `create` **and** user actions (`markRead`/`markAllRead` — there
is **no delete**) — is a message on a **FIFO SQS queue that triggers the notifications-writer Lambda directly** (SQS
event-source mapping, batch size 1 — **no EventBridge Pipe, no Step Function**); the Lambda read-modify-writes the doc
under one privileged **writer role** (the only writer; caps to the most-recent `NOTIFICATIONS_MAX`). **Per-user
ordering/serialization** = FIFO `MessageGroupId` = the target username (one message at a time, in order, per user; no
lost updates). The browser **never writes** the file — it only reads it (direct `GetObject`) and enqueues
user-action messages (`sqs:SendMessage` on the portal role, with `MessageGroupId` = its own username). Anti-spoofing:
user-action messages carry the caller's Cognito **ID token**; the writer derives the target `username` from the verified
claim and ignores any body `username` (`create` is trusted-producer-only). This is a **dedicated** write path (its own
FIFO queue/Lambda/role), decoupled from shared-spaces. Build order: **058** = write pipeline + writer role +
deploy/portal IAM + message contract (no UI); **059** = browser data layer (`notifications.service.ts` read +
`enqueueNotificationAction`, `useNotifications` hook with optimistic mark-read mutations + unread count +
prefetch-on-load + a **60-second background poll** for the icon; adds `@aws-sdk/client-sqs` +
`VITE_NOTIFICATIONS_QUEUE_URL`); **060** = UI (header **bell linking to a `/notifications` route** left of the username
with an unread indicator, a full **notifications page** with per-row unread marker like the active query tab, **10/page**
Prev/Next `Pager`, mark-read/mark-all-read with optimistic update + toast — **no drawer, no delete**); **061** = the
first **producer**: the shared-workspace control plane (each verb Lambda, SPEC-062) emits `create` notifications at the
terminal outcome of its lifecycle actions (seven events: created / create-failed / added-to-space / add-skipped-at-limit /
add-unknown-user / member-left / deleted — delete fans out to the deleter + all members), granted `sqs:SendMessage` on the notifications queue. Reuses `Pager`/`IconButton`/
`Badge`/`Toast`; 060 adds no IAM/infra; 061 adds only the SendMessage grant on the emitting verb-Lambda roles (SPEC-062; the single orchestrator role pre-062) + queue-URL env wiring + the inline emit calls.

**Control-plane refactor (062, standalone)** — the shared-space control plane shipped (050→054) as a **single
711-line provisioner Lambda** with an `action`-switch (create/add_members/remove_members/leave/delete) + inline JWT
verify + all helpers, under one broad orchestrator role. SPEC-062 decomposes it to the architecture's original intent
(§7 "provisioning Lambda(s)"): the **Step Function orchestrates single-task Lambdas** — `entry → validate-authorize →
Choice(action) → <verb Lambda> → success/failure` (Retry/Catch in the state machine), one Lambda per verb, shared
code (auth/registry/clients/cache/notify) in a common module/layer, and **per-verb least-privilege roles** replacing
the monolith role. **Behavior, the request contract (056), the membership-tag model, and registry/cache shapes are
unchanged** — structure only — plus two clarifications: **create stays creator-only** (no member-add at create; adds go
through 053 from the Connections tab), and each verb **emits its SPEC-061 notifications inline** via the shared helper.
The old provisioner function/role/tests are removed at cutover. Follows `docs/best-practices/lambdas/lambdas.md`;
decision recorded in `docs/shared-spaces-architecture.md`.

**Query-editor UX, round 4 (063→065, user-feedback one-offs)** — three independent presentation/editor refinements
on the SPEC-034→049 workspace, no data-layer/IAM change: **063** restructures the schema rail into a **tree** — each
accessible database is a collapsible node with two collapsible sub-groups, **Tables** and **Views** (grouped beneath
their database); expanding to browse is **decoupled** from selecting the SPEC-047 workspace-global active target
(per-node `useSchema`, a separate radio-style active control). **064** makes query-result columns **drag-resizable**
(persist across pages of the current result, reset on a new query; `MIN_COLUMN_WIDTH` floor; no wrap → ellipsis
truncation incl. the header; horizontal scroll for 20+ columns; keyboard/dbl-click reset). **065** adds **schema-aware
autocomplete** to the Monaco editor — a single SQL completion provider offering the **active database's** table/view +
column names (with type detail) alongside built-in keywords, updating on active-DB switch, keyword-only fallback when
no schema. All three are independent and can ship in any order. *(A fourth feedback item — contiguous result row
numbers — was already delivered in `QueryResultsTable` (SPEC-038, the `#` column = `rangeStart + rowIndex`), so no spec
was written.)*

**Create-Table-from-Files / "Table Builder" arc (066 → 067 → 068 → 069 → 070 → 071, + 072 producer)** — a new
**dedicated** async control plane (its own FIFO **SQS → EventBridge Pipe → Step Function**, **single-task Lambdas**
with per-verb least-privilege roles) that turns a folder of data files into a Glue/Athena **external table** in the
database the space maps to (personal = username; shared = space name). Decision record:
`docs/table-builder-architecture.md` (read first). Reuses the **pattern** of the shared-spaces control plane
(SPEC-050) and the dedicated-pipeline precedent of notifications (SPEC-058), **not** their resources. The browser
only gains `sqs:SendMessage`; authorization reuses the **ID-token actor** + shared-spaces **registry** membership
model (any active member may create — not owner-only). The Step Function orchestrates five verbs:
**validate-authorize** (token→actor, personal/shared authz, name + in-space location + **declared partition keys**) →
**check-table-absent** (Glue GetTable) → **inspect-source** (single consistent format — **Parquet/CSV/JSON**, ORC
deferred; **confirm the user-declared `key=value/` keys match the layout**, not auto-detect) → **infer-schema**
(**polars LazyFrame** on a sample → dtype→Hive mapping for data cols + **user-declared partition cols** → generate
`CREATE EXTERNAL TABLE IF NOT EXISTS` DDL **with partition-projection `TBLPROPERTIES`**; polars ships as a **Lambda
layer**, attached only to this verb) → **execute-ddl** (run the DDL via **Athena**; **projection ⇒ no `MSCK REPAIR`**;
terminal success). **Partitions = user-declared keys (granularity order) + partition projection** (decided
2026-06-30); the modal collects each key's type+range. Each step records a typed terminal reason via the SFN `Catch`.
**066** = foundation infra + polars layer (plumbing/stubs); **067** = request contract (+ `partitionKeys`) +
portal-role `sqs:SendMessage` + `VITE_TABLE_BUILD_QUEUE_URL` + validate-authorize; **068** = name-check + source
inspection; **069** = polars schema inference + DDL generation (+ projection props); **070** = execute DDL + terminal
states (+ execute-ddl LF/Glue/Athena/S3 role); **071** = the file-browser **"Create table from this folder"** button +
name dialog **+ partition-keys section** + enqueue (the only browser surface); **072** = notifications producer
(per-step failure + on-success, single recipient = the actor; depends on SPEC-058, mirrors SPEC-061). Build order
066→067→068→069→070→071; **072** after the notifications queue (058) + the verb Lambdas. New Lambda deps: **polars**
(layer). New IaC: `infra/modules/table-builder/`.

**Build order across the two arcs:** **SPEC-062 lands before SPEC-061** — the notification producer's inline emits
attach to the decomposed verb Lambdas, so decomposing first avoids adding emit logic to the monolith and then moving
it. SPEC-061 is written to also work against the pre-062 monolith (same call sites at each terminal branch) if it must
ship first, but **062 → 061** is the intended sequence. The notifications-infra arc (058 → 059 → 060) is independent of
the shared-spaces refactor and can proceed in parallel; only **061** depends on both (058's queue + 062's verb Lambdas).

**Query-editor UX, round 5 (077→080) + file-browser one-off (081)** — a user-feedback batch (2026-07-01), no
data-layer/IAM change: **077** removes database **selection** entirely — no "current database" anywhere; the schema
rail becomes **browse-only** across every accessible database and runs carry **no** `QueryExecutionContext.Database`, so
**every base-table reference must be fully-qualified `database.table`** (`FROM`/`JOIN`/subqueries/CTE bodies; unqualified
names fail — the accepted trade-off). This enables **cross-database queries/joins** across the databases the shared role
already has Glue/LF/S3 grants on (personal `username` tag + shared membership tags, SPEC-056); **077 supersedes SPEC-076**
(per-tab database — **will not be built**) and SPEC-047's workspace-global active DB. **078** runs
**multiple SQL statements** from one editor — split on `;` (string/comment-aware), execute **sequentially, stop-on-
failure**, one history entry per statement. **Design pass resolved:** three run scopes — **Run Statement** (selection /
cursor stmt / sole stmt, ⌘⏎ default), **Run Script → single result** (last result-producing stmt), **Run Script → tab
per statement** — plus a new **result-tabs** concept in the results region (one tab per result-producing statement, each
with its own pager/stats). **079** adds **editor/results layout presets** — a three-option control (editor ~90% / even 50/50 default /
results ~90%) that snaps the vertical split (min-height floors, keyboard-accessible, session-persisted preset); replaces
the earlier draggable-splitter design. **080** shows the **exact total row count** in the
status bar by **background-walking all `GetQueryResults` pages** after success (free calls, no extra scan; ceiling cap;
per-execution reset) instead of today's loaded-count "N+". **081** (file browser) makes **double-clicking a file row
download it** via the existing presigned-URL flow (both authenticated + read-only browse; explicit Download controls
stay). 077→080 are query-workspace one-offs (077 is a dependency-of-none but reshapes the DB model the others build on);
081 is independent. None add IAM/infra.

**Table-Share arc (088 → 089 → 090 → 091 → 092 → 093, + 094 producer)** — filed 2026-07-04; "**share a table** across databases." From the Query schema rail, a user shares any accessible table to one or more **users** and/or **shared spaces**: the data files are **copied** into each recipient's space under `shared_tables/{table}/` and a table of a chosen name is **created** over the copy in the recipient DB. A **new dedicated** async control plane (its own FIFO **SQS+DLQ → EventBridge Pipe → Standard Step Function**, single-task Lambdas + a **`table-share-common` (`tscommon`)** layer, **one shared execution role that is an LF admin**) mirrors the table-builder/shared-spaces pattern (reuses the pattern, not the resources). The SFN: **validate-authorize** (ID-token actor; actor must have **source** access — personal = own DB, shared = active member) → **inspect-source** (`GetTable`, **clone the source table definition**; reject views / catalog-partitioned / non-external; list objects; enforce object/size caps) → **`Map` over recipients** (per-item Catch): **check-target-absent** (fail that recipient on name conflict / non-empty prefix) → **copy-objects** (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → **create-table** (clone def, repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Decisions (2026-07-04):** push (no consent; recipient notified), clone-not-infer (format-agnostic), parallel `CopyObject` (Batch Ops deferred), **any space is a valid target** (source access still gated), conflict = **fail that recipient only** (no overwrite), v1 sources = **flat or projection-partitioned** base external tables. Build order 088→…→093; **094** (notifications: actor per-recipient outcome + recipient "shared with you") after SPEC-058 + the verb Lambdas. Decision record: `docs/table-share-architecture.md` (read first). New infra: `infra/modules/table-share/`; new browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`.

**App-shell / schema-rail UX one-offs (085, 086)** — filed 2026-07-02, both presentation-only (no data-layer/IAM/infra).
**085** adds a **collapsible side nav**: the Files spaces `Sidebar` and the Query `SchemaBrowser` share the same 248px rail
chrome, so it's factored into one **`CollapsibleRail`** base component with a collapse control; collapsed = **fully hidden +
a reopen handle** (not a slim icon rail), and the state is **persisted per browser in `localStorage` under one shared key**
so the choice carries across both rails. Below-`tablet` behavior (rail hidden) and the top-bar tabs are untouched. **086** adds a
**per-database Refresh** control to each schema-rail `DatabaseNode` (SPEC-063) that re-reads only that database's tables/views
(`queryKeys.schema(database)` invalidate/refetch via the existing `useSchema`/`invalidateSchema`) — manual, per-node, error
non-destructive; mirrors the SPEC-046 history-refresh pattern. Both are independent of each other and of everything else.

**Best-practice audit follow-ups (082→084)** — filed 2026-07-02 from a read-only audit of the Lambdas + SPA against
`docs/best-practices/`; all code-only, no IAM/infra. **082** fixes a lost-update race in the shared-space **registry**
writers (`finalize`/`save_members`/`set_status`/`reserve` retry) by giving them the same optimistic ETag CAS the
`cache.py` sibling already uses. **083** bundles the cross-cutting Lambda hardening items (config validate-at-init;
table-builder handlers validating event shape into typed terminals + actor notify instead of bare `KeyError`; type hints
on public signatures; thin the fat handlers + small Python-style fixes) **plus the lower-priority SPA smells folded in as
FRs** (memoize unstable context/hook identities + `QueryWorkspace` derived structures; harden the `useNotifications`
timer cleanup; fix the query submit de-dupe guard's stale read; resolve `QueryResultsTable` index keys). **084** makes
the query editor's Monaco completion-provider registration/disposal remount-safe
(tab switches / StrictMode) so autocomplete can't silently die. All three are independent of each other.

**Responsive & Files-UX arc (095 → 099, then 100/101/102/103, + 104)** — filed 2026-07-08 from the Claude Design
responsive mockups (`docs/design/Responsive Breakpoints.dc.html` + `README.md` + `design-system.md`); makes the whole
app responsive across mobile (base, `< 900px`) / tablet (`tablet:`, 900–1299px) / desktop (`desktop:`, ≥1300px) — **two
custom `@theme` breakpoints** in `App.css` (`--breakpoint-tablet: 900px`, `--breakpoint-desktop: 1300px`; the Tailwind
default `sm`/`md`/`lg`/`xl`/`2xl` prefixes are **reset to `initial`** so only `tablet:`/`desktop:` compile, and existing
`md:`/`sm:` code is migrated) — plus three Files feature changes. **All presentation-only** — no data-layer, service, IAM, or infra changes anywhere in the
arc. Reflows are responsive utilities on one component by default; a separate component/markup branch is allowed only when
the two presentations are genuinely structurally different (e.g. the Files **data table vs mobile card list**, SPEC-099).
**095** = the shared foundation everything else consumes: the custom breakpoint convention + a shared `useBreakpoint` hook
(mount-gating only), an off-canvas **`AppNavDrawer`** (300px,
hamburger, primary tabs + a contextual rail slot) + responsive `Header`, a **`MobileActionBar`** primitive, a reusable
**`Menu`** primitive (extracted from the query `TableActionsMenu`), and responsive `Modal`/`Drawer` (`mobileVariant`
bottom-sheet/full-height). The three **Files feature changes** are independent of responsiveness and each other: **096**
narrows the multi-select toolbar to **Copy/Move/Delete** (Download+Rename leave it); **097** adds **Download + Rename**
to the button-opened **object details panel** (**user decision: the panel stays opened by the per-object Details button,
visible at all breakpoints, NOT selection-gated** — the mockup's `count===1` inline-column model is not adopted; file
panel = Download+Rename, folder panel = Rename); **098** adds the **`..` parent-folder row** (non-selectable, hidden at
root). **099** lays the Files browser out responsively (5-col desktop → drop Type at `tablet` → 56px two-line card list on
mobile; `MobileActionBar` = New folder + Upload; icon-only bulk bar; **decision: no header `⋯` overflow menu and no mobile
selection mode — checkboxes stay always-visible; net-new Sort/Select excluded**) and depends on 095–098. Then the
per-surface reflows, each depending on 095: **100** Query (tablet rail ~220px + icon toolbar; **mobile browse-first — no
Monaco editor on phones**, Saved/History home, read-only results + Prev/Next); **101** Connections (cards horizontal →
stacked, pills wrap, full-width actions, "New" label; member drawers → full-height sheet); **102** Notifications (mobile
header stacks via an opt-in `PageLayout` prop; per-row Mark-read below the message; full-touch pager); **103** Help
(248px guides rail → horizontal chip section selector on mobile; **in-page search excluded — not shipped today**). **104**
Landing/sign-in (nav → hamburger menu; hero 46→40→32px; CTAs full-width stacked; feature grid 3→2→1) is independent
(public page; optionally reuses the 095 `Menu`). Build order **095 → 096/097/098 → 099 → 100/101/102/103 → 104**. No new
env vars, deps, or IAM.

**Control-plane-common prerequisite (107)** — filed 2026-07-11. `tbcommon/auth.py` and `tscommon/auth.py` are already
**near-identical twins** (same logic; they differ only in an import order and one error string); the two arcs below would take
that to **four independent copies of the JWT verification path**. **107** extracts the shared surface
(auth/clients/errors/registry/s3_listing/notify/messages/events) into one **`cpcommon` layer** that every control-plane verb
attaches alongside its domain layer, deletes the duplicates from `tbcommon`/`tscommon`, and ships **no behaviour change** (a
test whose *assertions* have to change is a spec violation; the two domains' differing error strings are parameterized, not
merged). It also closes two latent gaps the new arcs would otherwise walk into: the **basename-only hidden-path rule** becomes
**segment-level** (today `alice/_reports/x.json` is *not* ignored — the `_` is in a path segment, so Table Builder would ingest
data-quality reports as source data), and the **CI layer-size guard** becomes a **combined per-function** measurement (Lambda's
250 MB ceiling counts all layers *plus* function code; today's guard measures one layer in isolation and cannot see an
overflow). `shared-space-common` is deliberately **not** folded in. **107 ships as two PRs** (the layer is a new resource; the
deploy-role grant must apply first). **Build 107 before either arc below.**

**Data-quality arc (108 → 114)** and **file-converter arc (115 → 121)** — filed 2026-07-11 from
`docs/data-quality-architecture.md` and `docs/file-converter-architecture.md`, both **re-architected (v3)** after the review in
`docs/architecture-review-2026-07-11.md` **and** the 250 GB source-file requirement. Two **independent** dedicated async control
planes (FIFO SQS + DLQ → EventBridge Pipe → Standard Step Function → single-task verb Lambdas on **one shared execution role**).
Either may go first; both depend on **107**. **Data quality** = *diagnose* a file or folder (per-column type consistency, null
ratios, duplicates, row counts, ragged rows, encoding, cross-file column agreement) and write a report — read-only, never
modifies a source; inputs CSV/TXT, JSON/NDJSON **and Parquet** (so you can verify what the converter just produced). **File
converter** = *fix* it: CSV/TXT and JSON/NDJSON → typed Parquet, doing the **multi-file schema reconciliation Table
Builder skips** (Table Builder infers from a single sample file and silently drops columns absent from it).

**The engine is Athena, not Lambda — this is the v3 decision and it drives everything.** Lambda's hard ceiling is **900 s**;
a full pass over 250 GB is 30–80 minutes for conversion and *hours* for a Python scan. Polars lazy/streaming reads fix the
*memory* problem but not the *time* problem — the bytes still have to move. **Fargate was considered and rejected**: its only
network mode is `awsvpc`, so every task needs a subnet, meaning a **VPC in a project that has none**, plus ECR, a Docker
pipeline and an ECS cluster — all to get a *single big box* doing serially what Athena parallelizes. So: the converter runs
**Athena `UNLOAD`** (deliberately `UNLOAD`, not `CTAS` — both write real Parquet files, but `CTAS` also registers a Glue table
that must then be dropped; files are the deliverable), and data quality runs **one Athena profile query** over a temp external
table. **The consequence, stated plainly: both execution roles now need Glue + Athena + Lake Formation admin** (target DBs are
dynamic per-user/per-space so can't be statically LF-granted — same reasoning as SPEC-070). The earlier design's "zero catalog
access, tiny blast radius" property is **deliberately surrendered**; it was a real virtue and 250 GB is worth more.

Cross-cutting decisions that shape both arcs: **(1) the Athena poll lives in the STATE MACHINE** (`Wait → check-query →
Choice`), not inside a Lambda — table-builder's `execute-ddl` polls in a 300 s Lambda, which is fine for a `CREATE TABLE` and
**fatal** for a 20-minute query; SFN Standard executions run for up to a year, so the time ceiling disappears. The per-file
`Map` of the earlier design is **gone** — Athena fans out internally. **(2) the `Catch` always reaches cleanup** — both
pipelines create temp Glue tables in the *user's own* database, and the converter can leave partial Parquet in the destination
(over which a later Table Builder run would build a table full of **partial data with no error**). **(3) an S3 manifest between
SFN states**, never inline arrays — a large file list blows the **256 KB state-payload limit**, and `States.DataLimitExceeded`
escapes every `Catch`, so the user gets *no notification at all*. **(4) a hashed `MessageGroupId`** (SHA-256 of the location) —
SQS caps it at **128 chars** while S3 keys reach 1024. **(5) an explicit IAM `Deny s3:PutObject` on `*/user_settings/*` and
`*/DO_NOT_DELETE.txt`** — the user-space policy denies *delete* there but leaves *put* wide open, so any space-scoped writer
could overwrite `notifications.json` and destroy the inbox **unrecoverably** (the user can't delete the corrupt file either).

Two capabilities are **deliberately given up**, and both are stated loudly in the specs so nobody "fixes" them back.
**Heterogeneous CSV headers are REJECTED** (SPEC-117): an Athena external table has one schema for the whole folder and reads
CSV *positionally*, so mismatched files would be **silently misaligned** — a conversion that reports success and produces
garbage. Type widening still works fully; only column *union* is lost, and only for CSV (JSON's serde matches by key name and
is unaffected). And **two data-quality checks are approximate** (SPEC-112): a SQL engine never sees raw bytes, so **encoding**
is a sampled byte-scan (with its coverage percentage) and **ragged rows** are counted via a single-column raw-line table
(quoted delimiters over-count). Everything else is **exact** — and exactness is an *upgrade*: duplicate rows are now counted
exactly via `GROUP BY … HAVING`, where the Lambda design had to sample them to avoid a memory bomb.

**Excel is deferred entirely (user decision 2026-07-13)** — `.xlsx` is unsupported in both arcs; the `convert-excel` branch +
`fastexcel` layer were removed from the drafts. **The converter's destination stays user-chosen** (user decision; a locked reserved namespace was rejected). The
accepted residual risk — output nested **under** an existing table's folder is picked up by that table's queries — is mitigated
by the empty-destination rule (a live table's location is never empty, so the *direct* case is blocked with zero catalog calls),
the reserved-prefix blocklist, the IAM `Deny`, and a **SPEC-120 dialog warning that must name that specific case**.

**Corrections in v3.1** (an adversarial review checked every Athena claim against AWS docs; four were wrong and load-bearing).
**(a) There is NO workgroup query-timeout setting** — it's an **account Service Quota**, 30 min default, 240 max, raised only by
a **support ticket**. That, not Lambda and not Athena's throughput, is the **real ceiling on both features**, and it is a
**ship-blocking prerequisite**. **(b) `bytes_scanned_cutoff_per_query` must be unset** — the existing portal workgroup's 10 GiB
cutoff (`analytics/athena.tf:36`) is 25× under a 250 GB scan, so copying that shape would make every real query fail; removing
it removes the project's only cost guardrail on its most expensive operation. **(c) `UNLOAD` does NOT enforce an empty
destination when partitioning**, so our pre-check is the *only* guard — and **`StartQueryExecution` needs a
`ClientRequestToken`**, or an SFN `Retry` after a post-submission error starts a *second* UNLOAD and the output **silently
doubles**. **(d) Temp-table names must be safe identifiers** (`dq_tmp_{hex32}` / `fc_tmp_{hex32}`) — a leading underscore needs
backticks and a raw UUID's hyphens parse as subtraction, so the original DDL simply would not run. Also: the **Hive** JSON SerDe,
not OpenX (AWS warns OpenX invents nulls — which would poison the "a null means the key was missing" story these arcs rest on);
Athena needs an **explicit column list** (it does not auto-detect Parquet schemas), so `inspect-source` carries a polars layer in
**both** arcs; and **compressed text is not splittable**, so a single large `.csv.gz` is one worker and is rejected up front.

**Security fix (v3.1):** the file-converter's `Cleanup` state — which deleted "partial output under the destination" — was an
**authenticated cross-user file-delete primitive**. The delete could not be scoped in IAM (the destination is body-supplied, so
the resource can only be `{bucket}/*`), and the `Catch` reached cleanup from **every** state including `validate-authorize` — so
a message with a garbage token and someone else's path would fail validation and *then delete their files*. **`s3:DeleteObject`
is now granted nowhere in either arc.** `drop-temp-table` touches **Glue only**, which is what makes it safe on every path.
Partial output after a failed conversion is left for the user to delete, and the empty-destination rule turns that into a
**safety interlock** against re-running into a half-populated folder.

**SPEC-122 — the optional chain to Table Builder** (user request, 2026-07-12). A **"Create a table from the converted files"**
checkbox on the convert dialog; ticked, the converter **enqueues a Table Builder request** once the conversion succeeds. Table
building **stays in Table Builder** — the converter enqueues and gets out of the way, so there is still exactly one implementation
of "create a table from a folder." The hard part is the **trust boundary**: Table Builder never trusts a body-supplied actor, a
Lambda cannot mint a user's token, and a forgeable assertion would let someone create a table **in another user's database over
another user's data**. So Table Builder gains an **internal FIFO queue the portal role cannot write to**, fed into the same state
machine by a **second Pipe whose input transformer stamps the trust marker** (the public Pipe stamps it `null`) — the marker is
**infrastructure-set and cannot be smuggled in a body**, and a trusted producer asserts **identity only**, never entitlement.
**Note:** the shipped notifications pipeline is *not* a safe model to copy — `notifications_writer.py::_resolve_username` takes
`username` straight from the body for `create` while the portal role can write to that queue, so a browser can inject a
notification into any other user's inbox today. **Real, shipped, low-severity, and tracked separately.** SPEC-122 is **additive and
last**; nothing else depends on it.

**SPEC-123 — the data-quality runs dashboard** (user request, 2026-07-12). The arc already stored **one JSON per run in a hidden
folder** (`{space}/_data-quality-reports/{requestId}/report.json`) with a drill-down view — but had **no parent page and no nav
entry**, so a report was reachable *only* from its notification and **dismissing the notification lost it**. **123** adds a
`/data-quality` list page (a **primary nav** entry + an `AppNavDrawer` destination), aggregating runs across the user's personal
space and their shared spaces, newest first, 10/page, with verdict and `Sampled` chips — drilling into the SPEC-113 report view.
**The mechanism that makes it possible is a per-space `index.json`**: listing the reports prefix and GETting every report would be
one round-trip per row *and* return them in **UUID order — no chronology at all**, so "recent checks" would be randomly sorted and
would get slower the more the feature is used. `assemble-report` therefore appends a small entry (location, verdict, timestamp,
file count, sampled-flag) under **optimistic ETag CAS** — the same lost-update fix SPEC-082 already applied to the shared-space
registry, needed here because checks of *different* locations run in parallel. **The index is a convenience, never a dependency:**
an exhausted CAS is logged and swallowed, the report still lands, the notification still fires. v1 lists **completed checks only** —
failures live in notifications, and the page says so rather than lying by omission.

**SPEC-124 — starting a check *from* the dashboard** (user request, 2026-07-14). 123 gives checks a home page but **no way to start
one from it**: the only entry point is the Files browser, which is the right place when you are looking at your files and the wrong
one when you are looking at your history. **124** adds a **"New quality check"** action (header + empty-state CTA) opening a modal
that asks the only question the pipeline needs — *which data?* — as a **space selector over `DestinationPicker`**, the exact
`SaveResultsDialog` composition (SPEC-055/039). **Both entry points enqueue through the same `useDataQualityCheck` hook** — there is
one enqueue path in the SPA, not two. The one real change is that the picker renders files as **deliberately non-interactive** rows
(a file is never a move/copy/save destination), so it gains an **opt-in `selectableFiles`** mode — opt-in because three shipped
callers depend on the current behaviour. And because the arc persists nothing until `assemble-report` runs, a just-started check is
**not in the list**: 124 pays that off with a dismissible "check started — it will appear here when it finishes" banner rather than
leaving the user to conclude the button did nothing. **Browser-side only: no new IAM, env var, AWS call, or Lambda change.**

Build order **107 → (108→114) → 123 → 124 and/or (115→121) → 122**. New env vars `VITE_DATA_QUALITY_QUEUE_URL` and
`VITE_FILE_CONVERTER_QUEUE_URL` (each needs **four** wiring points incl. a **hand-set GitHub repo variable**). Each foundation
spec ships as **two PRs** — deploy-role IAM applies *before* the module's resources. Both arcs add their execution role to
`aws_lakeformation_data_lake_settings.admins` as a **constructed string in root `locals`**, never a module output (an unknown
element in that `compact()` silently drops the change).
