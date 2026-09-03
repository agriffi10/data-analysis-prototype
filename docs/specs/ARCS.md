# Spec Arcs — narrative context

Why each arc exists and how its specs fit together. **Pulled on demand**, not at session start — `INDEX.md`
carries status, this file carries reasoning. **These headings name a spec range and nothing else** —
status written into them rotted silently, four arcs at a time. Most arcs below are shipped; their
authoritative detail lives in `docs/spec-delivery/SPEC-XXX-*.md` and the per-arc architecture docs.

A spec cut for **size** (`process.md` §4 — past 8 FRs, write a second spec rather than growing one)
always leaves an arc entry here holding the pair's build order, even when nothing else groups them.

**Arcs** — one `##` per arc; read only the one you're in:

- [File-operations arc (SPEC-015 → 020, + 039 copy)](#file-operations-arc-spec-015--020--039-copy)
- [Analytics arc (SPEC-032 → 036)](#analytics-arc-spec-032--036)
- [Query-editor UX follow-ups (SPEC-040 → 042)](#query-editor-ux-follow-ups-spec-040--042)
- [Query-editor UX, round 2 (SPEC-043 → 044, + 041 amend)](#query-editor-ux-round-2-spec-043--044--041-amend)
- [Query-editor UX, round 3 (SPEC-046 → 049, one-offs)](#query-editor-ux-round-3-spec-046--049-one-offs)
- [Shared-connections arc (SPEC-050 + 056 → 055)](#shared-connections-arc-spec-050--056--055)
- [Notifications arc (SPEC-058 → 061)](#notifications-arc-spec-058--061)
- [Control-plane refactor (SPEC-062, standalone)](#control-plane-refactor-spec-062-standalone)
- [Query-editor UX, round 4 (SPEC-063 → 065, user-feedback one-offs)](#query-editor-ux-round-4-spec-063--065-user-feedback-one-offs)
- [Create-Table-from-Files / "Table Builder" arc (SPEC-066 → 071, + 072 producer)](#create-table-from-files--table-builder-arc-spec-066--071--072-producer)
- [Query-editor UX, round 5 + file-browser one-off (SPEC-077 → 080, + 081)](#query-editor-ux-round-5--file-browser-one-off-spec-077--080--081)
- [Table-Share arc (SPEC-088 → 093, + 094 producer)](#table-share-arc-spec-088--093--094-producer)
- [App-shell / schema-rail UX one-offs (SPEC-085, 086)](#app-shell--schema-rail-ux-one-offs-spec-085-086)
- [Best-practice audit follow-ups (SPEC-082 → 084)](#best-practice-audit-follow-ups-spec-082--084)
- [Responsive & Files-UX arc (SPEC-095 → 104)](#responsive--files-ux-arc-spec-095--104)
- [Control-plane-common prerequisite (SPEC-107)](#control-plane-common-prerequisite-spec-107)
- [File-converter arc (SPEC-115 → 122 — cancelled)](#file-converter-arc-spec-115--122--cancelled)
- [Data-quality arc (SPEC-108 → 114, + 123 → 124)](#data-quality-arc-spec-108--114--123--124)
- [Observability arc (SPEC-127 → 137)](#observability-arc-spec-127--137)
- [Refresh-table arc (SPEC-143 → 144 → **149** → 145)](#refresh-table-arc-spec-143--144--149--145)
- [Username-directory arc (SPEC-146 → 147 → 148)](#username-directory-arc-spec-146--147--148)
- [Audit-remediation arc (SPEC-150 → 156)](#audit-remediation-arc-spec-150--156)
- [Cross-arc follow-ups (SPEC-157, 158)](#cross-arc-follow-ups-spec-157-158)
- [Table-share-at-scale arc (SPEC-160 → 161)](#table-share-at-scale-arc-spec-160--161)
- [Feature-flags arc (SPEC-162 → 163)](#feature-flags-arc-spec-162--163)
- [Send-files arc (SPEC-164 → 165 → 166 → 167)](#send-files-arc-spec-164--165--166--167)
- [Archival arc (SPEC-168 → 169 → 170 → 171 → 172)](#archival-arc-spec-168--169--170--171--172)
- [Saved-queries-in-spaces arc (SPEC-173 → 174 → 175)](#saved-queries-in-spaces-arc-spec-173--174--175)
- [Data Explorer arc (SPEC-176 → 185)](#data-explorer-arc-spec-176--185)
- [File-operations control-plane arc (SPEC-187 → 191)](#file-operations-control-plane-arc-spec-187--191)
- [API-layer & containerisation arc (SPEC-192 → 202)](#api-layer--containerisation-arc-spec-192--202)
- [Transition identity arc (SPEC-203 and SPEC-205)](#transition-identity-arc-spec-203-and-spec-205)
- [Container-lambdas arc (SPEC-212 → 213 → 214)](#container-lambdas-arc-spec-212--213--214)

---

## File-operations arc (SPEC-015 → 020, + 039 copy)

Turns the read-only browser into a filesystem:
download, upload, create-folder, metadata, delete, move, rename, large-file upload, copy. All
build on SPEC-013 (authenticated user-space bucket). Move/rename = copy-then-delete; copy (039)
reuses the same `copyObject` minus the delete (additive, same-folder auto-suffix). Folder ops are
recursive + non-atomic. See architecture.md → *Constraints that shape the system*.

---

## Analytics arc (SPEC-032 → 036)

A second portal surface: an in-app Athena query workspace beside the
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

> **SUPERSEDED in part by SPEC-199 (2026-08-29): the browser no longer calls Athena or Glue.** All
> six calls — start, status, results, stop, get-database, list-tables — go through the API, which
> derives the workgroup, the results location and the caller's identity from the verified token;
> `@aws-sdk/client-athena` and `@aws-sdk/client-glue` are gone. Nothing above the service boundary
> moved, and **the isolation model is unchanged** — Lake Formation grants attach to a principal, and
> the principal is the same portal role, assumed by the API rather than vended to the browser. Full
> entry: `decisions/analytics.md` → *`stateChangeReason` rides a 200*, and `decisions/identity-and-access.md`
> → *The API makes exactly ONE AWS call per request*.

---

## Query-editor UX follow-ups (SPEC-040 → 042)

Refines the SPEC-035/036 workspace without touching the data
layer or IAM: 040 persists the un-run editor draft across tab switches/reloads (`sessionStorage`,
per-user) and adds a **Clear** button; 041 turns the editor into **query tabs** (`Query N`, monotonic
labels, closable-with-confirm, per-tab persisted text) and supersedes 040's single-draft storage;
042 paginates the history drawer (7/page, Prev/Next, newest-first, client-side). 041 needs a design
pass (new tab strip in `query-workspace.html` + §6) before code.

---

## Query-editor UX, round 2 (SPEC-043 → 044, + 041 amend)

Builds on the tab model: 043 adds **saved
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

---

## Query-editor UX, round 3 (SPEC-046 → 049, one-offs)

Small, mostly independent additions on the
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

> **047's active-database model was removed by SPEC-077** (round 5, below): no workspace/current database anywhere —
> every base table is fully-qualified `database.table` and the schema rail is browse-only. Read the switcher and DB-chip
> text above as history; full entry in `docs/decisions/`.

---

## Shared-connections arc (SPEC-050 + 056 → 055)

Bucket 2 (`dat-prod-shared-space`): user-created, uniquely-named,
non-renameable shared connections (name = shared S3 prefix = shared Glue DB), provisioned by an async
**SQS → EventBridge Pipe → Step Function** pipeline (validate → create → update permissions). Access is
gated by a **membership principal tag** on the shared role (10 bounded Cognito attribute slots; LF grants
the role per shared DB, IAM tag is the gate — same shape as the personal `username`-tag model). Source of
truth = an **S3 control-object registry** in the analytics admin bucket (`shared-spaces/` prefix,
pipeline-only); each user's `{username}/user_settings/shared-connections.json` is a UI **cache** the pipeline
writes (pending/active/failed status). Shared-DB query results route to the shared prefix. Decision record:
`lambdas/info/planes/shared-spaces.md` (reverses the "no backend" decision for shared-space mutations only).
The specs compose as: 050 = foundation plumbing (buckets, SQS/Pipe/Step
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

---

## Notifications arc (SPEC-058 → 061)

A per-user notifications inbox. A notification is `{id, message, read,
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

---

## Control-plane refactor (SPEC-062, standalone)

The shared-space control plane shipped (050→054) as a **single
711-line provisioner Lambda** with an `action`-switch (create/add_members/remove_members/leave/delete) + inline JWT
verify + all helpers, under one broad orchestrator role. SPEC-062 decomposes it to the architecture's original intent
(§7 "provisioning Lambda(s)"): the **Step Function orchestrates single-task Lambdas** — `entry → validate-authorize →
Choice(action) → <verb Lambda> → success/failure` (Retry/Catch in the state machine), one Lambda per verb, shared
code (auth/registry/clients/cache/notify) in a common module/layer, and **per-verb least-privilege roles** replacing
the monolith role. **Behavior, the request contract (056), the membership-tag model, and registry/cache shapes are
unchanged** — structure only — plus two clarifications: **create stays creator-only** (no member-add at create; adds go
through 053 from the Connections tab), and each verb **emits its SPEC-061 notifications inline** via the shared helper.
The old provisioner function/role/tests are removed at cutover. Follows `lambdas/info/best-practices/lambdas/lambdas.md`;
decision recorded in `lambdas/info/planes/shared-spaces.md`.

> **The per-verb least-privilege roles were descoped (user decision, SPEC-062 FR-005):** every verb runs on **one
> shared orchestrator role**. Read the roles claim above as history; full entry in `docs/decisions/` → *Bucket 2
> (shared-space)*.

---

## Query-editor UX, round 4 (SPEC-063 → 065, user-feedback one-offs)

Three independent presentation/editor refinements
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

> **The active-database model referenced above was removed by SPEC-077** (round 5, below): no current database anywhere —
> 063's radio-style active control is gone (the tree is browse-only) and 065's autocomplete became schema-wide over
> fully-qualified `database.table` names. Read the active-DB references as history; full entry in `docs/decisions/`.

---

## Create-Table-from-Files / "Table Builder" arc (SPEC-066 → 071, + 072 producer)

A new
**dedicated** async control plane (its own FIFO **SQS → EventBridge Pipe → Step Function**, **single-task Lambdas**
with per-verb least-privilege roles) that turns a folder of data files into a Glue/Athena **external table** in the
database the space maps to (personal = username; shared = space name). Decision record:
`lambdas/info/planes/table-builder.md` (read first). Reuses the **pattern** of the shared-spaces control plane
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

> **The per-verb least-privilege roles were descoped here too (same user decision as SPEC-062):** the five verbs run
> on **one shared execution role**. Full entry: `docs/decisions/` → *Table Builder (SPEC-066→072)*.

---

## Query-editor UX, round 5 + file-browser one-off (SPEC-077 → 080, + 081)

A user-feedback batch (2026-07-01), no
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

---

## Table-Share arc (SPEC-088 → 093, + 094 producer)

Filed 2026-07-04; "**share a table** across databases." From the Query schema rail, a user shares any accessible table to one or more **users** and/or **shared spaces**: the data files are **copied** into each recipient's space under `shared_tables/{table}/` and a table of a chosen name is **created** over the copy in the recipient DB. A **new dedicated** async control plane (its own FIFO **SQS+DLQ → EventBridge Pipe → Standard Step Function**, single-task Lambdas + a **`table-share-common` (`tscommon`)** layer, **one shared execution role that is an LF admin**) mirrors the table-builder/shared-spaces pattern (reuses the pattern, not the resources). The SFN: **validate-authorize** (ID-token actor; actor must have **source** access — personal = own DB, shared = active member) → **inspect-source** (`GetTable`, **clone the source table definition**; reject views / catalog-partitioned / non-external; list objects; enforce object/size caps) → **`Map` over recipients** (per-item Catch): **check-target-absent** (fail that recipient on name conflict / non-empty prefix) → **copy-objects** (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → **create-table** (clone def, repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Decisions (2026-07-04):** push (no consent; recipient notified), clone-not-infer (format-agnostic), parallel `CopyObject` (Batch Ops deferred), **any space is a valid target** (source access still gated), conflict = **fail that recipient only** (no overwrite), v1 sources = **flat or projection-partitioned** base external tables. Build order 088→…→093; **094** (notifications: actor per-recipient outcome + recipient "shared with you") after SPEC-058 + the verb Lambdas. Decision record: `lambdas/info/planes/table-share.md` (read first). New infra: `infra/modules/table-share/`; new browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`.

> **Superseded in part by SPEC-160 (2026-08-10):** "parallel `CopyObject` (Batch Ops deferred)" no
> longer describes the plan. **S3 Batch Operations is rejected, not deferred** — its Copy cannot
> rewrite a key (`TargetKeyPrefix` prepends the full source key) and it caps objects at 5 GB. The
> scale path is a top-level **Step Functions Distributed Map** over a flat `(recipient × object)`
> manifest, running the same copy code. Full entry: `decisions/` → *Table Share*.

> **"An LF admin" is history in one load-bearing way (SPEC-111 correction):** admin status does **not** confer
> `CREATE_TABLE` — table creation rides the `portal-managed` LF-Tag (TBAC). Full entry: `docs/decisions/` →
> *Control-plane table creation = TBAC*.

---

## App-shell / schema-rail UX one-offs (SPEC-085, 086)

Filed 2026-07-02, both presentation-only (no data-layer/IAM/infra).
**085** adds a **collapsible side nav**: the Files spaces `Sidebar` and the Query `SchemaBrowser` share the same 248px rail
chrome, so it's factored into one **`CollapsibleRail`** base component with a collapse control; collapsed = **fully hidden +
a reopen handle** (not a slim icon rail), and the state is **persisted per browser in `localStorage` under one shared key**
so the choice carries across both rails. Below-`tablet` behavior (rail hidden) and the top-bar tabs are untouched. **086** adds a
**per-database Refresh** control to each schema-rail `DatabaseNode` (SPEC-063) that re-reads only that database's tables/views
(`queryKeys.schema(database)` invalidate/refetch via the existing `useSchema`/`invalidateSchema`) — manual, per-node, error
non-destructive; mirrors the SPEC-046 history-refresh pattern. Both are independent of each other and of everything else.

---

## Best-practice audit follow-ups (SPEC-082 → 084)

Filed 2026-07-02 from a read-only audit of the Lambdas + SPA against
`docs/best-practices/`; all code-only, no IAM/infra. **082** fixes a lost-update race in the shared-space **registry**
writers (`finalize`/`save_members`/`set_status`/`reserve` retry) by giving them the same optimistic ETag CAS the
`cache.py` sibling already uses. **083** bundles the cross-cutting Lambda hardening items (config validate-at-init;
table-builder handlers validating event shape into typed terminals + actor notify instead of bare `KeyError`; type hints
on public signatures; thin the fat handlers + small Python-style fixes) **plus the lower-priority SPA smells folded in as
FRs** (memoize unstable context/hook identities + `QueryWorkspace` derived structures; harden the `useNotifications`
timer cleanup; fix the query submit de-dupe guard's stale read; resolve `QueryResultsTable` index keys). **084** makes
the query editor's Monaco completion-provider registration/disposal remount-safe
(tab switches / StrictMode) so autocomplete can't silently die. All three are independent of each other.

---

## Responsive & Files-UX arc (SPEC-095 → 104)

Filed 2026-07-08 from the Claude Design
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

---

## Control-plane-common prerequisite (SPEC-107)

Filed 2026-07-11. `tbcommon/auth.py` and `tscommon/auth.py` are already
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

---

## File-converter arc (SPEC-115 → 122 — cancelled)

> **THE FILE-CONVERTER ARC (115 → 122) IS CANCELLED (2026-08-03, user decision).** A data converter
> is not a feature this product will carry. Nothing was built — no infra, no Lambdas, no IAM — so
> there is nothing to unwind; the eight specs stay in the repo as `Cancelled` for the design record
> only. **Do not build them, and do not treat the arc narrative below as pending work.** The
> file-converter architecture record has been removed (never built). Everything the text below says
> about *data quality* (108 → 114) still stands and shipped — the two arcs were always independent.

The converter-only design survives interleaved in the data-quality narrative below (the two arcs were filed and
re-architected together): the `UNLOAD`-not-`CTAS` choice, the v3.1 `ClientRequestToken` double-output trap, the
Cleanup cross-user-delete security fix (the origin of the no-`s3:DeleteObject` rule both arcs share), and SPEC-122's
trust-marker design. Read all of it as design record only.

---

## Data-quality arc (SPEC-108 → 114, + 123 → 124)

**Data-quality arc (108 → 114)** and **file-converter arc (115 → 121)** — filed 2026-07-11 from
their architecture decision records (data-quality since folded into `lambdas/info/planes/data-quality.md`; the file-converter record and the 2026-07-11 review doc are removed), both **re-architected (v3)** after that review **and** the 250 GB source-file requirement. Two **independent** dedicated async control
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

> **"Lake Formation admin" was corrected by SPEC-111:** admin status does **not** grant `CREATE_TABLE` — table
> creation rides the `portal-managed` LF-Tag (TBAC). Full entry: `docs/decisions/` → *Control-plane table
> creation = TBAC*.

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
**Note:** the shipped notifications pipeline was *not* a safe model to copy — see `docs/security-baseline.md` →
*Design finding — notifications `create` spoofing*. **Superseded by SPEC-206 (2026-08-24):** that finding is
closed. The notifications writer now applies the same principle by a different mechanism — rather than a
second queue stamping a trust marker, it reads the `SenderId` SQS stamps on every message and refuses a
`create` sent with browser credentials. The marker is still infrastructure-set and still unsmuggleable;
it is simply the service's own, so no queue or Pipe was added to carry it.
**It is not the pattern to copy here, though:** SPEC-206 is a **deny of one principal**, which works
only because exactly one sender on that queue is user-reachable. Table Builder's marker is a positive
**allow** — a trusted producer asserting identity — and that is what a plane with several reachable
callers needs. SPEC-122 is **additive and
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

---

## Observability arc (SPEC-127 → 137)

**Why it exists.** Every Lambda in this repo logs free-form English to CloudWatch. That answers "what happened in this one
invocation" and nothing else: there is no way to ask for a p95 duration, a week of failures, or every event in one request,
because nothing in a log line is a *field*. **`log-foundry`** (`agriffi10/log-forge`, PyPI `log-foundry`) is the fix — a
zero-dependency library that emits one identically-shaped JSON record when a call starts and another when it ends, carrying
duration, status, and W3C trace/span IDs.

**SPEC-127 builds the pipe, not the instrumentation.** A **standard** (non-FIFO) SQS logs queue, swept on a **5-minute
EventBridge schedule** into the admin bucket as Hive-partitioned NDJSON at `logs/{service}/dt=…/hh=…/`. Three constraints shaped
it. The queue **cannot be FIFO**, unlike every other queue here, because `SQSSink` sends no `MessageGroupId` — ordering is
recovered from the records' own `timestamp`/`log_id`, not from delivery.

> **All three of those were reversed by SPEC-129, and this paragraph describes 127 as it was built rather than the pipe as it
> runs.** The queue is now **FIFO** with `message_group_id` = the service (`log-foundry` 0.5.0 removed the `MessageGroupId`
> constraint), the sweep is on a **10-minute** schedule, and the layout is **one appended object per service-day** at
> `logs/service={s}/year=/month=/day=/data.jsonl` — so every write is an ETag-CAS read-modify-write. Read this paragraph as
> history; `decisions/` and `spec-delivery/SPEC-129` carry the current shape. Delivery is a **pull, not a push**, for the reason
#270/#271 already established: an event-source mapping or Pipe idle-long-polls a queue that is empty almost always, and that
idle polling was the bulk of the account's SQS volume — so the sweep short-polls (`WaitTimeSeconds=0`) explicitly, since a
scheduled consumer sitting in a 20-second long poll reintroduces the same bill from the other direction. And `service` arrives
**inside an untrusted body and becomes an S3 key**, so it is pattern-validated and anything unroutable is written verbatim to
`logs/_unrouted/` and deleted — every message routable means every message deletable, which is what keeps a malformed body from
redelivering every 5 minutes until retention. Two **upstream** changes gate the whole arc (SPEC-127 FR-001): the package
declares `requires-python >=3.13` against this repo's `python3.12` fleet, and its `shutdown()` is **terminal** — it never resets
the module-level worker, so a handler that flushes the obvious way logs nothing for the rest of that warm container's life.
Both are one-line upstream fixes (relax to `>=3.12`; add a non-closing `flush()`), pinned exactly because the `cpcommon` layer
attaches to every control-plane verb.

**SPEC-128 is the pilot**, and data-quality is the right one: the **longest** plane (nine verbs, so cross-verb correlation
actually pays), the **newest** (least understood under real load), and **entirely operator-facing** — a mistake costs log
quality, not access. Its honest limitation is recorded rather than discovered: `log-foundry`'s trace context is per-process, so
one run is **nine traces**, joined on a `request_id` field. True stitching needs an upstream `lf.continue_trace()` plus two more
values threaded through the state payload, and is deliberately sequenced *after* the pipe is proven live (user decision,
2026-07-22: correlation now, stitching later).

**Two user decisions run against the recommendation and are settled, not open.** `logs/` gets **no lifecycle rule** — nothing is
ever lost, at the cost of unbounded growth with no ceiling; the invariant that keeps it safe is that every existing rule on the
admin bucket carries a prefix filter, pinned by assertion. And the sink is **SQS only**, not `MultiSink(Stdout, SQS)` — if the
queue or sweep breaks, that window's trace data is gone, with `SQSSink`'s stderr write as the only breadcrumb. Note what that
does *not* mean: the ~20 existing `logging.getLogger()` call sites are untouched and CloudWatch still receives all of them, so
SPEC-126 FR-004's forensic log is unaffected.

Build order **127 → 128 → rollout**. 127 ships as **two PRs** (deploy-role IAM applies before the module's resources). No
`VITE_` variable and no SPA change anywhere in the arc — `log-foundry` is a Python library. The new Lambda variable
`LOGS_QUEUE_URL` is **optional by construction** (`os.environ.get`, never `_require`), which is precisely what lets the
rollout proceed one control plane at a time instead of touching all 34 functions' environment blocks at once.

**SPEC-130 → 133 add the narrative the first three specs deliberately left out.** 127/128/129 built a pipe and proved it
carries something; what it carries is *boundaries* — a `span.start`/`span.end` pair per invocation and nothing between them.
That answers which verb failed and how long it took, and is silent on what it was doing, which is the question an operator
actually arrives with. The content already exists: the sweep and the verbs narrate themselves in ~20 `logging.getLogger()`
calls that reach CloudWatch and never reach the store those same functions feed.

**130 is the foundation and ships alone, changing no call site**, because `cpcommon` attaches to every control-plane verb and
a layer change plus nine call-site changes is not one blast radius. It adds the sanctioned emitters (`info`/`warning`/`error`,
never-raise, so nobody imports `log_foundry` directly and bypasses the discipline the module is built around) and `step()` for
child spans. It also fixes two identity defects that instrumenting on top of would have multiplied: every root span in the
fleet reports `function: "handler"` — `traced` never passed a `name`, and every Lambda entry point in this repo is named
`handler` — and `verb` was a span *default*, so the first child span would carry `request_id` but not the verb that produced
it. Naming the root span after the verb is a **discontinuity in a store retained forever** and is accepted without migration;
`fields.verb` stays populated so queries span the cutover.

**The two consumers are shaped by amplification, not by taste.** The sweep instruments itself, so its events go to the queue
it drains: a sweep emitting one event per message consumed would give the queue a floor it can never drain below, so SPEC-131
requires its event count to be `O(1)` in messages and `O(G)` in day-groups, with a test that fails when a per-message emitter
is added. SPEC-132 has the same hazard twice — `check-query` runs on a 30-second poll for as long as the profiling query does
(minutes to tens of minutes, since the poll was moved into the state machine to escape Lambda's 900 s ceiling), so it narrates
**transitions only**; and byte-scan and inspect-source iterate per file, per region and per column, so those get no step and
no emitter.

**One rule spans all four, and the line is drawn at file contents — not at user-derived data** (user decision, 2026-07-23).
`logs/` lives in the **admin bucket** and is read by administrators for administrative purposes, and that destination is what
makes user-derived *metadata* the right thing to log rather than the wrong thing: file names, S3 keys and locations,
usernames, database/table/column names and space names are all permitted and encouraged, because an operator debugging a
failed run needs to reach the object. **Usernames are not sensitive here** — the username already *is* the S3 prefix, the
principal tag and the Glue database name (SPEC-033). The absolute line is **data from inside a file** — a cell value, a
sampled row, a result set, a decoded byte range, the text at an offset a UTF-8 scan rejected — because that can be PII, it is
never needed to debug a control plane, and `logs/` is retained forever. Column *names* are schema and are in; column *values*
are contents and are out. **Tokens and email addresses are out regardless of provenance**: a bearer credential is not
metadata (which is why the drain redacts every known token field before anything logs the body), and an email — unlike a
username — appears nowhere else in these operator records, has no operational meaning here, and would be the only personal
contact detail in a prefix retained forever. And the narrative **never reaches the console** —
`echo=` is prohibited outright, with the one named exposure being `init`'s `StdoutSink` fallback when `LOGS_QUEUE_URL` is
unset, which stays because it is the cold-start safety property the module is shaped around, and which is bounded by the
existing `logging.getLogger()` calls already putting the same keys in CloudWatch. There is deliberately **no runtime
redaction filter**: the rule turns on *provenance* — did this value come from inside a file — and no filter over a field name
or value shape can see that. Enforcement is a name-based tripwire test plus review.

**SPEC-133 instruments `control-plane-dlq-drain`**, the one shared control-plane function outside the pipe entirely, and it is
the only one of the four that touches infra (`LOGS_QUEUE_URL` plus `sqs:SendMessage` on the logs queue, mirroring
data-quality's `EmitStructuredLogEvents`). Its point is not traces: **consuming a DLQ message destroys the evidence**, and
SPEC-126 FR-004 knowingly traded each DLQ's 14-day retention for a log group's 14-day retention. Writing the redacted,
size-capped body as an event upgrades that record to permanent. Two traps shape it. `request_id` must be a **field, never
baggage** — the drain handles up to 400 requests per invocation while `_reset_baggage` runs once, so per-message baggage would
leak one request's id onto the next, which is exactly the fabricated correlation key SPEC-128 FR-002 forbids. And per-message
events are **correct here and prohibited in the sweep**, which only looks inconsistent: the sweep emits into the queue it
drains, so an event per message gives that queue an undrainable floor; the drain emits to the logs queue and drains the
request DLQs, with no feedback loop and an empty-by-design normal case.

Build order **130 → (131 | 132 | 133)**, the three consumers independent once the layer lands. Only 133 needs infra, IAM or a
new environment variable, and nothing in the arc touches the SPA.

**SPEC-134 → 137 finish the fleet** — the remaining 21 functions, one spec per plane plus one for the singletons, each
needing the same infra pair 133 introduced (`LOGS_QUEUE_URL` + `sqs:SendMessage` on the logs queue), since only data-quality
and the sweep have it today. Each is written around what that plane can actually get wrong. **134 (shared-space, 8 verbs)** is
first because it lands the **shared coverage harness** the other three reuse — four copies of an enumeration test is how three
of them drift — and because a single request there touches five stores that can disagree (registry, per-user cache, Glue, Lake
Formation, Cognito slots); every one of that plane's past bugs (#153–155 CAS race, #163/#164 durable intent, #165 `forget`) was
diagnosed by inferring what the registry must have looked like. It is also the only plane with **no `notifies_on_failure`**, so
the decorator-ordering rule stated three times elsewhere is *asserted absent* here rather than looking forgotten. **135
(table-builder, 5)** targets the plane whose canonical failure was a verb that **completed** — SPEC-070's false "LF admin ⇒
`CREATE_TABLE`" meant tables silently were not created (four PRs, #243–246, to find) — so the DDL, its Athena
`StateChangeReason` verbatim, and the table's post-condition are all logged; its in-Lambda Athena poll gets the same
transition-only treatment `check-query` got. **136 (table-share, 5)** is shaped by the only **`Map` fan-out** in the repo:
three verbs run once per recipient at `MaxConcurrency: 5` with a per-item `Catch`, so `request_id` no longer identifies one
invocation and **`recipient` is mandatory on every fan-out event** — partial success (2 of 3 shared) is this plane's normal
outcome and must be readable from `logs/` alone. **137 (the three singletons)** is grouped by a shared hazard, not a shared
domain: `notifications-writer`, `pre-signup` and `post-confirmation` do **not** attach `cpcommon`, and attaching it naively is
PR #196 — `config._require` demands six variables at import that none of them has. Verified rather than assumed:
`cpcommon.observability` imports and emits with **zero** env vars (the package `__init__` has no imports; `clients`
lazy-imports boto3), so the layer is safe — and that invariant is pinned by a test importing it in a **subprocess with a
scrubbed environment**, because `conftest`'s env baseline is exactly what hid the problem last time. The stakes there are
uneven: the writer is how every other plane's failures reach a person, and its own DLQ is deliberately undrained (circular),
so its events are the only account of its silence. 137 also closes the loop — its harness entries assert that **every** Lambda
in the repo is registered or explicitly excluded.

---

## Refresh-table arc (SPEC-143 → 144 → **149** → 145)

Filed 2026-08-03 (user request). **Table Builder writes a schema once and never looks again.** It infers columns from a
bounded read of one sample file, issues `CREATE EXTERNAL TABLE`, and stops. When files with new columns land in the same
folder afterwards, Athena keeps returning the old columns and the new data is simply invisible — no error, no warning,
just a narrower answer than the data supports. The only remedy today is to drop the table and rebuild it from the Files
browser, which means leaving the Query workspace and **retyping partition keys that are recorded nowhere but on the table
itself**. This arc is the missing second half of Table Builder, reached from the same table-options menu (SPEC-044) the
user is already in.

**No new control plane, and that is the arc's central decision.** A refresh *is* `inspect-source` plus `infer-schema` run
against a table that already exists — the two expensive verbs, one of which carries the 240 MB polars layer. So the arc
extends the **existing** table-builder plane: same FIFO queue, same Pipe, same Step Function, same shared execution role,
with a `mode: "create" | "refresh"` field on the envelope and a `Choice` around a shared spine. `MessageGroupId` stays the
target database, so a refresh and a build on the same database serialize against each other for free.

**Eligibility turns on shape, not on a marker.** A refresh must faithfully rebuild a table it did not create in this run, so
`load-table-definition` refuses a view, a managed table, and a catalog-partitioned table whose partition metadata it would
silently discard — the checks
`clone_definition` already makes for table-share, and the reason that function **moves to `cpcommon.glue` unchanged**, with
`tscommon.glue` re-exporting it and the refresh path **mapping** its four reason codes at its own call site (`source_is_view
→ cannot_refresh_view`, and so on). The stems differ, so a prefix parameter cannot produce the refresh names, and mapping
leaves table-share byte-for-byte intact. A `portal.managed` TBLPROPERTY *is* introduced (143 FR-007) but deliberately is
**not** the eligibility test: every pre-existing table lacks it, and it is user-writable via `ALTER TABLE SET
TBLPROPERTIES`, so it can be neither a fact nor a permission. A tripwire test fails if any verb reads it. (It is also one
character from the unrelated **`portal-managed` LF-Tag on databases**; both sites carry a comment saying so.) One check is
**not** inherited: `clone_definition` validates only the location's **bucket**, so `load-table-definition` adds its own
**prefix**-within-the-authorized-space check (`table_outside_space`). The catalog is not the authorization boundary, and a
table pointing into another user's prefix has a perfectly legitimate bucket.

**`load-table-definition` exists because the shared spine is not generic**, and this is the constraint most likely to be
re-discovered mid-build. `inspect-source` lists `space.bucket` + `space.prefix` — it has no `location` input — and
`infer-schema` hands its partition keys straight to `build_create_table_ddl`, which requires the **SPEC-069 declared
shape** (`type ∈ {integer,date,string}` plus `range`/`values`/`format`) and raises a bare `ValueError`, not a
`TerminalError`, on a Glue-shaped key. So the verb **normalises**: it rewrites `space.prefix` from the catalog and
**reconstructs** the declared keys from the table's `projection.*` properties, refusing with
`projection_not_reconstructable` rather than guessing. Only data columns are re-derived; a folder whose `key=value/` layout
has drifted fails with the existing `partition_layout_mismatch` rather than quietly adopting the drift.

**The removals design is the part to read before proposing an alternative** (144 FR-003). The requirement was *warn, then
require explicit confirmation*, and the textbook implementation — a dry run that returns a diff and waits — does not fit a
fire-and-forget plane with no synchronous return channel. A plan-artifact pair (new artifact, new index, new view, new IAM,
two async round trips for one button) and a browser-side preview (the browser cannot infer types; that is what the polars
layer is *for*) were both considered and rejected. What ships instead: an `allowRemovals` flag, default false, and a
terminal `columns_removed` failure that **names the removed columns in the notification and changes nothing**. The refusal
*is* the warning. What it guarantees is stated carefully rather than overclaimed: the specific columns are named to the
user in a durable notification before any removal can happen — it does not guarantee they read it. So SPEC-145's dialog
carries an **always-present, always-unchecked** opt-in with explicit consequence copy, and the `columns_removed`
notification carries an **in-app link** (`/query?refreshTable=…&removed=…`, every component a catalog-safe identifier and
so URL-safe and re-validatable) that opens the dialog with the specific names rendered and confirm gated until the box is
ticked. The link matters because a `Notification` in this repo is `{id, message, read, timestamp, link?}` and **carries no
structure at all** — an earlier draft of 145 proposed deriving the outcome from the inbox, which would have meant parsing
prose. The link is the only channel that exists, and SPEC-144 mints it because it owns the message layer.

**The apply is a drop and a recreate**, through Athena, back to back with nothing between them. Safe only because the table
is **external**: dropping it removes a catalog entry and touches no objects, and the execution role's explicit
`Deny s3:DeleteObject` stays exactly as it is. That property is load-bearing and is written into the spec as such — if a
table-builder table ever becomes non-external, the apply becomes destructive. IAM gains one action (`glue:DeleteTable`);
Lake Formation needs nothing, because the `portal-managed` tag-policy grants already carry `DROP` at both database and
table level. `ALTER TABLE ADD COLUMNS` was rejected: it cannot retype, cannot remove, and behaves inconsistently across the
three SerDes in play, so it would be a fourth code path covering only the easiest case. Two sharp edges in `cpcommon/ddl.py`
shape the apply: its `storage=` parameter is a `Storage` NamedTuple carrying a **pre-rendered** clause string, not a bag of
SerDe fields, and the builder emits `CREATE EXTERNAL TABLE **IF NOT EXISTS**` — which on this path would turn a recreate
after a silently-failed drop into a successful no-op, so 144 adds `if_not_exists=False` and a post-condition `GetTable`
(SPEC-135's lesson: this plane's canonical failure was a verb that *completed* while the table was not created). The honest
cost is a **window** of a second or two in which the table does not exist, and the one genuinely bad outcome — drop
succeeds, recreate fails — gets its own reason code and its own wording, because a user who reads "refresh failed" will
assume nothing happened.

> **Superseded in part while building 144 (2026-08-04).** The window is **not** closed by the FIFO queue as 144 FR-006 AC1
> claimed: the Pipe starts executions `FIRE_AND_FORGET`, so `MessageGroupId` serializes delivery, not execution, and two
> refreshes on one database overlap. What actually bounds the damage is narrower — the statements are back to back, both
> carry an Athena idempotency token so a Retry re-attaches rather than re-dropping, and they share one poll budget so
> Lambda cannot be killed between them. Recorded, not fixed. The drop also **destroys catalog metadata**: table identity,
> `Description`/`Owner` and any table-level Lake Formation grant (column comments *are* carried). **`glue:UpdateTable`,
> which replaces the definition in place, is SPEC-149 and is sequenced BEFORE 145** — it closes both the window and
> the metadata loss, and it is what an eventual move to Iceberg would need, since a drop-and-recreate destroys the
> snapshot history that is most of the reason to adopt Iceberg.

> **Superseded outright by SPEC-149 (2026-08-04): the apply is no longer a drop and a recreate.** It is one in-place
> `glue:UpdateTable` — a read-modify-write on the live table — so there is no window, no metadata loss, and no
> `IF NOT EXISTS` question. IAM moved the other way too: **`glue:DeleteTable` was REMOVED**, `glue:UpdateTable` added, and
> no verb on this plane deletes a table any more (the `Deny s3:DeleteObject` is untouched, and Lake Formation's existing
> `ALTER` on the `portal-managed` tag policy is what `UpdateTable` needs). The reason code split above is gone with the
> mechanism — one `update_failed` says nothing was changed, because nothing was. The **concurrent-refresh overlap
> survives**, reduced rather than closed: Glue offers no compare-and-set on `UpdateTable`, so the worst case is
> last-write-wins between two definitions instead of one run seeing no table. See `decisions/` → *The refresh apply
> replaces the definition in place*.
>
> **Superseded by SPEC-157 (2026-08-09):** the overlap no longer survives. A per-table lock in the admin bucket,
> claimed under ETag CAS, serializes refresh outside Glue — the second run is refused with a notification rather
> than racing. Glue still offers no compare-and-set, which is *why* the lock exists. See `decisions/` →
> *A per-table lock serializes refresh, because the catalog cannot*.

**The message layer needs more work than the feature looks like it should need**, and it is in 144's scope for a reason:
`tbcommon/messages.py` is a *failure* table whose renderer hard-codes `Couldn't create table "{name}": …`,
`success_message` takes no reason and hard-codes *"is ready to query"*, and `emit_failure` never reads
`TerminalError.tokens` — which `cpcommon/errors.py` documents as deliberate, tokens having been added so that table-builder
and table-share stayed untouched. Every one of those is correct for a plane that only created tables and every one is in
the way now. 144 also assigns the **no-op notification** to `diff-schema`: the state machine has no notification state,
every emit in this plane is in-Lambda, and on the unchanged path no Lambda runs after it. And because `emit_failure` passes
no `link=` today and `TerminalError` has no link field, 144 has `emit_failure` **construct** the `columns_removed` link
itself from the context it already holds — rather than growing a transport field on `TerminalError` for one caller.

**Two infra traps worth carrying into the build.** `lambda.tf` is `for_each` over the function map, so a new verb needs only
a `locals.tf` entry — but **`stepfunction.tf` passes an explicit per-function `_function_arn` map to `templatefile()`**, so
a new ASL state without a key there fails at *plan* time. And `clone_definition` copies **all** Glue `Parameters`, so a
partitioned table's captured properties always include `projection.*` — which `_tblproperties` regenerates — so 144 strips
them before merging or every partitioned refresh emits each projection key twice.

**Explicitly not built:** propagating a refresh to table-share recipient copies (a share is a one-time snapshot with **no
provenance link in either direction**, so the linkage would have to be invented first), changing partition keys, refreshing
views, and any scheduled or automatic refresh. Build order **143 → 144 → 145**; 143 ships the branch ending in a typed
`not_implemented` stub so the whole path is exercised live before it can change anything. Browser surface is 145 only, and
it adds no IAM, no env var and no new AWS call. Per `transition_plan.md` §2 item 9 the table arcs are feature-flagged off
for Phase 1 of the client transition and re-enabled in Phase 4 against their original acceptance criteria; nothing in this
arc reads the `cognito:username` claim outside `cpcommon.auth`, so it survives unchanged.

---

## Username-directory arc (SPEC-146 → 147 → 148)

Filed 2026-08-03 (user request). **Every flow that asks a user to name another user asks by free text.** `AddMembersDialog`
is a textarea, `TableShareDialog` is an input with chips; both run `parseMemberInput`, which silently drops anything failing
the catalog-safe pattern, and neither checks that a name belongs to anyone — the browser has never had a way to know.

**What happens next is better than this repo's own comments claim, and the arc was nearly specced on the wrong premise.**
`add_members.py` catches `UserNotFoundException` and queues a notification to the space **owner** naming the user it could
not add (pinned by `test_add_unknown_notifies_owner`); table-share reports unresolved recipients too, and
`TableShareDialog`'s inline help already says so. Meanwhile **`add_members.py`'s module docstring and
`parseMemberInput`'s docstring both still say unknown users are "silently ignored"** — stale since the notification landed,
and exactly the kind of wrong comment about error handling that a later design gets built on. Correcting both is in
SPEC-146's scope. The real cost is therefore not silence but **latency and asymmetry**: the report arrives minutes later,
only the owner sees it, the person you were adding still is not in the space, and every typo costs a full round trip
through an async control plane to learn something the browser could have flagged as you typed. The arc replaces
remembering with picking.

**The source is S3 common prefixes on the user-space bucket, not Cognito `ListUsers`** — settled 2026-08-03 after reading
`transition_plan.md`, and the reasoning inverts the obvious answer. *Today* Cognito is complete and S3 is not: the personal
prefix is created **by the browser** on first visit to `/files` (`ensurePrefixMarker`, SPEC-014 — a deliberate
no-backend decision), so a confirmed user who never opened the file browser has no prefix. *After the transition* it
reverses: §2 item 7 settles that **sign-in provisions nothing** — the sync pre-creates every space and `ensurePrefixMarker`
is deleted outright (§6.3) — while federated login makes `cognito:username` a synthetic provider-prefixed value (and under the transition's baseline variant there is no `cognito:username` at all — `transition_plan.md` §6.1)
(§6.1) and users appear in the pool only after first sign-in. So S3 becomes complete and Cognito becomes both incomplete and
wrong-keyed. Choosing the source that is right on the far side of a migration already in flight beats the one right today,
especially when today's gap is bounded (pre-production, no production users) and the failure mode is a missing suggestion in
a field that still accepts free text. **Do not add a Cognito union "to be safe"** — a second source with different
completeness properties is a second thing to reason about every time the directory looks wrong.

**One shared object, one new grant.** A daily `rate(24 hours)` Lambda in a new `infra/modules/user-directory/` module lists
the bucket's top-level `CommonPrefixes`, filters through `CATALOG_IDENTIFIER_RE`, and publishes a sorted JSON document to
`_directory/usernames.json`. `_directory` is the first deliberate exception to the bucket's "every top-level prefix is a
username" invariant, and it is safe for one precise reason: the regex requires a leading lowercase letter, so that name can
never *be* a username — which is why it was chosen. The portal role gains **one** statement, `GetObject` on `_directory/*`,
with no `ListBucket` and no write. Two traps are in scope rather than discovered: the builder role must join the
**user-space bucket policy's principal allowlist** as a constructed string in root `locals` (#241, which has bitten this
repo three times), and the deploy-role `.tftpl` applies as **PR 1** before the module as PR 2 (with function-prefixed Sids, matching the
observability policy's convention, and **no new S3 statement** — the deploy role already holds `s3:*` on that bucket).
Guards worth naming: an empty listing **never overwrites** a non-empty document (a bad list would otherwise erase the
directory, and an empty directory is indistinguishable from a broken feature); the event count is O(1) in users, mirroring
SPEC-131's rule for the same reason; and the builder role's `ListBucket` is **deliberately unconditioned** — an
`s3:prefix = ""` condition is the obvious tightening and is rejected because whether botocore even emits that context key
is an implementation detail that would fail closed, and `simulate-custom-policy` would simply agree with whatever the
author assumed. It is safe unconditioned because the role holds **no `GetObject` anywhere**: it can learn that a prefix
exists — though, stated accurately, it can also enumerate every object *key* under every prefix, since `Delimiter="/"` is a
property of the Lambda's code and not of the grant. Accepted: no `GetObject` anywhere, key names are metadata under the
field rule, and it is a Lambda role with no user-assumable path. If that ever stops being comfortable the fix is a separate
bucket, not an unverifiable condition key.

**The trie lives in the browser, not in the artifact.** The published document is a flat sorted array precisely so the
consumer can choose its own index; 147 builds a character trie from it once per session. A serialised trie would be several
times larger, unreadable when debugging, coupled to one consumer, and pointless — the browser walks the whole document to
build any index at all. Prefix matching alone is not enough (someone hunting `bob_smith` types `smith`), so ranking is
exact → prefix → substring, alphabetical within each band, deterministic, with no fuzzy matching and no recency. **The
substring band is honestly linear** and says so in its own JSDoc — no single-pass structure answers arbitrary substring
queries sub-linearly — so it short-circuits at the result limit and is skipped entirely when the prefix band already filled
it. The hook hands out a stable **`search` callback** rather than the index itself, which is what makes the lazy build
invisible and stops a consumer holding a half-built structure.

**The most important behaviour is that an unknown name is never blocked.** The directory is up to a day stale, misses
not-yet-provisioned users, and is **never an authorization input** — a tripwire test fails if any control-plane verb reads
it, and every existence check stays `admin_get_user` against the User Pool. A combobox that refused an unlisted name would
convert a stale cache into a hard failure, in a flow where an unlisted name is a slower path and not a lost one. So:
suggestions are suggestions, free text always commits, and the "not in the directory" note is neutral, non-blocking, and
**absent entirely** while the directory is loading or unavailable — a note arriving a second after a name was accepted
reads as a delayed rejection, and telling a user their colleague "was not found" because a background fetch failed is worse
than saying nothing. The hook collapses "errored" and "empty" into one `unavailable` status so no consumer has to remember
to handle both.

**The combobox is not the `Menu` primitive**, and that is the easy mistake: `Menu` is `role="menu"` with arrow-key roving,
correct for a menu and wrong here — a combobox keeps focus in the input and moves `aria-activedescendant`. **Escape is not
free either.** `Modal` has no `closeOnEscape` prop, `Drawer`'s is a caller-supplied opt-out a leaf cannot reach, and
`useEscapeKey` is an unconditional `document` listener inspecting neither `defaultPrevented` nor any stop flag — so
"first Escape closes the list, second closes the dialog" rests on React's root delegation and must be **verified**, with a
`defaultPrevented` guard on `useEscapeKey` as an in-scope fallback. The order is tested in the real composition, which is a
field inside a **Modal** inside a **Drawer** (`ManageMembersDrawer` renders `AddMembersDialog`), not the other way round —
and the fixture has to reproduce that drawer's `closeOnEscape={!addOpen && !removing}` gate, because with a bare nesting
both surfaces' document listeners fire on one keydown and the order the shipped app has is simply unreachable.
No dependency is added; if the implementation reaches for a combobox or positioning library, that is a Tech Stack change
requiring a note first.

**148 replaces two inputs and nothing else** — both dialogs enqueue the same fields with the same values, asserted
field-by-field against the pre-spec expectation (not byte-identity: `requestId` is a fresh UUID per call). The two dialogs
take **different** components, because `TableShareDialog` renders **one combined chip list** mixing user and space kinds
with badges: handing chip rendering to `UsernameChipsField` would grow a second list beside it, so it takes the
single-value `UsernameCombobox` and keeps its own list, while `AddMembersDialog` — which has no list today, only a
textarea — takes the chips field outright. The combobox carries an optional **`onCommitMany`** for the same reason:
table-share's user entry is a *bulk* field today (`parseMemberInput(entry)`, placeholder `e.g. bob, cara`), and a
strictly single-value component would have quietly deleted that. The arc also fixes a small long-standing wrong: an invalid pasted token stays in
the input with the existing `CATALOG_IDENTIFIER_RULE` sentence instead of vanishing, via `parseMemberInputDetailed`, which
lands in **147** (its paste handling depends on it) and leaves `parseMemberInput`'s contract untouched. `TableShareDialog`'s
**space** kind keeps its free-text path with suggestions off — space names are a different list from a different bucket
with different membership semantics, and one field pretending to serve both nouns would be worse than serving one well.

> **Superseded by SPEC-158 (shipped).** The space kind is now the same combobox, suggesting the user's OWN spaces from the
> connections cache — one field serving both nouns, because the source became a prop rather than something the component
> reached for. What survives is the reason there is no space *directory*: see `decisions/`.

**Explicitly not built:** a shared-space directory, display names or emails (an email is not metadata under the field rule
and has no place in a document every authenticated user can read), server-side search, fuzzy matching, and any
authorization use. The all-users disclosure is **accepted and recorded** rather than left implicit: a username already *is*
the S3 prefix, the principal tag and the Glue database name (SPEC-033), it is already on every shared-space roster
(SPEC-075), and a prefix-search feature discloses the set by construction. Build order **146 → 147 → 148**; 146 ships as
two PRs; 147 and 148 add no IAM, no AWS resource and no env var — 147 derives the object's location from the existing
`userSpaceBucket()` helper, so the four-point `VITE_*` wiring dance is avoided across the whole arc.

## Audit-remediation arc (SPEC-150 → 156)

A 2026-08-05 whole-codebase audit produced ~40 findings. They are grouped here into **seven specs by plane
and risk profile**, not by severity, because a spec that mixes a browser one-liner with a Lambda data-loss
fix is unreviewable. Read this before picking one up: the ordering constraints below are real, and two of
them will silently produce bad work if ignored.

**The audit's own headline is already discharged.** SPEC-145 merged (#361) with a type error in
`SchemaBrowser.test.tsx`; lint, prettier and all 1301 tests passed because `ci.yml` never invokes the
compiler, so `Deploy App` on `main` went red at 03:10 and was fixed by #362 at 03:19. **#363 then added the gate**
(`npm run build` on every PR), so 150 FR-001 is now only the residue: declaring the `strict` default the
project currently inherits from the compiler. That failure is also the arc's
argument: every spec here closes something the repo already believed was closed.

**The grouping.** **150** is browser + CI guardrails — the typecheck gate, coverage floors, and the
small-but-user-visible defects around them (six "not configured" messages that can never render, an
expired session showing the wrong text on every S3 surface, a double-click that can start two refreshes).
**151** is control-plane correctness with no new infrastructure: the two data-integrity defects
(a single-file data-quality check profiles the whole parent folder, and a sibling-matching listing prefix
can yield `verdict: "clean"` with `rowCount: 0`), teardown freeing a space name while objects remain,
a roster CAS that overwrites the field it protects, and DDL literals bypassing the escaper in the same
module. **152** is split out from 151 *because it provisions infrastructure* — new ASL states and a verb
per plane so that a failure occurring before any verb runs still notifies the user; CLAUDE.md's infra rule
and the deploy-role IAM expansion apply in full. **153** is test and gate integrity — the guards that pass
by coincidence, chief among them that `test_deploy_matrix.py`, written *because* SPEC-137's gates were all
blind, never checks the layer job's copy list against the layer directory, which is SPEC-137's actual
shape. **154** is frontend journey coverage: the suite's real gap is not weak assertions but untested
*wires* — a hook tested with `renderHook`, a component tested with a stub callback, and nothing between.
**155** and **156** are the reuse work, browser and Lambda respectively, deliberately last so no refactor
rides along with a behaviour change.

**Ordering constraints that matter.** **155 Phase 5 must not start before 154 lands** — it decomposes a
1772-line and a 1300-line component, and `FileBrowser`'s upload and collision paths are exactly the ones
154 covers and nothing else does. **156 Phase 3 must not start before 151** — 151 fixes the `casio` 409
predicate *in place* and 156 then moves it; reversed, a bug fix hides inside a refactor. **156 Phase 1
comes before everything else in 156**, because `cpcommon.config`'s import-time `_require` of six env vars
is the *cause* of the duplicated JWKS verifier, not merely adjacent to it. 150, 151, 152, 153 and 154 are
otherwise independent and can run in parallel.

**What the arc deliberately does not do.** No feature work. No `noUncheckedIndexedAccess` (239 sites, two
load-bearing — its own decision). No blanket `fireEvent` → `userEvent` migration; §21 scopes that rule to
new and reworked tests, so it stays opportunistic. No blocking mypy — 153 lands it report-only over the
shared layers as the first notch of a ratchet.

> **Superseded (2026-08-09, notch 2):** mypy is now **blocking** over the shared layers at a cleared
> zero baseline. The arc's scope statement stands as written for 153 itself; the ratchet has since
> moved a notch. Path and current state: the `[tool.mypy]` block of `pyproject.toml`.

No fix for the concurrent-refresh race at the Pipe level:
150 FR-003 closes the browser side, and the real fix is a serialization change that belongs to its own spec.

**One correction the arc carries, because two of five audit passes got it wrong and it would cost real
work.** **TypeScript `strict` is already ON.** `tsconfig.app.json` has no `"strict"` key, and
`tsc --showConfig` does not emit defaults — but TypeScript 6.0.3 defaults it true (`--strict false` yields
157 errors; as-configured yields 0). Do not "enable strict" as a task. 150 FR-001 *declares* the inherited
default, which is a one-line change whose justification is the ruff-0.16 incident already written up in
`pyproject.toml`: a tool widening its own defaults overnight turned `main` red once already.

---

## Cross-arc follow-ups (SPEC-157, 158)

Two singles rather than an arc: they share no mechanism and neither depends on the other.

**SPEC-157 — serialize concurrent table refresh.** The one exposure SPEC-149 left open, and its
own entry says so: the Pipe starts executions `FIRE_AND_FORGET`, so `MessageGroupId` serializes
*delivery* per database and not *execution*. Two refreshes of one table can overlap and the second
to finish wins. **Severity is genuinely low and the spec says so** — both runs re-infer from the
same folder, so they usually compute the same definition and last-write-wins is a no-op. It only
bites when the files change between the two reads, and then it is **silent**: `diff-schema` reports
"unchanged" and nothing in `logs/` says a definition was overwritten.

Three things were settled against the API models before the design, not after. **`REQUEST_RESPONSE`
on the Pipe is impossible for a STANDARD state machine** — botocore's own `InvocationType`
documentation says so — which is what forces the "just make it synchronous" idea into an EXPRESS
conversion, itself rejected twice over (5-minute ceiling vs `inspect-source`; at-least-once
execution, which would *create* duplicate refreshes). **`UpdateTable.VersionId` is not a CAS** —
documented only as "the version ID at which to update the table contents", no precondition error.
And the table-builder execution role carries an explicit **`Deny` on `s3:DeleteObject`** for the
admin bucket, which SPEC-149 kept deliberately — so the lock is released by OVERWRITING under ETag
CAS, never by deleting, and "free" is a state of the object rather than its absence. A steal for a
lock left by a dead execution needs executions to be bounded, so the state machine gains a
`TimeoutSeconds` it does not have today; that is a prerequisite, not a tidy-up.

**SPEC-158 — shared-space suggestions from the local cache.** Small, and filed for a structural
reason rather than its size: it lifts `UsernameCombobox`'s data source to a prop, so the component
stops being the only shape of suggestion field the app can have. SPEC-147 had it call
`useUserDirectory` internally — the right reading with one source; a second source is the trigger
to revisit it.

**A shared-space DIRECTORY was considered and declined (user decision, 2026-08-05), and the reason
is worth keeping.** Sharing to a space does **not** require membership
(`test_recipient_space_membership_not_required`), so a full list would be strictly more useful than
"spaces you belong to" — and that is exactly what makes it a disclosure: it would publish every
space name in the organisation to every authenticated user, with no existing equivalent. A username
is already the S3 prefix, the principal tag, the Glue database name and a roster entry; a space name
is discoverable today only by colliding with it at create time, and space names are user-chosen and
often descriptive. So 158 suggests only what the user can already see, and any other space stays
typeable. **Do not add the directory "for symmetry with SPEC-146."**

## Table-share-at-scale arc (SPEC-160 → 161)

> **160 is COMPLETE (2026-08-10).** The mechanism changed and nothing user-visible did — the
> caps, conflict rules and notifications are exactly as they were, which was the arc's stated
> precondition for 161 moving the ceiling. What shipped:
> `docs/spec-delivery/SPEC-160-table-share-distributed-map-transfer.md`.
>
> **161 is COMPLETE (2026-08-10) and the ceiling has moved.** `SHARE_MAX_OBJECTS` **20,000**,
> `SHARE_MAX_TOTAL_BYTES` **1 TiB**, plus a new `SHARE_MAX_TRANSFER_ITEMS` (20,000) on
> `recipients × objects`. The cloned definition joined the object list behind a pointer, which
> is what let `SHARE_MAX_DEFINITION_BYTES` stop being a choice between the 256 KB payload and a
> 100-column commented table. The machine declares a top-level `TimeoutSeconds` of 10,800, so a
> run that can now last hours cannot last a year. **One live check is owed** — the script is in
> `docs/testing/e2e.md` §4.10 Table share. What shipped:
> `docs/spec-delivery/SPEC-161-table-share-caps-wide-definitions-long-runs.md`.

The arc exists because the table-share caps are not a policy — they are the shape of one Lambda.
`copy-objects` copies every object for a recipient inside a single 900-second invocation, and
`SHARE_MAX_OBJECTS = 1000` / `SHARE_MAX_TOTAL_BYTES = 20 GiB` were sized backwards from that
timeout (SPEC-090's delivery doc says so outright). A user with several hundred Parquet part files
over 20 GiB does not get a slow share; they get a refusal that reads like a product decision and
is really an implementation detail.

**160 changes the mechanism, 161 moves the ceiling.** Deliberately in that order: 160 must be
provably behaviour-neutral — same push, same conflict rules, same notifications, same caps — before
anything is allowed to get bigger, so a regression in the new engine cannot hide behind a new limit.

**S3 Batch Operations was the recorded escape hatch since SPEC-090, and 160 rejects it on
measurement of the API, not preference.** Its Copy operation cannot rewrite a key:
`TargetKeyPrefix` *prepends* to the full source key, so a job can only produce
`bob/…/alice/tables/sales/year=2024/part-0.parquet` — the source's own prefix echoed inside the
recipient's space, with the recipient table's `LOCATION` pointed at a path that names the sender's
directory layout. It also caps objects at 5 GB, where `tscommon.copy` already handles more via
`UploadPartCopy`, and one job writes to exactly one destination bucket. **Step Functions Distributed
Map** has none of those properties, reads the manifest the plane already writes to the admin bucket,
and runs the existing copy code unchanged.

The restructure that makes it work is worth stating, because the obvious version does not: the
Distributed Map is **top level**, over a flat `(recipient × object)` manifest — not nested inside
the recipient `Map`. That keeps every recipient's objects in one fan-out, sidesteps the nesting
question entirely, and costs one thing: per-recipient failure attribution stops being a property of
the Map item and becomes a verb that reads the `ResultWriter` export. `ToleratedFailurePercentage`
is therefore **100** — the Map Run must always finish so the collector can attribute — and child
executions are **STANDARD, not EXPRESS**, because a batch may hold a multi-GiB object whose
multipart copy would blow EXPRESS's 5-minute ceiling and whose at-least-once re-run would recopy
the batch.

The engine lands on **`cpcommon`**, not `tscommon`, and that is the arc's other reason to exist:
the send-files arc below is its second caller, and SPEC-156 already settled that `cpcommon` owns
the algorithm while a domain layer owns the wording.

## Feature-flags arc (SPEC-162 → 163)

Everything ships to everyone the moment it merges. The arc adds a git-controlled JSON document in
the user-space bucket (`_config/feature-flags.json`, beside `_directory/`), per environment,
naming the four primary features on or off — and then actually
hides a disabled one.

**The split is document-then-gate, and 162 ships something nothing reads.** That is intentional: the
publish pipeline, the IAM grant and the fallback semantics are all verifiable on their own, and a
flag set that resolves correctly is a precondition for gating rather than a part of it.

Two decisions carry the arc. **A flag is presentation, never authorization** — turning Query off
hides the tab and every entry point and revokes nothing; the IAM grants are untouched, and a test
forbids any service or `lib/` module importing the flags. This is the username directory's advisory
rule (SPEC-146) applied to a second document, for the same reason: the moment someone treats it as a
boundary, it becomes one, badly. And **an unreadable document falls back to compiled-in defaults
(everything on)**, accepting openly that during an outage a deliberate "off" does not take effect —
the alternative, failing closed, strips the app to Files for everyone on one S3 blip.

**163's hard part is not the tab, it is the cross-feature entry points.** "Create table from this
folder" lives in the file browser but is a Query feature; "Share table" lives in the Query rail but
targets Shared Workspaces. Gating component-by-component is exactly how the fourth one ships
unhidden — the failure mode `reviewer-contract.md` records from `log-forge`'s SPEC-033. So the surfaces live in
a **registry** with a test that walks it in both states, plus a guard-the-guard that fails if the
registry ever goes trivial (SPEC-153's discipline).

**The document was first specced into the admin bucket and moved (2026-08-10, before build).** That
would have given the portal role its first-ever grant on a bucket admin-only since SPEC-032 — and,
more to the point, the grant would not have worked: the admin bucket carries an explicit "never read
by the browser" comment in place of a CORS config, and its host is absent from the enforcing CSP
`connect-src`. Two infra gates, on the exact surface SPEC-140 records breaking sign-in for a day,
bought nothing that `_config/` beside `_directory/` does not already have. The lesson generalises:
**for a browser-read advisory document, the bucket that already serves one is the cheap answer** —
and because this feature fails *silently* to its all-on defaults, a blocked read would have looked
exactly like a healthy environment.

## Send-files arc (SPEC-164 → 165 → 166 → 167)

A user can move a file anywhere inside a space they can reach, and can share a whole *table* with
anyone — but cannot hand a colleague a file. The browser has no permission to write into another
user's prefix, which is the isolation model working exactly as designed, so "send these files to
Bob" needs a privileged path for the same reason table share did.

**It gets its own control plane rather than a mode on table share's.** The two share an algorithm
(`cpcommon.transfer`, from SPEC-160) and nothing else: different request contract, different
authorization question, different failure vocabulary. Folding them together would put one queue and
one DLQ under two unrelated user features, and a malformed send would dead-letter someone's table
share.

The arc is the table-share arc's shape, one spec per reviewable unit: **164** the plane, the contract
and validate-authorize; **165** source resolution and the copy plan; **166** the conflict guard, the
Distributed-Map transfer and the terminals; **167** the UI and the notifications.

Three decisions are settled up front. **The destination is an inbox namespaced by sender** —
`{target}/shared_files/{sender}/{item}` — mirroring `shared_tables/{table}/`, so two senders never
collide and provenance is visible in the file browser without a metadata lookup. **A send is a push
and never an overwrite**: no consent step (table share's recorded precedent), and a non-empty
destination is a per-recipient `conflict` that names the colliding item. And **the recipient field
is the field we already built** — SPEC-147's combobox with SPEC-158's prop-supplied source,
usernames from the directory and spaces from the user's own connections cache, which is precisely
why 158's prop lift was worth doing before a second consumer existed.

The containment check in 164 deserves its own line, because it is the one place a path bug becomes a
cross-tenant read: an item's key is validated against a **trailing-slash-normalised** source root, so
`alice2/` never passes as inside `alice/`, and 165 re-checks every key that comes back from
`ListObjectsV2` rather than trusting the request-time check.

## Archival arc (SPEC-168 → 169 → 170 → 171 → 172)

> **SPEC-169 shipped (2026-08-12), so the commit gate below is now a state rather than a plan:**
> `collect-transfer-results` returns one boolean and `CommitOrRollback` branches on it, with the
> deletion reachable from exactly one arm (asserted by walking the ASL graph) and the rollback
> deleting by LISTING the archive prefix — which also catches objects a batch copied before it
> died and never reported. Details: `docs/spec-delivery/SPEC-169-*.md`.

Data a user has finished with still costs S3 Standard rates and still fills the file browser. There
is no way to put something away. The arc adds a fifth bucket, a fifth control plane, and two
operations: **archive** a file or a folder into Glacier and delete the original, and **restore** it
back by pasting the id from the receipt the archive left behind.

**The storage class is the whole design.** `GLACIER` (Flexible Retrieval) is not readable, and a
`CopyObject` whose source is in `GLACIER` fails `InvalidObjectState` — so restore is not a copy, it
is `RestoreObject` plus a 3–5 hour wait plus a copy, and the plane grows a `Wait`/poll loop no other
plane in this repo has. `GLACIER_IR` was rejected (readable in real time, which would delete the
whole restore path but makes "archive" mean "moved to a cheaper bucket") and `DEEP_ARCHIVE` too
(12–48 hours, 180-day minimum). The 90-day minimum duration is accepted and surfaced in the confirm
dialog: archive-then-restore-next-week still bills 90 days.

**Retention is a ceiling, not a floor.** A 7-year lifecycle expiry, not Object Lock. Object Lock
needs versioning — deferred by decision — and in compliance mode nothing can delete the object, not
even root, which would make the restore's archive cleanup impossible. The rule is deliberately
bucket-wide with no prefix filter, the inverse of the admin bucket's prefix-scoped `check`, because
this bucket holds exactly one class of object and a filter would be a silent way to leave some data
unexpired.

**The archive bucket is the first bucket the browser has no relationship with at all** — no CORS,
absent from the CSP `connect-src`, and the portal role holds zero statements naming it. The only
route to archived bytes is a restore request. What the browser *does* get is a **Deny**: `PutObject`
and `DeleteObject` under `archive/` in both space buckets, so the receipt cannot be forged or
deleted by the user it describes.

Two decisions carry the correctness of the thing. **The source is deleted only when every object is
confirmed copied** — archiving is the only operation here that deletes data as a side effect of a
copy, and "copied 900 of 1000, deleted 1000" is the failure it must never have; the commit gate is
explicit and a partial transfer rolls the archive copy back instead. And **the receipt is a report,
not a record**: an archived key carries its own origin, so restore reconstructs every destination
from a `ListObjectsV2` over the archive prefix, exactly as SPEC-143 judges a table by shape rather
than by the marker it also writes. The manifest exists only as a cross-check that can fire when
something is already wrong.

**The key layout is partitioned by space kind, and that is not cosmetic.** Receipts sit at
`{username}/archive/{uuid}/` and `{space}/archive/{uuid}/` in their own space's bucket, where they
cannot collide. The archive bucket is the first place both namespaces meet — and shared-space names
are made unique against the *shared-space registry* only; **nothing checks a proposed space name
against the User Pool**, so a user `alice` and a space `alice` can both exist today. Flat, they would
share one archive prefix, and since restore authorizes by space and then reads whatever sits there, a
member of space `alice` could restore user `alice`'s files into the shared space. The leading
`personal/` / `shared/` segment is the entire fix.

**The restore guard is absolute.** Any occupied destination key refuses the whole restore and names a
bounded sample of the collisions — no skip, no overwrite, no partial restore around an obstacle. It
runs before `RestoreObject` because retrieval is billed and cannot be cancelled. Its asymmetry with
archiving's rollback is deliberate and recorded: a partial *archive* rolls back, a partial *restore*
does not, because deleting restored data to make the operation atomic would destroy the thing the
restore was for.

**Shipped in 170, with three things the narrative above did not anticipate.** A **403 counts as
occupied** — a key the role cannot head is one it must not overwrite, and on these buckets that is
live rather than hypothetical. The guard's pool is bounded by **botocore's default
`max_pool_connections` (10)** and not by the obvious "workers x timeout / latency", so the verb buys
**time** (600 s) rather than threads. And the restore validator turned out to be a **branch of the
existing front door** rather than its own verb: `ChooseMode` sits downstream of validate-authorize
and the raw Pipe record buries `mode` in an escaped JSON string, so both modes return the same five
keys through one `Validated` Pass. Full reasoning: `decisions/` → *The restore guard*.

The arc is the table-share shape, one spec per reviewable unit: **168** the bucket, the plane and
validate-authorize; **169** expansion, the Glacier transfer, the commit gate and the receipt;
**170** the restore contract, the archive lookup and the destination guard — everything verifiable in
seconds; **171** retrieval, the wait loop and the copy-back — everything that takes hours; **172**
the UI, the read-only `archive/` mirror and the notifications.

One structural note for 172: **there is no context menu in the file browser.** Rows carry an
always-visible *Details* button and nothing else, so a per-item action has exactly two homes — the
details panels and the selection toolbar — and Archive takes both. 172 also builds the app's **first
prefix-based write gate**: nothing today gates Upload or *New folder* on the current prefix, so
without it a user who walks into `archive/` and uploads gets a bare `AccessDenied` for a rule this
application wrote.

### Build order across the four 2026-08-10 arcs

They are not independent, and two of the edges are easy to miss:

- **160 before 164→167 — SATISFIED; `cpcommon.transfer` exists.** The send-files plane consumes it — the manifest writer,
  the batch copier and the result reader — which 160 creates. Building the send arc first would
  fork the engine, which is the outcome SPEC-156 exists to prevent.
- **163 before 167.** SPEC-167's *Send to…* control is a gated surface: it declares
  `Depends On: SPEC-163` and two of its acceptance criteria (FR-001 AC4, FR-006 AC3) require the
  registry to exist. Shipping 167 first leaves the entry point outside the registry, which is
  precisely the miss the registry was built to prevent.
- 161 after 160, and 165→166→167 in order, are internal to their arcs.

- **160 before 168→172 as well — also satisfied.** The archive plane is `cpcommon.transfer`'s **third** caller, and
  SPEC-169 extends the engine with a per-item storage class. Building the archival arc first would
  fork the copier a second time.
- **168 → 169 → 170 → 171 → 172 in order**, and the ordering inside it is load-bearing in one place:
  170 must land before 171, because 170's destination guard is what makes 171's billed, uncancellable
  Glacier retrieval safe to initiate.

162 → 163 has no dependency on the other three arcs and can run in parallel with them. The archival
arc has no dependency on 162→163 or 164→167 beyond the shared `cpcommon.transfer` edge; if 163 has
landed by the time 172 is built, the archive entry points register in its surface registry (they
inherit the Files flag rather than gaining one of their own).

## Saved-queries-in-spaces arc (SPEC-173 → 174 → 175)

**A saved query is a file, and SPEC-043 made it a row in a private document.** Today every saved
query lives in `{username}/user_settings/saved-queries.json` — a JSON store only the query editor
can read, only its author can reach, and which no amount of sharing can ever open to a colleague.
That shape was right when the workspace had one user and one database. It is wrong now: a saved
query is SQL with a name, the person who wrote it usually wants it beside the data it queries, and
a shared space exists precisely so that the people in it can hand each other work. This arc turns
saved queries into `.sql` objects in a `saved_queries/` folder at a space root — the user's own
space, or any shared space they are an active member of.

**It is an ordinary folder with exactly one protection, and the narrowness is the design.** Its
contents are ordinary: visible in the file browser, downloadable, uploadable into, a valid move/copy
destination, subfolders allowed, individual files deletable by anyone with access to the space —
because a saved query nobody can throw away is a saved query that accumulates forever, and a folder
the user cannot treat as a folder is a folder they will fight. The only thing protected is the
*folder itself*: it cannot be deleted, and it cannot be renamed — one entry, in
`UNDELETABLE_ROOT_FOLDERS` alone, since S3 has no rename and `moveFolder`'s existing
`isUndeletableRootFolder` refusal therefore covers both. It is kept alive by the same hidden
`DO_NOT_DELETE.txt` every space root already uses. `protectedFolders.ts`'s three lists stay three
lists (visible / pasteable / destroyable) and this folder answers **yes / yes / no** — the note at
the top of that file already argues against unioning them, and this is the second case that proves
it.

**What keeps the load list coherent is a filter, not a write lock.** Because anyone may drop a CSV
or a subfolder into `saved_queries/`, the store offers *top-level `.sql` files and nothing else* —
that filter is a requirement with tests, not a precaution, and the `Delimiter: '/'` is load-bearing
beside it (`saved_queries/archive/old.sql` is a file in a folder, not a saved query). It has one
non-obvious consequence the specs pin: **an S3 page and a display page are different things**, so a
listing page of 25 keys can yield zero rows while more pages remain, and a folder holding two
hundred CSVs and one saved query must not render as empty. The hook keeps fetching until it has a
display page or the listing is exhausted — **that is 174's work, not 173's**: 173 ships one listing
page plus a Load more control, so a page of 25 CSVs renders a drawer with nothing in it but that
button.

**The marker protection is free, and that is a claim about ARN wildcards worth checking.** Both
bucket policies already deny `s3:DeleteObject` on `*/DO_NOT_DELETE.txt`, and `*` in an S3 resource
ARN matches `/` — so a marker at `{root}saved_queries/DO_NOT_DELETE.txt` is covered at that depth
and any other, in both buckets, with **no IaC change in the whole arc**. The same reading says
something broader: *any* object named `DO_NOT_DELETE.txt`, anywhere, is already undeletable, so
showing one in the listing offers an action this application's own IAM refuses — the SPEC-150 FR-007
mistake. 173 therefore hides the marker by **basename** rather than by the one exact key
`useFileBrowser` hides today. The wildcard reading is the load-bearing premise of all of it, so it
is pinned by a test over the two `.tftpl` files and owes one live confirmation: a real delete of a
real marker, refused.

**Two deliberate losses, both recorded rather than discovered later.** The queries in the existing
JSON store are **abandoned, not migrated** — the portal is pre-production with no real users, and a
migration is code with one execution and no way to test its second run; the document is left in
place (`user_settings/` denies delete) and the store's code is deleted so there is one saved-queries
system in the tree. And the drawer **loses its SQL preview line**: a `.sql` file carries no metadata,
so a preview means a `GetObject` per row — twenty-five round trips to show twenty-five one-line
snippets. The body is fetched only when a query is opened.

**The order is S3's own, and that is not laziness.** The list pages lexicographically because that
is how S3 pages. Sorting by last-modified across a paginated listing is the lie SPEC-123 records
about the data-quality runs index: the newest query may sit on page nine, and a client-side re-sort
of the loaded pages makes rows the user has already seen jump between pages as later pages arrive.
For the same honesty the range label reads `X–Y of Z+` while pages remain — S3 reports no total, and
`24` and `at least 24` are different facts.

**The file changes when the user saves it, and Save always asks.** Editing a tab edits a buffer:
nothing writes on keystroke, blur, tab switch, run, close or unload, and the rule is a **tripwire
test with a zero-`PutObject` count** rather than a description of today's behaviour, because the
failure it guards is silent and lands in someone else's shared space. The other half is that
**every** Save prompts for a file name — a linked tab's included, pre-filled and selected rather
than skipped, which is a change from SPEC-043's silent write-back. A user about to overwrite a file
should be told which file, in which space, before it happens. The tab's label is the file's name
with the extension removed, from `savedQueryName(key)` — the store's own function, so a tab and a
list row can never disagree about what a file is called.

**Collisions move from a list scan to a key.** SPEC-043's dialog detected a name clash by scanning
the in-memory array, case-insensitively. That stops being sound the moment the list is paginated and
the target space may not be the one on screen, so the check becomes a HEAD on the exact key inside
`writeSavedQuery`. One visible consequence is accepted deliberately: S3 keys are case-sensitive, so
`Report` and `report` are now two saved queries where they used to be one.

The arc is three specs: **173** the folder, its protections and the space-scoped store, cutting the
existing surfaces over for the user's own space; **174** the space selector and the paginated load
list; **175** the destination picker on save.

**174 before 175, and the ordering is load-bearing.** Either order leaves a gap for one merge — the
question is which gap. Loading first means a shared space is offered and is empty until 175 lands,
which is harmless and self-explanatory. Saving first means a user can put a query into a shared
space and then have no way to open it, which is a hole with their work in it. Nothing else in the
arc reorders: 173 must precede both, since it is the store.

One structural note for 173: `saved_queries/` is a **Query** feature wearing a **file-browser** row,
so it is gated on the `query` flag from `GATED_SURFACES`, not on `files` — the same shape as
"Create table", the row SPEC-163 calls the one everyone forgets. With the flag off it leaves the
listing and the destination picker together (a destination you cannot see is not a destination),
and that is the only place the gate touches an ordinary folder operation. The delete/rename refusal
is **not** part of the gate and is asserted with the flag off: "you cannot see it" and "you cannot
destroy it" are different guarantees, and only one of them survives a stale cached flag document.

> **174 landed 2026-08-11**, and it took the gating note one step further than the paragraph above
> anticipated. The **space selector** is itself a shared-workspace surface: with `sharedWorkspaces`
> off it offers *My files* alone, filtered at the view exactly as SPEC-163 filters the connections
> list and the schema rail, under a registry row of its own. That is a deliberate deviation from
> 174's FR-001 ("exactly the spaces `useQuerySpaces()` returns") and is recorded in its delivery
> doc. The keep-fetching rule this arc predicted for 174 shipped with a bound the arc did not name:
> **an error stops the fill**, because a failed page leaves `hasNextPage` true — the fill's own
> trigger — and would otherwise spin.

> **175 landed 2026-08-12 and the arc is COMPLETE.** Saving asks *which space* too, so a shared
> space's `saved_queries/` folder can hold something at last — which is the thing the arc existed
> for, and until now no code path could produce. Two notes the paragraphs above did not anticipate.
> The selector's gating went the same way a second time and needed a **second registry row**: the
> 174 row renders the drawer, so the save dialog's destination control would have gone ungated
> unnoticed, and *that* one offers a colleague's space as a **write** target. And the choice made
> "which file does this replace?" a real question, answered in exactly one place —
> `isLinkedSavedQuery` judges the **key**, so the dialog's promise and the host's `overwrite` cannot
> drift apart. Choosing a different space **copies**; nothing in this arc ever moves or deletes a
> colleague's file.

## Data Explorer arc (SPEC-176 → 185)

The portal can already run SQL. What it cannot do is let someone **look at a table** without writing
any — pick a database and a table, see its rows, page through them. That is the Data Explorer, and
everything it needs to do it already exists inside `features/query/`: the Glue reader, the Athena
start/poll/results/cancel layer, the space list, the results pager, the row-count walk and the
column-width store.

**The arc opens with the refactor, and that ordering is the whole point.** A `features/data-explorer/`
built first would import those from `features/query/` because that is where they are — recreating
the undeclared shared layer SPEC-155 spent a whole spec dismantling, one directory over, and the
ESLint rule that now guards `components/`, `lib/` and `hooks/` does not reach feature-to-feature
imports. **176** moves the shared ground into `features/catalog/` while nothing is riding on it,
ships no user-visible change at all, and extends the layering rule to name
`features/data-explorer/` **before it exists** — so the first file created there lands under a guard
that is already working rather than one added afterwards. A spec that ships nothing visible is a
fine way to open an arc when it is the change most likely to go wrong.

**177** takes the saved-query store out too, deliberately separated from 176 so a harder move cannot
block the one everything else is built on. It landed the same way — nothing user-visible, nothing
live owed — and its one deliberate change is the point of the whole extraction: `useSaveQuery` now
takes **`{sql, link}`** rather than a `QueryTab`, a shape the Data Explorer has no way to produce, so
SPEC-183 reuses SPEC-175's collision-and-confirm path instead of reimplementing it. Only
`SavedQueriesPanel` stayed behind, because it is a workspace rail surface rather than part of the
store. **179 onward** build the surface itself — the picker and the grid — as their own components
rather than by widening the Query workspace's.

> **179 landed 2026-08-13, and it is the arc's first visible surface.** Two corrections worth
> carrying. FR-005's *space → database → table* picker has **no database step**: a space maps to
> exactly one Glue database here, so the control would have had one option — the picker shows the
> database and `?db=` became a cross-check. And the fifth flag key's "five places" are not the ones
> the spec listed: the publish workflow's matrix is per *environment* and needed no edit, while
> `scripts/validate_feature_flags.py` refuses an unknown key and would have failed the publish.
> Its results table was a **placeholder SPEC-180 has now replaced wholesale**.

> **180 landed 2026-08-13, and three of its decisions reach outside the feature.** Column geometry is
> keyed by column **name**, not position — which is why it reuses the catalog's sizing constants and
> `ColumnResizeHandle` (moved into `features/catalog/`, generic over its key) rather than
> `useColumnWidths`. `getQueryResults` stopped collapsing SQL NULL to `''`: FR-003's "an empty string
> and a NULL are visibly different" was unbuildable at the layer asked to satisfy it, and SPEC-181's
> `isNull` and SPEC-185's copy need the distinction too. And a bug the grid inherited rather than
> introduced — a remembered page index outliving its cached pages — was drawing "No rows returned"
> over a result that has rows. The column header **menu** is still SPEC-181's; 180 ships headers that
> resize, drag and pin, with hide/pin/reorder in their own panel.

> **181 landed 2026-08-13, and it is the spec the feature exists for.** Its two hardest problems
> were not the ones the spec anticipated. **Athena's own refusal is not an error anywhere in the
> plumbing** — `getQueryStatus` resolves and the reason arrives as `stateChangeReason` on a
> successful poll — so FR-003's "render the syntax error through `toUserMessage`" first required
> `useExploration` to MAKE an error out of a successful poll; and FR-006's "history never re-runs a
> query that failed" cannot come from the cache, because SPEC-178 deliberately evicts a failed
> execution, so a history step onto a known-failed statement now **suspends** with *Run it anyway*
> as the retry. Three smaller corrections: `useExplorationQuery` takes the tabs result rather than a
> tab id alone (the history lives in the tab's `sessionStorage` document, and a second instance of
> that hook is a second writer); the spec's `stage` is gone, because staging the query in the hook
> and the presentation in the dialog would let half a draft survive a Cancel; and no field in the
> settings dialog submits on Enter, since every field in it is a criteria row — which is what
> SPEC-155's suppression exists for. FR-008 also settled a question the arc kept asking: **a
> pre-flight "this looks expensive" confirm is not buildable**, because Athena will not report what
> a query will scan until it has run it.
>
> **SUPERSEDED in part by 182:** `clearAll` no longer preserves the grouping — it clears that too,
> and the control's label changes to *Remove all filters and grouping* while one is in force. The
> concern was never the clearing but the silence.

> **182 landed 2026-08-13, and its two panels are the arc's clearest statement of its own premise.**
> Calc and Grouping look like siblings and are opposites: a **selection** exists only in the browser,
> so aggregating it server-side would be a billed execution per selection change — Calc therefore
> issues **zero**, and says "N selected cells **on this page**" every time it says anything. Grouping
> is the mirror: aggregating in the browser would aggregate whichever rows happened to be fetched,
> which is the scale lie this feature was designed around, so it renders a real `GROUP BY` and mints
> an execution like any other change. The percentage column inherits both halves of that argument —
> computed client-side from rows already fetched (a windowed total would re-scan for a column asked
> for by eye) and headed **`% of count_all (this page)`**, because only one page is ever in memory.
> Two things the spec did not name turned out to be load-bearing: **leaving grouping mode has to drop
> sorts on aggregate aliases** (`count_all` exists only while the grouping does, so FR-003 AC6's
> "returns to the ungrouped execution, from cache" is otherwise a query Athena rejects), and the
> ordering refusal belongs on the **Grouping panel's Apply** rather than on a sort control — while a
> grouping is in force every column a user can see is orderable, so the only reachable way to build
> the conflict is to sort a column and then group it away.

> **184 landed 2026-08-14, and its two hard problems were both about measurement.** The spec's
> `foreground?: string` became a five-token union, because "every colour pairing meets contrast
> requirements" is not a claim anyone can make about a colour picker — and the narrowing turned the
> criterion into an arithmetic one, computed over the cross product, the sampled gradient and the
> selection's own fill rather than judged. **`warning` was measured out of the palette**: 5.02:1 on
> white and 4.49 on `accent-soft`, so a colour that is legible only sometimes was dropped in favour
> of one fewer. Axe carries the other half of that criterion and cannot carry this one — jsdom has
> no layout engine, so `color-contrast` is off — which is worth remembering the next time an axe
> pass is offered as evidence about colour. The second problem was the URL transformer, where both
> simple encoding rules are wrong: unconditional encoding makes `${value}` over a column of links
> produce `https%3A%2F%2F…` and never link at all, while no encoding lets a value climb out of its
> path segment. The leading position substitutes raw and the `https:` allowlist guards it; every
> later position is encoded. Two smaller notes: `ColourRule` needed a `scope` the spec's model did
> not have, because one field cannot carry both what a rule tests and what it paints; and the Text
> view deliberately stays raw, since it is the copy surface SPEC-185 is about to build on.

**The arc is ordered by risk, descending, and its first three specs ship nothing a user can see.**
That is the rule the whole decomposition follows: layer extractions, shared-model design and the
injection surface go at the front; polish, formatting and help go at the back. The alternative
ordering — shell first, so there is something to look at — buys a demo and pays for it by
discovering structural problems after several specs have built on them.

> **178 landed 2026-08-13.** Two things the spec did not anticipate. Its filter model — every
> value through `sqlLiteral` — **would not have worked**: Trino does not coerce, so
> `WHERE "qty" > '5'` against a bigint is a query-time error, invisible on the Table Builder's
> all-string CSV tables and surfacing on the first Parquet one, after 180→182 had built on the
> model. `ColumnFilter` gained a `valueKind`, and a `'number'` renders bare behind a charset gate
> that is load-bearing rather than a fast path (`Number` alone accepts `0x1f`, `0b11` and
> `Infinity`). And the **repo-wide** one-builder sweep FR-002 asked for is not achievable —
> `useTableActions`, `useRunDdl` and `CreateViewDialog` build real DDL and `DEFAULT_SQL` is
> `SELECT 1;` — so it is scoped to the feature, on SPEC-165's actual precedent.

**178 is the engine, and it is where the arc's two hardest decisions live.** The first is that
**filter, order and grouping render SQL, and everything else is presentation** — column visibility,
order, pinning, width, colour and transformers must never change the rendered SQL, so they cost
nothing and apply instantly. That means `SELECT *` always: narrowing the projection to the visible
columns would cut bytes scanned on Parquet, and would also turn un-hiding a column into a billed
several-second re-run, making cost depend on a gesture users read as cosmetic. The rule is enforced
by `renderExplorationSql`'s **signature** — it takes the source and the query description and
nothing else, so a function that cannot reach presentation cannot be made to depend on it by a
later edit.

The second is that this is **the first place in the repo where the browser interpolates
user-supplied values into SQL**. Everything the portal builds today is either typed into Monaco or
assembled from identifiers already validated against `CATALOG_IDENTIFIER_RE`; a filter value is
neither, and there was no TypeScript literal escaper. 178 adds one, and it is the **Trino/DML** rule
(double the single quote), not the Hive/DDL backslash rule the Python side carries for a different
dialect — the repo's "two escapers, never confused" note gains its TypeScript half here. The raw
expression bar does not relax this: the bar is the *user's own SQL* and passes through verbatim, as
Monaco's does, while the **per-column menus and filter-by-cell-value** are the app composing SQL
around a value the user never wrote as SQL. A cell containing `O'Brien` filtered by `=` is the whole
hazard in one click, and it arrives from real data long before anyone thinks to type it.

**Everything is server-side, and the forward-only cursor stops mattering because of it.** Athena's
`GetQueryResults` gives a `NextToken` with no random access and no re-sort of a finished result,
which reads like a blocker for an Excel-like grid. It is not, once the engine is one **execution per
distinct rendered SQL**: paging *within* an execution is free — those calls scan no extra bytes, a
property `useResultRowCount` already relies on — so Prev/Next never bills and only filter, order and
grouping do. Toggling a sort back is a cache hit rather than a second charge. There is deliberately
**no client-side toggle**: DBeaver offers one, and here the client half cannot be made honest, since
sorting whichever rows happened to be fetched is a lie a grid this Excel-like would tell
convincingly.

**Cost is the through-line, and it can only ever be reported, never predicted.** Athena will not say
what a query will scan before running it, so a "this looks expensive, continue?" confirm is not
buildable; the guards are the workgroup's per-query bytes cutoff and honest after-the-fact
reporting. Which is why filters apply on an **explicit gesture, never per keystroke** — a keystroke
would be a query.

**180 → 182 build the surface, and the two analysis panels land on opposite sides of the
client/server line** — not as a compromise, but because of what each one is. **Calc** aggregates the
current cell *selection*, which exists only in the browser, so it computes client-side and says so;
a query per selection change would be absurd for a gesture as cheap as dragging across ten cells.
**Grouping** *is* a `GROUP BY`, so it renders SQL and mints an execution like any other query
change. Because grouping generates SQL the user did not write, and that SQL is an invoice, the panel
**discloses it** — DBeaver's Query button is a nicety there and the difference between understanding
a charge and not, here.

**183 is where the arc's model earns its shape.** A saved `.sql` file cannot be reverse-engineered
into a table plus filters without a SQL parser, so a loaded file is a **source**, not a view state —
which makes `ExplorationSource` a union: `table` renders `FROM "db"."table"`, `sql` renders
`FROM (<body>) AS t`, and filters, ordering and grouping compose over either arm without knowing
which. The union therefore lives in **178**, with only the `table` arm reachable for five specs;
retrofitting it at 183 would have touched every spec in between. The arc's most user-visible loss is
here and is accepted rather than hidden: **a saved exploration reloads as a query, not as an
exploration**, its filters baked into the SQL rather than returning as editable chips. The
alternative is a sidecar JSON carrying the view state, rejected because SPEC-173 settled that a
saved query is a `.sql` **file** in an ordinary folder — a sidecar reintroduces exactly the JSON
store that spec deleted, plus a second artifact to keep in sync with a file users can freely rename,
edit or delete from the file browser.

> **183 landed 2026-08-13, and it shipped HALF of the above.** The loading half was descoped during
> build at the user's direction and deferred to a later spec, so the paragraph above now describes
> that spec rather than this one — the `sql` arm of `ExplorationSource` stays exactly as 178 left
> it, unreachable, and nothing was half-built for it. What shipped is the save: an exploration's
> **rendered** SQL written as a `.sql` file through SPEC-177's flow, with the collision-and-confirm
> path, the destination selector and the in-place re-save all SPEC-175's. The sidecar stays
> rejected, and the guard is a count — one `PutObject` per save.
>
> Its one decision that reaches outside the feature is a **flag** one, and the registry found it
> rather than review. Registering *Save as query* under `dataExplorer` reads naturally and asserts
> nothing: `/explore` already hides the whole workspace, so there is no gate for the walking test to
> remove. It belongs to **`query`** — the exact mirror of *Explore data* on the Query rail — because
> with the SQL workspace hidden there is no editor to open the file in and `saved_queries` has
> already left the file browser, so the file would land somewhere its author cannot see. The
> question a registry row answers is which FEATURE a control belongs to, not which screen it is on.
>
> One thing the deferred load spec has to face first: `splitSqlStatements` lives in
> `features/query/`, which this feature may not import, and the wrapped-subquery refusals are built
> on it. It moves down to `lib/sql.ts` — the same move 176 and 177 made, one layer lower.

**The flag is independent, and the expression bar is not gated on `query`.** `dataExplorer` stands
alone, so an environment can ship the grid while keeping the SQL editor hidden — arguably the main
reason to want the feature. The tempting corollary is that the free-text `WHERE` box should then
follow the `query` flag, and that is a category error against a rule the project already settled: a
feature flag is **presentation, never authorization** (SPEC-162). It revokes no grant, the IAM
boundary is identical either way, and gating the bar would buy no security while leaving the feature
unable to express what analysts actually filter on. The accepted cost is stated plainly — an
environment that turns `query` off to *tidy SQL away* will still be offering a SQL input on this
page.

**Four of DBeaver's surfaces are excluded by nature rather than by scope.** Chart, Spatial/GIS and
the JSON/XML presentations have no column types here to render, and the **References panel is
impossible**: Glue has no foreign keys, so "related rows via FK" has nothing to read. The whole
write half of DBeaver's Data Editor — inline edit, row add/duplicate/delete, save, generated DML,
virtual keys — is out for the same kind of reason: an Athena result is not an editable table.

> **185 landed 2026-08-14 and closed the arc.** Its two ways out of the feature divide on the same
> line the whole arc does: **copy** takes the cell selection, which exists only in the browser, and
> **export** copies the execution's own results object, which is the only thing that holds every row.
> Neither issues a query — export's server-side `CopyObject` is what makes "the whole result, no
> second bill" true, and it is also why exporting a *selection* is out of scope: a partial export
> would need either a second query or a re-serialization of rows that are not all loaded.
>
> **Reusing `useSaveResults` turned out to require moving it**, which the spec had listed as out of
> scope on a reading of "change" that a relocation does not meet. It sat in `features/query/`, which
> this feature may not import — the same wall SPEC-176 and SPEC-177 were built to take modules
> through, so it went down to `features/catalog/` with its body untouched, and `normalizeCsvName`
> with it. **One thing about it did change, and it closed a live defect:** the hook built its own
> destination list from an unfiltered `useQuerySpaces()`, so the Query workspace's Save-results
> dialog had been offering a colleague's space as a **write target** with `sharedWorkspaces` off,
> unregistered and unnoticed since SPEC-055. The destinations are now a parameter — SPEC-174's shape,
> and SPEC-177's — both views gate them, and both have a registry row.
>
> **The Help guides are the arc's last piece and the registry found a hole in the test that walks
> them.** Every guide row before this spec happened to live in the `files` section, which is the one
> the Help page opens on — so the recipe queried a card without selecting its section, and a row for
> a guide anywhere else would have come back absent in **both** flag states and read as correctly
> hidden. The recipe now selects the owning section first. The guides themselves say the one thing a
> user cannot infer from the UI: every filter and sort is a real query against Athena that scans
> data, and the figures at the bottom of the screen are the cost signal.

**The arc needs no IaC and no IAM.** The Athena and Glue grants exist, results land in the
already-granted `{username}/athenaresults/` prefix, and the only non-app change in ten specs is
`config/feature-flags.json` plus the `deploy-config.yml` matrix that SPEC-162's validator reads.

> **176 landed 2026-08-13.** Two things the spec did not anticipate, both worth carrying. Its scope
> claim that only one file outside `features/query/` was affected was **wrong — six were**, and the
> discovery strengthened the premise rather than widening the work: `features/table-builder/` had
> been reaching into a leaf feature for the Glue reader and the schema key for two arcs. And the new
> ESLint clause, written in the same shape as the rule it extends, **resolved onto the right files
> and caught nothing** — `no-restricted-imports` matches the literal import source, and one sibling
> feature reaches another as `'../query/…'`, which contains no `features/` segment. FR-006's demand
> that it be verified by violating it in both directions is the only reason it shipped working.

## File-operations control-plane arc (SPEC-187 → 191)

> **187, 188, 189 and 191 are COMPLETE.** The plane copies, moves, deletes and **notifies** end to
> end; the browser's enqueue service is still called by nothing. Remaining: **190** alone — the
> browser's async model, which now also carries **191's FR-005 (Help & guides)**.

Recursive folder copy, move and delete are the last bulk data operations this product performs in
the **browser**. `copyFolder` issues one `CopyObject` per object in a strictly sequential loop,
`moveFolder` does that and then deletes, and `deleteFolder` lists the whole subtree before batching
its deletes. A user renaming a large folder holds a tab open while thousands of round trips run one
at a time from their laptop; closing it leaves the operation half-done with no record it ever
started. Six planes already exist for exactly this shape of work. This arc builds the **seventh**,
and it is the plane whose absence is felt every day rather than one enabling a new feature.

**The arc has a second motive, and it is the reason it comes first.** The next arc moves every AWS
SDK call out of the browser and behind an API. That API must be *thin* — tokens and service calls,
no data operations inside it — or the one operation whose cost grows with object count lands in a
request handler and sets the API's whole shape. Building this plane first means the API arc inherits
a browser that already enqueues, and the front-door choice (ALB, API Gateway) stops being
constrained by a 29-second ceiling. It is also independently verifiable **where it stands today**:
the browser already enqueues to SQS directly, so the whole plane can be proved before anything about
hosting changes.

**Be precise about that thinness claim, because it is only half true.** What moves is the operations
whose cost grows with the number of objects *in a folder*. What stays in the browser still includes
work that grows with object count: the SPEC-020 upload queue (N objects, arbitrary bytes, straight to
S3), and `firstFreeName`'s **up to 999 sequential `HeadObject` probes** to name a same-folder copy —
which FR-002 keeps synchronous because it operates on a single file. The API arc should inherit those
knowingly rather than discover them.

> **Superseded 2026-08-29 by SPEC-198 FR-004, for the probe only.** It left the browser for the
> **API**, not for the plane: behind the API each probe would have been a browser → API → S3 round
> trip, which is strictly worse than the loop it replaced, so it is one route. A same-folder copy
> stays synchronous. The upload queue's residual stands — the bytes still go straight to S3, now
> under a presigned URL. Full entry: `decisions/storage.md` → *The free-name probe moved to the API*.

**And the lock protects less than its name suggests.** SPEC-187's per-space lock serialises *this
plane's* executions. It does not cover the single-file operations FR-002 deliberately leaves in the
browser, nor upload, nor create-folder, nor `useSaveResults`, nor `savedQueries.service`, nor the
other six control planes — all of which write the same prefixes. That is why SPEC-189's source
deletion must remove **only the keys its plan copied** and never a prefix listing, diverging from
SPEC-169's rollback on purpose: an object written into a folder between expansion and commit was
never copied, and a prefix-listing delete would remove it silently, unrecoverably, with versioning
off. The accepted cost is an orphan, which is visible and recoverable where the alternative is
neither.

**SPEC-187 IS COMPLETE AND DEPLOYED, and four things it found are worth carrying forward.**

1. **The lock protocol moved to `cpcommon`** rather than being copied — this plane was its second
   consumer, and two full compare-and-set implementations is the twin SPEC-156 spent a spec
   removing. That was escalated rather than decided, because the extraction meant editing a shipped
   plane.
2. **This machine has no `Validated` Pass**, unlike every neighbour. Three of the contract's fields
   are absent for a `delete`, and a `Pass` reading an absent path raises an uncatchable
   `States.Runtime` — the very first delete would have died before the notifier. 188 and 189 add
   states to this machine: read the rule that replaced it before adding a `Pass`.
3. **The space root is refused as a selectable item.** Every protected rule matches the named folder
   or below it, never above, so one item of `alice/` named a subtree containing all of them. That
   closes the ancestor class for root-anchored rules only — a folder containing a *nested* protected
   folder is 188's problem, and the spec already says a nested marker is excluded from the plan
   rather than refused.
4. **`focommon/outcomes.py` ships `refused`**, which SPEC-188's own enumeration does not list. Add it
   there rather than re-deciding what an into-itself refusal is.

**SPEC-189 IS COMPLETE, and four of its findings change what 190 and 191 can assume.**

1. **The terminal carries everything the producer needs and it reads no second source** — the
   complete outcome list, the `operation`, BOTH spaces as `(kind, name)`, the destination prefix,
   each item's `targetName` and `kind`, and the per-item counts. `ReleaseLock` runs **before**
   anything that notifies, and a test pins that ordering: **191 inserts its producer AFTER it.**
2. **The outcome vocabulary is 13 members, not SPEC-188's 7**, and it gained `delete_failed` beyond
   what SPEC-189's own FR-008 enumerated — a `delete` that removed nothing is not a `duplicate`,
   because nothing was copied. Every member has a body in `focommon.messages`; 191 words them, it
   does not invent them.
3. **`CONDITIONAL_DELETE_ENABLED` is `False` and the HEAD-compare path is live.** Until the owed
   enforcement probe passes, a `move` has a race window between the head and the delete. That is a
   deliberate, recorded state — do not flip the flag without running §14 of the plane's script.
4. **The byte cap is 2 TiB, down from 3.** The joint budget had no lock-give-up term and came to
   ~12,700s against a 10,800s ceiling. Any spec adding a state to this machine re-runs
   `test_the_JOINT_budget_fits_the_machines_own_ceiling` — it reads every verb timeout back out of
   `locals.tf`, so a new verb is counted automatically but a raised timeout is not free.

**SPEC-188 IS ALSO COMPLETE, and it settled five things 189 inherits rather than re-decides.**

1. **The plan is the contract between the verbs**, at `{admin_bucket}/file-ops/{requestId}/plan.json`
   — its shape, its `executionArn`-based reuse guard and its `plan_superseded` check are in
   `lambdas/info/planes/file-ops.md`. Every object already carries its `etag`,
   so **189 does not need to re-HEAD anything** — but 189 still owes the check SPEC-188 FR-001 AC5
   names: confirm conditional `DeleteObject` against the live API before relying on it.
2. **The guard verb is reusable unchanged**, and 189's second pass is a second invocation of it, not
   a second implementation. It refuses nothing wholesale: a conflicted item comes back as an outcome
   record, so **189's commit gate is per ITEM** — a skipped item is planned and not copied.
3. **`FILE_OPS_MAX_TOTAL_BYTES` and `MACHINE_TIMEOUT_SECONDS` are both PROVISIONAL** and re-derive
   together. The byte cap's makespan already subtracts **two** guard sweeps, so 189 owes the copy and
   deletion terms rather than the whole computation.
4. **The machine's placeholders are `TransferPlaceholder` and `DeletePlaceholder`**, both bare
   `Pass` states reached after the guard. Every Task taken under the lock carries a `Catch` to
   `ReleaseLockOnFailure`, and a rule over every Task now asserts it — a Task without one has no edge
   to a terminal, so the release walk stays green while the space wedges.
5. **One residual is recorded and deliberately not built here.** FR-002's exclusion set is closed and
   says nothing about a *nested* protected folder inside a selected one — a `move` or `delete` of a
   shared-space folder containing a nested `archive/` or `athenaresults/`. The deletion is 189's and
   so is the per-item failure it would take; decide it there rather than widening the expansion's
   enumeration, whose four rules were each argued separately.

The shape is the file-send arc's, one spec per reviewable unit: **187** the plane, the contract, the
lock and validate-authorize; **188** source expansion, the copy plan and the destination guard;
**189** the transfer, the source deletion and the terminals; **191** notifications, Help and the live
checks; **190** the browser's async model and its in-flight state.

**SPEC-191 IS COMPLETE, and three of its findings change what 190 inherits.**

1. **Its FR-005 (Help & guides) MOVED TO 190, by the user's decision, and the reason generalises.**
   Building 191 first means nothing it ships is user-reachable — the browser enqueues nothing.
   Help is the sole exception: it deploys immediately, and a guide saying folder operations run in
   the background would have been false for as long as 190 was unbuilt, which SPEC-074 FR-005
   forbids. **A spec built out of dependency order should expect its user-facing half to travel
   with the behaviour, not with the machinery.**
2. **`ReleaseLock`'s CATCH reaches the producer too, not just its `Next`** — a release that
   exhausts its `Retry` would otherwise complete the operation and tell the user nothing, and 190's
   per-space gate settles on a notification carrying the `requestId`, so it would hold that space
   until the ceiling. 190 must not "tidy" that edge.
3. **The payload is bounded by BYTES as well as count**, so a re-submit built from a notification
   covers at most the carried conflicts — fewer than the count cap when the keys are pathological,
   and `more` says so. 190's conflict view is already specified as bounded; the submitting tab keeps
   the full list, and the notification is the durable fallback. **`requestId` is on every row,
   including a failed run's**, which is what lets 190 settle an in-flight entry either way.

**SPEC-190 IS COMPLETE, and the arc is CLOSED.** Three of its findings are worth carrying past it.

1. **The dispatcher is `useFileBrowserDialogs`, and the same-folder prompt's confirm moved there.**
   The five submission points are not symmetric: the probe that names an auto-numbered copy has to
   resolve BEFORE the routing decision, because its answer IS the `targetName`. `useCopy` therefore
   lost its same-folder branch and its source-prefix parameter, and its prompt is data only. The
   sweep now asserts exactly one importer AND exactly one call.
2. **FR-006 AC1 is partially delivered, on purpose.** The banner's outcome-grouped body is general
   over the plane's 13 outcomes, but the notification payload is capped at 1 KiB and carries only
   the conflicted items — a full per-item outcome list is not something that channel can hold. The
   run's other outcomes are told in the message. Widening the payload is a change to a shipped
   plane's contract; **a later spec that wants the browser to render every outcome must start
   there**, not in the browser.
3. **The conflict view is gated by `files`, not by the switchover's own flag.** Throwing the kill
   switch must not strand a conflict raised before it was thrown, and the `Review conflicts` control
   is already on shipped notification rows. A registry row's `name` is its accessible name and
   `RECIPES` keys are unique, so one control cannot hold a row under two flags — a spec adding a
   surface gated by two flags has to pick, or give the second one a different name.

**Build 191 BEFORE 190 — the numbering is not the build order, and the arc review is why.** SPEC-190
consumes 191's extended notification wire shape and its producer: its conflict view is reachable from
the notification, and it settles an in-flight entry by matching the `requestId` a notification carries.
Landing 190 first would put a version on `main` where every folder operation acknowledges "you'll get
a notification" that never arrives, in-flight entries never settle, and the per-space submit gate holds
until the machine's ceiling. 190 also ships behind a feature flag, which is what makes that window
survivable if the order is ever forced. It is five rather than
file-send's four because file-send's UI was one new dialog, where this one rewrites the file
browser's core interaction model — the biggest UI change in the arc, and not something to share a
spec with a notification producer.

**Three decisions are settled up front, and two of them were review findings rather than authoring
choices.**

**The async boundary is "exactly one file", not "is it a folder".** The first draft said an operation
goes async only when it must LIST to know what it touches — coherent, but measured against the wrong
quantity: a file-only *copy or move* of K files is a sequential loop of `HeadObject` + `CopyObject` +
`DeleteObject`, up to 3K round trips, which is precisely the cost the arc exists to remove. The rule
is now that a selection stays synchronous **if and only if it is exactly one file**. A single folder
is enqueued too, including a folder **rename** — forced rather than chosen, since a rename is one
`CopyObject` per contained object.

**FIFO does not serialize executions, so the plane takes a per-space lock.** The draft claimed
`MessageGroupId` serialized a space's operations against each other. SPEC-157 exists because that is
false: the Pipe starts the machine `FIRE_AND_FORGET`, so delivery is ordered and execution is not.
The consequence here is worse than table-builder's, whose loser overwrote a schema — this plane's
loser **deletes objects a concurrent move has already relocated**, unrecoverably, with versioning
off. The lock is SPEC-157's: an admin-bucket object under ETag CAS, held by the execution ARN,
released by overwriting, stealable only because the machine now carries a `TimeoutSeconds`.

**A browser pre-flight cannot bind an async decision, so the conflict answer rides on the envelope
and the plane re-checks.** `onConflict: 'refuse' | 'overwrite'` is part of the request contract from
the first spec, because a contract that cannot express "the user already confirmed" forces either a
contract change mid-arc or a silent semantic choice over buckets with versioning **off**. The
re-check before copying is SPEC-171's finding one plane over, where a file re-created between the
guard and the copy would have been overwritten and reported as success.

**One thing this arc gains for free, and it is a security improvement.** Every protected-folder rule
in this product — `athenaresults/`, `archive/`, `saved_queries/`, the `DO_NOT_DELETE.txt` basename
rule — is enforced **client-side only** today. Moving these operations onto a plane makes them
server-side for the first time: the browser's refusals stay as the affordance (SPEC-186 FR-002 —
refuse before the destructive confirm), and the plane becomes the enforcement, each verified by
deliberate violation of the other. That is the same gap SPEC-173's still-owed bucket-policy check
exists for, closed for a different set of rules.

**One target-environment note, filed 2026-08-18 and not work in this arc.** The client's design has an
**S3 event notification on upload completion** triggering the file-management state machine. That is
a second front door into this plane, and its envelope has no verified token in it — every
authorization check in SPEC-187 reads an actor the browser's request proved. If that trigger is
actually wanted, it needs its own spec: either a verb that derives the actor from the object key's
own prefix (the prefix *is* the principal, so this is tractable) or a decision that event-triggered
work runs as the plane rather than as a user. Do not let it arrive as a bucket-notification config
change.

**The one trap to carry into 188.** The three protected-folder lists in `protectedFolders.ts` differ
on purpose and must not be unioned — the first draft did exactly that in the same acceptance
criterion that forbade it, and would have silently removed the ability to copy *out of*
`athenaresults/`, which is picker-locked and undeletable but deliberately copy-able. State the rule
per (side × operation), enumerated against the real constants, and read that file's own note first.

## API-layer & containerisation arc (SPEC-192 → 202)

> **THE ARC IS COMPLETE. SPEC-202 merged in two parts — the retirement on 2026-08-31, the narrowing
> and the destroy on 2026-09-02 — and everything below this block is a dated note from while it ran.
> Read them as history.**
>
> **What shipped:** an HTTP API with one `$default` route verifying a bearer and assuming the portal
> role; the object surface, the catalog and the eight control-plane queues behind it; the SPA as a
> container on Fargate behind an ALB, configured by a runtime document; and then the subtraction —
> the Identity Pool, the browser's credential layer, CloudFront, the static bucket, `deploy-app.yml`
> and `infra/modules/app`, all gone. The browser holds no AWS credentials and reaches AWS only for
> presigned S3 bytes.
>
> **What the arc found that no spec predicted**, beyond SPEC-193's four apply-time traps below: that
> **no origin worked for five specs** because nobody added the container to the Cognito app client
> until the last one; that a **queue resource policy would have silenced every notification**; that
> SPEC-140's CSP **verification technique** was unsatisfiable and generalised from the wrong
> directive (corrected in `decisions/infrastructure.md`); and, one merge after the destroy, that the
> **Checkov accept list was holding the retired grant's own findings open**, so removing the grant
> made both acceptances stale — a hard error by design.
>
> **The open questions are settled:** 1 and 2 answered in the re-scope below, 3 **void** (the arc
> never replaced `lib/returnPath.ts`), 4 answered by SPEC-196. **What is owed** is not in this entry
> — [`docs/testing/owed.md`](../testing/owed.md) carries it, including the five checks merge 2 was
> taken with **waived rather than passed**, of which the fresh sign-in from a clean profile is the one
> that gates the merge itself.

> **SPEC-200 MERGED 2026-08-29 and the eight control-plane queues are behind the API.** The browser
> holds no AWS grant at all now; what it still calls directly is presigned S3 bytes and Cognito
> through Amplify. The message carries a nested `identity` block **alongside** the token it does not
> yet replace — SPEC-201 flips the planes onto it and only then stops the token being sent, and
> reversing either boundary fails all eight planes closed on the first request after deploy.
> **(Since run.)** SPEC-200's Phase 5 was owed here; seven of the eight planes were exercised
> through the API on 2026-09-01 with no browser `sqs:SendMessage` anywhere, and the grants
> simulation ran on 2026-08-30. What is left of it is in [`owed.md`](../testing/owed.md).
>
> **(Since observed, 2026-09-01.)** The arc's central claim — that Lake Formation keeps enforcing
> against the assumed-role session — was an argument when this was written and is now a measurement:
> as a member, a `SELECT` against another user's database failed terminally with no `/results` fetch
> and **no re-login**, while a database that user does hold returned rows in the same minute. One
> denied and one allowed through the same route, so the grant is on the **assumed** role. Whether a
> foreign and an absent database are distinguishable is LF's property, not the API's, and stays a
> row in [`owed.md`](../testing/owed.md).

> **SPEC-193 APPLIED 2026-08-26, and what the apply found is worth more than what the spec
> predicted.** The platform is live: `api.dataquarry.app` answers `/healthz`, `portal.dataquarry.app`
> serves a placeholder through an ALB, and a Fargate task **pulled from ECR with no NAT gateway** —
> the arc's central claim, verified beside a route-table read rather than on its own.
>
> **Four traps, none of them predicted, each costing an apply:**
>
> 1. **ELB calls `ec2:GetSecurityGroupsForVpc` on the caller's behalf** inside `CreateLoadBalancer`,
>    so it appears in no `elasticloadbalancing:` action list.
> 2. **A condition on a key the caller does not populate fails CLOSED.** The access-log bucket policy
>    was refused twice — once for `aws:SourceAccount`, once for `aws:SourceArn` alone — and ships with
>    no condition and both delivery principals.
> 3. **`ignore_changes = [task_definition]` means CI must point the service.** Terraform registers the
>    revision and never moves the service, so the task ran a tag nobody had pushed and failed with a
>    `CannotPullContainerError` **indistinguishable from the endpoint failure the platform exists to
>    be tested for**.
> 4. **A Fargate task volume cannot give a non-root container a writable path** — it arrives empty and
>    root-owned and does not initialise from the image. The mechanism is `linuxParameters.tmpfs`, and
>    **SPEC-194's image inherits this**: it must run as the uid the task definition names.
>
> **The lesson that generalises past this arc:** two hypotheses about that mount were wrong before the
> third change printed `id` and `ls -ld` instead of guessing again. When two guesses have failed,
> spend a deploy on **output**, not on a third hypothesis.
>
> SPEC-194 starts from a platform that works, with `deploy-spa-image.yml` replacing the dispatch-only
> `push-placeholder-image.yml` this spec shipped as scaffolding.

> **THE RE-SCOPE, 2026-08-18, and everything in it shipped as written.** It was a preamble telling a
> builder what the arc would and would not touch; it is now the settled account of what it did.
> **The arc was PREP WORK and kept the current Cognito authentication exactly as it is** (user
> decision). The BFF, Entra ID and Identity Center are **target-environment** work in a later arc; Arc
> B does everything that can be done ahead of that move without touching how anyone signs in.
>
> - **Sign-in is unchanged** — Cognito User Pool, Managed Login v2, Amplify in the browser, the Hosted
>   UI round trip and `lib/returnPath.ts` all stay. No session cookie, no DynamoDB session store, no
>   `/auth/*` routes, no code exchange of our own. Open question 3 below is therefore **void**:
>   `lib/returnPath.ts` is not replaced in this arc.
> - **The API authorizes with the Cognito ID token as a BEARER** — the trust model the seven control
>   planes already have. No cookie means **no CSRF surface and no `SameSite` requirement**, so the
>   *two-origins-one-registrable-domain* decision relaxes from a requirement to a preference.
> - **The Identity Pool kept minting browser credentials until SPEC-202**, which is what removed the
>   degraded window the BFF ordering created: every un-ported feature kept working through the arc, so
>   the live checks owed on the archive, table-builder and Data Explorer arcs stayed runnable.
>   SPEC-202 retired it on 2026-08-31, once nothing in the browser needed AWS credentials — **which
>   was not a change to how anyone signs in**, and reading it as one is the conflation the register
>   entry exists to prevent.
> - **`connect-src` keeps the Cognito hosts** (open question 2's answer, amended): API host + S3 +
>   `'self'` **+ the User Pool and Hosted UI hosts**, because Amplify is still running in the browser.
>   SPEC-140's recorded outage was exactly an omitted Hosted UI host.
> - **Provider-agnosticism survives in reduced form** — the API's token verification takes its issuer
>   and JWKS from configuration rather than hard-coding Cognito, so the later arc swaps the provider
>   rather than the verifier. It is a verifier, not an OIDC client.
> - **SPEC-195 is rewritten** as *the API's auth boundary*; **SPEC-196** takes the verified username
>   from the token rather than from a session record.
>
> Everything the entry below says about a BFF, a session, a cookie, a code exchange or Identity Center
> is retained **for the later arc to inherit** — not to build here.
>
> **AMENDED 2026-08-18 — the target environment now has two identity variants, and Arc B is
> deliberately outside them.** `transition_plan.md` §3.3 splits the identity plane into **[A]** Entra
> issuing OIDC directly with no Cognito at all (the baseline) and **[B]** Entra SAML with Cognito
> reduced to a bridge (the fallback), decided by gate G8 in Phase 0. **No variant decision reaches
> this arc and no spec here is gated on a transition gate** — the API is a verifier whose issuer,
> audience, JWKS URI and username claim are configuration, so a variant is a configuration change to
> a component this arc already ships.
>
> **It is not left literally untouched, and that is worth being exact about.** The revision adds
> three forward-compatibility obligations, each small, each with a test, each shippable today:
> SPEC-195 gains a premise keeping the verifier free of router dependencies; SPEC-198 strengthens one
> existing acceptance criterion so the presigned-URL clamp reads the credential rather than a
> configured duration; SPEC-199 requires the results-location derivation to stay in one function. Two
> further sections below are re-framed rather than changed — the shared-space membership section
> (now explicitly *interim*) and the credentials-never-reach-the-browser claim (unconditional here,
> gated on G9 in the target).

### What the review gate caught, and why the arc entry says so

The eleven specs were written in parallel and then put through `process.md`'s reviewer gate — three
per-spec passes plus one framed on **the arc as a whole rather than any one spec**. That fourth frame
is the one that earned its place: every defect below was invisible to the spec that contained it,
because each spec was internally consistent and pinned its own version with its own test.

- **The queue contract did not agree with itself.** SPEC-200 wrote `{"identity": {…}}` nested with
  `assurance: "verified-id-token"`; SPEC-201 read the fields flat and accepted only `"interactive"`.
  Both suites passed in isolation, and all eight control planes would have failed closed on SPEC-201's
  first deploy. Settled: nested permanently, `"interactive"`, and SPEC-201 owns the API-side token drop.
- **A queue resource policy would have silenced every notification in the product.** SPEC-201's
  blanket `Deny` on all but the API role denies `sqs:SendMessage` to the **seven** other execution
  roles that write to the notifications request queue — verified against `infra/main.tf` and the
  policy templates. It presents silently, because every notify path is best-effort by design: archives
  and shares would complete and users would simply never be told. FR-005 withdrawn; the identity grant
  stays the only path.
- **`tmpfs` is rejected on the Fargate launch type**, and SPEC-193's mount set disagreed with the paths
  SPEC-194 actually writes — with `readonlyRootFilesystem: true` the container would never have started.

  > **Corrected by SPEC-193 PR 5 (2026-08-26).** The mount-set half stands and is now asserted by a
  > test reading SPEC-194's own criterion. The tmpfs half does not: AWS's `LinuxParameters` reference
  > gives four fields an explicit Fargate-unsupported note and gives `tmpfs` none, so "rejected on the
  > Fargate launch type" is not established. The mechanism is `volumes` + `mountPoints` because the
  > image spec depends on that pair — and the shipped module uses no `linuxParameters` at all.
- **The runtime-config accessor threw before the app's own module-load reads** (`lib/s3Client.ts` and
  `fileBrowser.types.ts` both read at import), so a production build would have thrown before
  rendering. The bootstrap is now a dynamic import of the provider tree.
- **No origin worked for five specs.** Nobody added the container origin to the Cognito app client
  until the arc's last spec, so between SPEC-197 and SPEC-202 CloudFront was blocked by its own CSP
  and the API's CORS while the container could not complete a sign-in. The three additive changes
  moved to **SPEC-193**; SPEC-202 only narrows.
- **Two live checks could not have failed.** SPEC-198's credential-layer isolation proof was refused by
  its own route before IAM ever saw it, and the CloudTrail evidence three specs leaned on does not
  exist — the only trail records archive-bucket data events, single-region, no management events. The
  proof stays with SPEC-196's probe; the trail assertions are gone, and the slot-tag half is recorded
  as **owed and not dischargeable in this arc**.
- **SPEC-202 planned to destroy its own rollback.** One merge bundled the narrowing, the Identity Pool
  retirement and CloudFront's destruction, then ran the fresh-sign-in check afterwards. It is two
  merges now, and the spec says which one cannot be rolled back.

**This entry exists to hand the arc to a session that was not in the room when it was scoped.** Read
it before writing SPEC-192. It carries the decisions, the open questions and the traps; the reasoning
behind the settled ones is in `docs/transition_plan.md` §3–§4 (amended 2026-08-17) and in the
`decisions/` entries the arc's specs will add.

### Why the arc exists

The portal calls AWS directly from the browser. The client environment will not permit that, so every
SDK call moves behind an API, and the SPA moves from CloudFront to a container. Seventeen service
files and ~3,300 lines currently import `@aws-sdk/*`; `infra/` has no VPC, ALB, ECR or ECS.

**Arc A (SPEC-187 → 191) comes first and is the reason this one is tractable.** It moves every
operation whose cost grows with object count onto a control plane, which is what lets this API be
*thin* — tokens and service calls, nothing that loops over objects. Do not start this arc before
Arc A lands; an API built around a synchronous folder copy sets its own shape.

### Settled — do not re-litigate

- **Front door for the API: API Gateway.** The established pattern in the target environment. Every
  technical objection dissolved once the API became thin: presigned uploads remove the 10 MB payload
  cap, and with folder work on a plane nothing approaches the 29-second HTTP-API ceiling (which is
  **not** raisable; only regional/private REST APIs can be raised, at the cost of throttle quota).
- **SPA: a container on ECS Fargate behind an ALB.** It cannot go through CloudFront. `infra/modules/app`
  (CloudFront + static site) is retired.
> **SUPERSEDED for this arc by SPEC-195 (2026-08-27) — the NEXT THREE BULLETS describe the
> DEFERRED design, inherited by the later arc rather than cancelled.** What shipped is a
> **verifier, not an OIDC client**: no code exchange, no refresh token, no session, no cookie.
> Sign-in is untouched — the browser keeps its Cognito ID token and sends it as an
> `Authorization` bearer, which is the trust model the seven control planes have had since
> SPEC-011, with the token on a different transport. The relaxation matters: **no ambient
> credential means no CSRF surface**, so a later spec introducing a cookie re-opens CSRF,
> `SameSite` and the one-registrable-domain requirement this arc downgraded from a requirement
> to a preference. CORS is still required either way.

- **Two origins, one registrable domain.** SPA and API are separate hosts, so they must be subdomains
  of one parent — *same-site*, so the session cookie is delivered to both under `SameSite=Lax`, with
  CORS and `credentials: 'include'` on the API.
- **BFF compute: Lambda.** It meets the Identity Center constraints — `CreateTokenWithIAM` needs
  SigV4 credentials, which the execution role supplies, and the session state the single-use
  assertion forces lives in DynamoDB rather than in process.
- **Session: a BFF.** The server performs the OIDC code exchange and holds the tokens; the browser
  gets an opaque `httpOnly` cookie and nothing else. **The SPA never constructs an IdP URL** — it
  navigates to the API's own login endpoint, which mints the redirect and holds the PKCE verifier and
  `state` server-side.

- **AWS credentials never reach the browser.** The API assumes a role carrying the user's identity —
  a `username` session tag now, an Identity Center identity context later — and makes the calls
  itself. Every existing IAM policy, bucket policy and Lake Formation grant keeps enforcing unchanged.

  > **CORRECTED by SPEC-196 as built (2026-08-27): "a `username` session tag" understates it.** The
  > identity is **eleven** tags — `username` plus one `shared_space_k` per occupied membership slot —
  > and the slots are the half that fails **silently**. Stamp `username` alone and personal S3,
  > personal Glue, notifications and the file browser all keep working; only shared spaces refuse,
  > which is indistinguishable from the propagation delay the product already documents and already
  > offers a recovery for. The slot tags are also the half SPEC-196 **cannot prove live** — nothing
  > it ships touches a shared space — so that proof is owed to SPEC-198.
- **File bytes: presigned URLs**, both directions. The browser talks to S3 for bytes only, which is
  why **bucket CORS is still required** for the new origin. **In the target this survives only if the
  API can presign from `GetDataAccess`-vended credentials — gate G9** (`transition_plan.md` §5.5,
  §3.9). It is unproven, it is cheap to prove, and if it fails the browser holds scoped credentials
  after all and SPEC-202's load-bearing negative needs re-wording. Nothing in Arc B waits on it.
- **Queue trust:** the API verifies the token, strips it, and writes a verified `actor`. The queues
  become writable only by the API's role. The control-plane Lambdas drop JWKS verification and keep
  every authorization check.
- **Identity provider: Entra ID in the target environment, Cognito today**, and the OIDC layer is
  provider-agnostic so one image serves both. The current environment keeps Cognito and its two
  trigger Lambdas exactly as they are. **This is now load-bearing rather than a convenience**
  (2026-08-18): the target's baseline variant deletes Cognito outright, so the configuration-driven
  verifier is what makes that a config change instead of a rewrite — see SPEC-195.
- **Machine-facing API: designed for, built later.** `{actor, delegated_by, assurance}` enters the
  control-plane message contract in this arc so the later door needs no rework. Callers act **on
  behalf of a named user** and pass the portal username directly.
- **A control plane runs under its own execution role and the requesting user rides in the message —
  and that is FORCED, not chosen** (recorded 2026-08-18). Step Functions is not a
  trusted-identity-propagation receiving service, and `AWSIAMIdentityCenterAllowListForIdentityContext`
  — which STS attaches to every identity-enhanced session and which denies everything not on its
  list — carries no `states:` actions. So an identity-enhanced session **cannot start an execution**,
  and even if it could, a ~1-hour session is shorter than the work. This is the strongest
  justification the `{actor, delegated_by, assurance}` contract has, and it is external to us: the
  user identity is for **authorization and attribution**, never for data-plane enforcement inside a
  plane. SPEC-200 records it.
- **The queue in front of a plane is NOT optional, and the tempting simplification is REJECTED**
  (recorded 2026-08-18). API Gateway offers a native `StartExecution` integration, and a target-side
  reader will propose using it to delete the enqueue hop. It would take the FIFO
  `MessageDeduplicationId`, the `MessageGroupId` ordering, the request DLQ and SPEC-126's drain, and
  the at-least-once redelivery model SPEC-157's per-table lock is written against — all of which are
  load-bearing here and none of which a direct `StartExecution` has. SPEC-200 carries it as a named
  rejected alternative so it is refused once rather than re-argued.

### The correction most likely to be made again

**Identity Center is not a login provider for a web application.** The citation to use is AWS's own
**Important** on the customer-managed-applications page: such an application *"must obtain a token
from a trusted token issuer, **which is external to IAM Identity Center**."* That is the whole
argument, and it is documented rather than inferred. *Do not lean on the older phrasing that IdC's
OIDC service "implements only the device-authorization parts needed for the AWS CLI" — it is
quotable from the OIDC Welcome page but sits in the same guide as `CreateTokenWithIAM`, which
documents `authorization_code` with PKCE, `refresh_token`, `jwt-bearer` and `token-exchange`. The
conclusion is right; that sentence is the weak way to reach it.* So Entra and
IdC are not alternatives: **Entra authenticates the users; IdC propagates their identity into AWS.**
Anyone who reads "tie the app to an Identity Center login" as a sign-in flow will build something
that cannot work.

Two further constraints on that flow, both settled and both easy to lose: the jwt-bearer assertion is
**single-use** (IdC rejects a second exchange of the same token, so exchange once at login and use the
`refresh_token` grant after), and **DynamoDB TTL deletes expired items only within a few days** while
an expired-but-undeleted item is still returned by reads — so session expiry is checked on read, and
TTL is storage hygiene rather than the security boundary.

### Shared-space membership: the tags come from YOUR registry, not from any directory

> **This section describes the TARGET ENVIRONMENT, not Arc B.** What Arc B actually builds is
> **SPEC-196**, which stamps `shared_space_1..N` from the **`custom:shared_space_k` claims of the
> verified Cognito ID token** — byte-identical to what the Identity Pool stamps today, which is the
> whole argument that no IAM policy is rewritten. Do not source those tags from the registry while
> building SPEC-196; that would break the equivalence, and SPEC-196 records it as a requirement whose
> wrong implementation silently succeeds. `useSharedSpaceAccessRecovery` stays for the same reason:
> claim-sourced tags still carry SPEC-056's propagation delay.

> **AMENDED 2026-08-18 — this section describes the INTERIM plane, and it is right about it.**
> `transition_plan.md` §3.4 collapses the target's two credential planes into one, and the
> identity-enhanced session's allow-list denies plain S3 — so in the **end state there are no
> principal tags at all**, and a member's access to a shared space becomes an **S3 Access Grant on
> its prefix plus a Lake Formation grant on its database**, issued per (member, space) by the
> shared-space control plane (§3.9).
>
> What follows is still correct and still gets built, for **Phases 1 through 4**: the API assumes the
> portal role with `username` plus the membership tags computed from the registry, and every existing
> policy keeps enforcing. That interim plane is what makes a working file browser possible before the
> trusted token issuer, the customer-managed application, the Access Grants instance and the
> IdC-enabled workgroup exist. Read this section as a **way station with a known exit**, not as the
> destination — and note the exit is *better* on the same axes: no per-user slot limit, no propagation
> delay, no directory attribute, and per-user attribution on storage as well as on queries.
>
> **One correction to what follows, and it is the thing most likely to be misread.** The
> ten-slot ceiling does **not** dissolve when the tags stop coming from Cognito. It lives in
> `infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl`, which loops over
> `max_shared_memberships` and emits `${aws:PrincipalTag/shared_space_${k}}` into the S3 resources,
> the `ListBucket` prefix condition and the Glue ARNs — so an eleventh tag matches no resource
> whatever wrote it. `AssumeRole` accepting 50 session tags is true of STS and irrelevant to
> enforcement. The ceiling goes at Phase 5, with the tags.

**Both directories are effectively shut, and that is fine.** Membership is a principal tag today
(`custom:shared_space_1..N`, written by `shared-space-add-members`, mapped by the Identity Pool to
`${aws:PrincipalTag/shared_space_k}`). In the target environment you cannot write to Entra. Identity
Center is subtler, and the flat claim that its store is "read-only under SCIM" is **wrong**: what AWS
documents is that *"after setting up automatic provisioning with SCIM for your IdP, you can no longer
add or edit users in the IAM Identity Center **console**"*, while *"the Identity Store APIs that allow
for mutating users and group membership remain accessible"* to principals in the **management account
and the delegated administrator account**.

That is a stronger argument against stashing membership there, not a weaker one. The door exists but
it is the wrong door: it needs management-account or delegated-admin privilege this application will
never hold, and AWS warns in the same breath that using it on a SCIM-provisioned directory causes the
directory to **drift from the IdP** — "breaking the expectation that the IdP is the single source of
truth", with unintended privilege escalation and audit gaps named as the consequences, and an SCP
offered to block it outright. So membership stays ours by design, not by inability.

**The BFF removes the need.** Membership had to live in the IdP only because the *browser* received
credentials directly and could not be trusted to assert its own. The BFF calls `AssumeRole` itself, so
it computes the tags from the **shared-space registry** — already the source of truth, and already the
authorization input everywhere that matters (`is_active_member`, never the member's join chip). The
trust level is unchanged: the BFF is a privileged server-side component like the control planes that
write the registry, and the browser still cannot influence it.

Three things this improves rather than merely permits. **Membership takes effect immediately** — today
there is a propagation delay that `useSharedSpaceAccessRecovery` exists solely to paper over, and that
affordance can go. **The slot limit gets easier to raise, but does not dissolve** — `shared_space_1..N` is a fixed
pre-allocation partly because a Cognito custom attribute can never be renamed or deleted, and
`AssumeRole` takes up to 50 session tags so you pass only what applies. **The binding constraint is
the IAM policy**, which enumerates the slots; raising the cap means re-rendering it, bounded by IAM's
6,144-character inline-policy limit. Only Phase 5's move off principal tags removes it. **The self-service-edit risk disappears** — no directory attribute
backs the tag, so there is nothing a user could edit to assume someone else's access.

Keep the same tag keys and values and **no IAM policy changes at all** — only where the tag comes
from. That holds for the whole interim window; Phase 5 then retires the tags and the
`${aws:PrincipalTag/username}` conditions along with them, which is a policy change and is scoped
there rather than here.

Where IdC still matters for shared spaces is the **catalog plane**: Lake Formation grants against the
IdC user for a shared space's database. IdC groups cannot be **authored** — but SCIM syncs them from
Entra, so groups do exist and are perfectly good grant targets. The distinction is worth stating,
because it decides where a grant is keyed: **team-level** data sharing grants to an Entra-sourced
group and needs nothing from our registry, whereas a **shared space** is this app's own construct with
no Entra group behind it, so its grants stay per-user and registry-driven — §3.8's reconciler.
Do not model shared spaces as directory groups.

**And that is the same reason the end state's storage grants are per-user too.** Once the tags are
gone, the Access Grant on a space's prefix is keyed exactly the way the Lake Formation grant on its
database already is: per (member, space), from the registry, issued by the plane that owns
membership. The two halves are one job and are designed as one: **`transition_plan.md` §3.11**.

### Other applications acting on behalf of users

**Which half of this Arc B ships, and which half is the target environment.** Arc B lands the
*contract* — `{actor, delegated_by, assurance}`, nested under one `identity` key, with `assurance`
`"interactive"` and `delegated_by` null for a human at a keyboard (SPEC-200) — and the planes trusting
it (SPEC-201). It ships **no** delegated door: no non-human authorizer, no credential issuance, no
may-this-client-act-as-X allowlist. Everything below about tiers, token exchange and the BFF describes
the **target environment**, where the BFF exists; today the API verifies the Cognito ID token instead
and the shape is identical downstream. Read it as the design the contract was cut to fit, not as work
in this arc.

**IdC provides identity ASSURANCE, not authorization.** It can vouch that a user really is who a caller
says; it cannot say what they may do in this application — the registry does that, and always did. A
team expecting IdC to be what *enables* delegation has the wrong model.

Because the BFF resolves membership from the registry, the path downstream of identification is
**identical** for a browser session and a delegated call. Two tiers differ only in how the end user was
established: an **IdC-integrated caller** presents an IdC access token scoped to this application as
audience, exchanged through the token-exchange grant so IdC validates the user; a **non-IdC caller**
authenticates as itself (IAM SigV4 or client credentials), asserts a username, and is checked against a
per-service delegation allowlist. That difference is what the `assurance` field records, and why
flattening the two would be wrong.

**The control planes never notice.** They receive `{actor, delegated_by, assurance}` and authorize on
the registry; they never see a token. A delegated request and a browser request produce byte-identical
messages apart from those two fields, so delegation costs the planes nothing.

**One real limitation, and it IS binding.** A delegated call whose user identity was *asserted*
carries no IdC identity context, so it cannot make a Lake Formation-enforced query on that user's
behalf. **Triggering** is unaffected — the enqueue paths run inside a control plane under its own
execution role with LF grants to that role, so the user identity is used for authorization and
attribution, never for data-plane enforcement. But **reading data as the user is not delegation
through this API at all**, and the earlier reading — that consuming teams only want to trigger
processes — is wrong: teams may want Lake Formation permissions of their own.

It is a separate integration that **bypasses the BFF entirely**, in one of two shapes: **(a)** we grant
Lake Formation permissions in **our** account, RAM-share the resource, and the other team queries from
**their** account under their own propagated identity; or **(b)** they run against an **IdC-enabled
Athena workgroup in our account**, with their users assigned through Identity Center. Either way our
API is out of the path — which is cleaner than routing data reads through a BFF that could not
propagate identity anyway.

Three facts fence that off, each confirmed against the live AWS docs:

- **RAM sharing carries trusted identity propagation only inside one organization instance.** Grantor
  and grantee must be in the same **Region**, the same **AWS Organization**, and the same
  **organization instance** of IAM Identity Center. An account instance forecloses shape (a) outright —
  hence the new open question below. **Source note:** this one is *not* on the limitations page the
  next two are quoted from — it is in Lake Formation's cross-account sharing material, corroborated by
  Identity Center's own prerequisite that with an account instance *"all AWS services that you want
  users to access with trusted identity propagation must reside in the same AWS account."* Do not go
  looking for it on `identity-center-lf-notes.html` and conclude it is invented.
- **The grants stay ours.** Lake Formation refuses to grant to IdC users or groups on Data Catalog
  resources in an external account — the literal error is *"Cross-account grants are not supported for
  the principal."* Permissions are granted only on resources in the **owning** account; an
  external-account IAM role acts as a **carrier role** on behalf of an IdC user or group.
- **Shape (b) is new infrastructure, not a config flip.** An IdC-enabled Athena workgroup requires
  **both** Lake Formation configured for IdC identities **and** S3 Access Grants — *"Amazon S3 Access
  Grants must be configured to use Trusted identity propagation identities."* Access Grants is nowhere
  in this architecture today. It also explains `transition_plan.md` §3.6: the
  `AWSIAMIdentityCenterAllowListForIdentityContext` policy permits only the three S3 Access Grants
  operations, which is why plain `GetObject` is denied on that plane.

**And the same page reaches our own Path B. It is AMBIGUOUS, and both confident readings are wrong.**
The considerations list names *"Federated access to the Athena API"* among the features TIP is **not
compatible with**, and says queries in a TIP workgroup *"cannot be run directly from the Athena
console. They must be run from the Athena interface in an EMR Studio that has IAM Identity Center
enabled."* Athena SQL support for TIP is stated to be available *"in both EMR Studio and SageMaker
Unified Studio"* — both studio products. Read one way, our shape is exactly what that bullet excludes.

But AWS uses *"federated access to Athena"* elsewhere as a **narrow, named feature**: the page titled
*Use Lake Formation and JDBC or ODBC drivers for federated access to Athena* defines it as *"SAML
2.0-based federation with Athena using Okta and Microsoft Active Directory Federation Services (AD FS)
identity providers"*. The sibling bullet in the very same incompatibility list names that driver
feature, so the two plausibly read as the API half and the driver half of one SAML feature — which our
shape is not. TIP's own mechanism (`AssumeRole` with `ProvidedContexts`) exists precisely so a caller
*can* make AWS API calls carrying an identity context, and the console exclusion is explicable by the
console's session not being identity-enhanced rather than by a ban on API callers.

So: **materially at risk, not settled either way — and settled only by experiment.** That is gate G7
(`transition_plan.md` §5.5), and it stays in **Phase 0** because `transition_plan.md` §3.5's step 3 and
the whole identity-enhanced query design rest on the answer. Budget for the possibility that it fails; do not
plan as though it already has.

**CORROBORATED 2026-08-24 — the narrow reading is now the better-evidenced one.** AWS shipped
trusted-identity-propagation plugins in the Athena JDBC (3.6.0) and ODBC (2.0.5.0) drivers on
2025-09-10, and the browser-based variants two months later (JDBC 3.7.0, ODBC 2.0.6.0, 2025-11-21):
ordinary client code exchanges a JWT, assumes an identity-enhanced session and calls the Athena API,
with no studio product in the path. That is our shape, shipped and documented by AWS, so *"federated
access to the Athena API"* cannot mean "any API caller carrying an identity context". G7 stays a gate
— a vendor driver may hold a privileged path our own code does not — but expect it to pass.
`transition_plan.md` §3.10 carries the detail, and it also reaches a question this arc never asked:
the client's Excel, Access and Power BI users **survive the transition, but every one of those
desktops is a cutover** — they are on the SAML path today, which genuinely is incompatible with TIP.
See `transition_plan.md` §2 item 15 and §3.10's migration subsection.

Three more constraints from the same list bite independently of G7. **An IdC-enabled workgroup cannot
be modified to support resource-level IAM permissions or identity-based IAM policies** — which
constrains what can happen *inside such a workgroup*, and does **not** reach the plane where
`${aws:PrincipalTag/username}` governs S3 and the personal Glue database.

> **SUPERSEDED 2026-08-18.** This passage said that plane was *"§3.4's separate base plane"*, separate
> **by design**. `transition_plan.md` §3.4 is superseded: there is one plane in the end state, and the
> tag-governed one is the **interim** plane that runs through the transition's Phase 4 and retires in
> Phase 5 (§3.9). They are separate in **time**, not by design. The constraint above is unaffected
> either way; only the reason it does not bite is.

A workgroup's
**authentication method is fixed at creation** and an existing workgroup cannot be converted.
**Entitlement changes take up to an hour**, which floors the reconciler's lag no matter how often it
runs, and queries **time out at 30 minutes, one hour maximum**.

### Was open — all four settled 2026-08-18, when the specs were written

1. **The machine-facing surface is DEFERRED to a later arc; only its contract lands here.**
   `{actor, delegated_by, assurance}` enters the control-plane message contract in **SPEC-200** and
   every plane accepts it (`delegated_by` null for a human at a keyboard). No non-human authorizer, no
   credential issuance, no may-this-client-act-as-X model and no rate limiting ships. The reason to
   land the contract anyway is that the alternative re-opens seven planes' message contracts, their
   parsers, SPEC-126's DLQ-drain redaction and their log records later; the reason to defer the door
   is that the human path has not run live until **SPEC-202**, and this repo's record (SPEC-137, and
   SPEC-140's `connect-src`) is that an auth surface fails in the state nobody exercised.
2. **The `connect-src` derivation** is the API host + the S3 endpoint (for presigned bytes) + `'self'`,
   **not** SPEC-140's enumeration of AWS service hosts — still derived from Terraform variables, never
   frozen as a string, and rendered into the nginx config at container start. **SPEC-194** owns it;
   **SPEC-202** asserts the final state.

   > **Answered and shipped by SPEC-194 (2026-08-27).** That end state is right and the **start
   > state is not** — on the day the container shipped the list is every host SPEC-140 enumerates
   > **plus** the API origin, because nothing is ported yet, and it shrinks one entry per porting
   > spec. Both CSP locals live at **root**; the container takes `connect-src` from the task
   > definition as one variable and bakes every other directive, those being properties of the
   > bundle rather than of the environment. Two things this question did not anticipate: nginx has
   > **no escaping**, so anything interpolated into its configuration must be allowlist-validated —
   > a quote truncated the policy and a `;` appended a directive, on a container that reported
   > healthy — and a policy assembled with `join` needs its **separator** asserted, since joined on
   > a space it is one malformed directive with every element still present.
3. **`lib/returnPath.ts` is replaced by a server-side return path**, held beside `state` in the BFF's
   login transaction, which survives private browsing where `sessionStorage` degrades. The module is
   deleted. **SPEC-195** owns it.
4. **The API is Python, and it is ONE Lambda function.** Python because every other Lambda here is —
   it reuses `cpcommon.observability` (so API records land in `logs/` beside the seven planes), the
   Lambda deploy matrix, the layer packaging and the blocking `ruff`/`mypy` gates. The cost is that
   the transport contract exists in two languages, so **SPEC-197** must ship a mechanism holding them
   in agreement rather than two hand-edited copies. **As built:** declared once in Python, the
   TypeScript generated from it, with a CI regeneration-diff gate and `tsc -b` as the second gate. One function behind a proxy integration, not one
   per route: the API is thin, and per-plane privilege is expressed by which role a request assumes
   (**SPEC-196**), never by which function ran.

### What SPEC-197 found, and what it passed on

**A preflight was refused by the router, so no browser could reach the API with a bearer.**
`$default` matches `OPTIONS`, and API Gateway auto-answers a preflight only when *no* route matches
— so preflights reached the Lambda and were denied by default. Every bearer-carrying `fetch` failed
as an opaque `TypeError`, which reads to a user as "the API is down". Invisible to `curl`, which does
not enforce CORS, and to every offline gate. The router now answers `OPTIONS` before authentication —
**offline-asserted and live-owed**: that the gateway overlays its configured CORS headers onto the
integration's own `OPTIONS` 200 is taken from AWS's documentation rather than measured, and the
failure mode if it is wrong is silent (suggestions stop appearing, with no banner).

**The isolation proof passes to SPEC-198, and SPEC-196 Premise 2 must not be read as discharged.**
`GET /v1/user-directory` cannot carry it: the `ReadTheUsernameDirectory` grant is unconditioned and
the document is byte-identical for every caller, so the route returns the same bytes with the
principal tag dropped. What it does prove live is the *plane*. A live 403 on this plane passes too —
it cannot be staged against a bucket-wide grant.

**§D and §E were partly run on 2026-08-27** rather than at SPEC-202, because SPEC-197 deletes the
probe routes they are driven through; running them at 202 would have deleted the only instrument
that can observe the isolation model before it was ever observed. What ran and what did not is in
`docs/testing/sessions.md`.

### One more decision the arc took, because it supersedes a Key Decision

**The dev-unauth path is retired** (`VITE_S3_DEV_UNAUTH`, the read-only public test bucket and its
`/files` auth-gate bypass) in **SPEC-198**, with the browser's S3 client — it works by calling S3 from
the browser, which is the thing this arc removes, and keeping it would mean the SPA still ships
`@aws-sdk/client-s3` for one dev-only branch nobody tests against the real one. Local work points the
SPA at a locally-run or deployed API. **Done 2026-08-29**: the entry is
`decisions/identity-and-access.md` → *The dev-unauth path is retired*, and the markers are in
`CLAUDE.md`, `architecture.md` and `.env.example`.

### What SPEC-198 found that the arc did not forecast

**The isolation obligation splits in two, and only one half is this API's to prove.** A correctly
built route refuses a foreign prefix *before* reaching AWS, and from outside that refusal is
indistinguishable from an IAM denial — so the **route layer** is proved offline, by call count
(zero botocore calls and no `AssumeRole` on the refusing path), and the live 403 records only that
the deployed route refuses. The **credential layer** has no observation surface here: the account's
only CloudTrail trail selects S3 data events on the **archive** bucket alone and records no
management events, so any criterion phrased as "CloudTrail shows the call was issued and denied"
**cannot fail** — it returns nothing whether the call happened or not. The citation for that half is
SPEC-196 Phase 5 item 6's dated `_identity/self` result. This arc adds no trail selector: that is
unbudgeted infra, and if it is ever wanted it is a spec of its own.

**A temporary foreign-prefix probe route was DECLINED.** A route that grants a foreign-prefix read in
order to test that foreign-prefix reads are refused is the shape of the defect it tests for.

**A document that belongs to no user needs its own route, and that is now twice.**
`_directory/usernames.json` was the first (SPEC-197) and `_config/feature-flags.json` the second —
found during SPEC-198's build, because the space resolver refuses a prefix no caller's claims
authorize and the flag read would have 403'd into the compiled-in all-on defaults, which is
indistinguishable from a healthy environment. SPEC-199 and SPEC-200 should expect a third rather than
discover one.

### Was open, now answered — and it was never a spec decision

**Which Identity Center instance the portal lands on: SETTLED 2026-08-18 — the ORGANIZATION
instance.** Confirmed with the client platform team alongside same-Region and single-central-account.
No spec could have closed it; it was theirs to answer, and the answer is the permissive one.

**What it un-forecloses.** An account instance would have ruled out shape (a) below — RAM-shared data
read from another team's account under their propagated identity — because AWS's prerequisite is
explicit that with an account instance *"all AWS services that you want users to access with trusted
identity propagation must reside in the same AWS account"*, and Lake Formation's RAM sharing carries
trusted identity propagation only when grantor and grantee share a Region, an Organization **and** an
organization instance. Both shapes are now available. Nothing in Arc B ever depended on the answer;
Phase 5 and any future team-level data sharing did.

**One question replaced it, and it is answered in the transition plan rather than in a spec:
`transition_plan.md` §3.11.** Per-(member, shared-space) Access Grants and Lake Formation grants
(§3.9) are a new verb plus a reconciling sweep on the shared-space control plane, they are transition
Phase 5 work, and the Phase 3 inventory sizes them. Its companion, **SPEC-203**, ships in *this* environment: it is where the interim plane's
membership tags come from once there is no Cognito claim to read.

It is here because of what it forecloses. AWS's own prerequisite is explicit: with an **account
instance**, *"all AWS services that you want users to access with trusted identity propagation must
reside in the same AWS account where you enable IAM Identity Center."* So an account instance rules
out shape (a) above — RAM-shared data read from another team's account under their propagated
identity — because Lake Formation's RAM sharing carries trusted identity propagation only when
grantor and grantee are in the same **Region**, the same **AWS Organization**, and the same
**organization instance**. AWS recommends the organization instance for exactly this reason.

Nothing in Arc B depends on the answer; everything in Phase 5 and any future team-level data sharing
does.

### The shape

**192** runtime configuration (`VITE_*` becomes runtime accessors — the prerequisite that lets one
image promote across environments, and the OIDC provider block lives here — see *What 192 found*
below); **193** the VPC, ALB, API
Gateway, ECR and ECS, with the deploy-role IAM expansion as in-scope work; **194** the SPA container
and its nginx config, which reproduced every job CloudFront was doing — SPA fallback, per-class
cache headers, the security header set, compression, health check — three of them as **named
divergences** (`Server: nginx`, no brotli, no HSTS `preload`); **195** the BFF —
session, provider-agnostic OIDC, the DynamoDB store; **196** the AWS identity layer, per-plane
credential providers; **197** the transport contract plus one small feature ported end to end to
prove the spine; **198** the file browser and presigned URLs; **199** catalog (Athena + Glue); **200**
the delegated actor contract and the enqueue paths; **201** the Lambda trust boundary; **202**
retiring CloudFront and the Identity Pool, and the arc's live checks.

Order de-risks: infrastructure early (new resource types trip this repo's recurring IAM traps, so
prove the pipeline with a placeholder API before porting anything), then the auth and transport spine,
then the volume.

### What 192 found, and what the next spec inherits

**The sequencing the arc scoping did not make.** The document has to be published **before** the app
depends on it, and the arc brief left that unstated. It shipped as three PRs: publish `/config.json`
from `deploy-app.yml` while the app still read the inlined values, read the deployed document back by
hand, then switch over. The reverse order breaks production for the length of a review, and neither
the suite nor `tsc` can see it — Vitest runs with `import.meta.env.DEV` true, where a fallback answers
every read. Reverting the switchover alone restores a working bundle.

**The document is 20 keys, not the spec's nineteen**, because Arc A's `VITE_FILE_OPS_QUEUE_URL`
landed first; it joins group (b), so the end-of-arc figure of **ten** is unchanged.

> **CORRECTED by SPEC-197 as built (2026-08-27).** `apiBaseUrl` had no `VITE_*` variable because
> nothing read it. It is **required** now and has `VITE_API_BASE_URL`, on the rule that every
> required key has a dev fallback: the dev-boot warning is driven from the classification, so a
> required key without one warns about nothing at all — `[null].join(', ')` is the empty string.
> Seeding the test harness instead, as SPEC-197 FR-007 describes, was measured at 69 failures
> across 3 files, because a one-key seed moves every `vi.stubEnv` suite onto the document path.

**SPEC-194 inherits four obligations.** (1) `/config.json` is served by the SPA's own container and
**never proxied** to API Gateway — the SPA must render its own error states while the API is down.
(2) It must exclude `public/config.json` from the image build context; a committed one is served in
preference to the rendered document, and a test asserts its absence. (3) It re-points FR-008's
agreement test at the ECS task definition, the fifth wiring point. (4) The interim CloudFront cache
behaviour dies with the distribution, so nginx's `no-store` becomes the only guarantee — and the
reason it matters is measured: CachingOptimized applies its **1 s MinTTL even against an origin
`no-store`**, and an object reaching an edge without the header takes a **24-hour** DefaultTTL.

> **SPEC-194 IS COMPLETE (2026-08-27), and here is what it settled.** All four obligations are
> discharged: `/config.json` is rendered by the container's own entrypoint and served by its own
> nginx, never proxied; the build context excludes it, from a `.dockerignore` **at the repository
> root** rather than beside the Dockerfile, which is where Docker would not have read it; the
> agreement test reaches the task definition, and the entrypoint's own key list is a **sixth**
> wiring point, not the fifth — it is the leg that actually renders the served document; and
> nginx's `no-store` is asserted on the response.
>
> **What the next spec inherits.** The image is live on `portal.dataquarry.app` and CloudFront is
> still production and still the rollback, so two delivery paths run until the cutover. Bucket CORS
> admits the CloudFront origin only, so the browser's direct S3 calls fail **preflight** from the
> container origin until SPEC-198 — expected, not a defect. Terraform registers task-definition
> revisions the service is never pointed at (`ignore_changes = [task_definition]`), so a change to
> the runtime-configuration map or the CSP reaches the running container only on the next push to
> `main`, or through the deploy workflow's `workflow_dispatch`.
>
> **Two traps worth carrying forward.** nginx has **no escaping mechanism**, so anything
> interpolated into its configuration must be allowlist-validated — a quote truncated the policy
> and a `;` appended a directive, on a container that started and reported healthy. And responses
> nginx generates **before it resolves a location** reach no location block at all, so a
> per-location header discipline needs a server-level floor beneath it.

**One live check was withdrawn rather than deferred**, and it is worth knowing why before someone
re-adds it: after `/config.json` gets a `CachingDisabled` behaviour, no observation distinguishes a
present from a missing origin `no-store` header. The header is read directly instead.

### Two traps carried from Arc A

**The five `cognito:username` readers collapse to one.** `transition_plan.md` §6.1 calls that claim
the highest-consequence detail in the migration — three readers in `cpcommon/auth.py`, one in
`notifications_writer.py` with its own verification path, one in `shared-space-common/auth.py`, plus
the SPA. After this arc the BFF derives `actor` once and everything downstream reads a field it
cannot forge. That is a large part of why the API migration should happen **before** the environment
move rather than after.

> **Discharged and corrected, 2026-08-30 (SPEC-201).** The collapse happened; two details in the
> sentence above did not survive contact. There is **no BFF** — the arc's re-scope removed it, and
> the **API** derives the actor from the bearer it verifies, which is the same collapse by another
> mechanism. And `notifications_writer.py` had not had "its own verification path" since SPEC-156
> FR-004; it was a claim *reader*, which is why the count of five still held. What is left in
> `lambdas/` is nothing: the whole Cognito arm of `cpcommon.auth` is deleted, and a sweep fails if
> a shipped module writes a provider's claim name as a literal again. `identity-pool.tf` retires
> with the Identity Pool in SPEC-202; the SPA reads `getCurrentUser().username`, which is the same
> value but never the claim string.

**The API stays thin only if it is kept thin.** Arc A moves folder operations, but the browser still
holds work that grows with object count: the SPEC-020 upload queue, and `firstFreeName`'s up to 999
sequential `HeadObject` probes. Those are deliberate residuals, recorded so this arc inherits them
knowingly.

> **The probe half is discharged, 2026-08-29 (SPEC-198 FR-004): one route, not 999 round trips.** The
> upload queue's residual stands and is now sharper — the queue is client state and does not move,
> and its bytes go straight to S3 under a presigned URL minted per file. **Premise 1 is what keeps
> the rest thin and is now mechanical:** every `list_objects_v2` in `lambdas/api/` passes
> `Delimiter='/'` and a bounded `MaxKeys`, no module imports `get_paginator`, and a test enforces
> both. SPEC-199 and SPEC-200 inherit it.

## Transition identity arc (SPEC-203 and SPEC-205)

These specs exist because a fresh-context review of the identity-variant revision found the same
gap twice: `transition_plan.md` names obligations that **no spec owned**, and each is the kind
of work that arrives as "a small change during Phase N" and is a plane's worth of design.

**They were never an arc in the usual sense.** They do not compose and they shipped far apart.
**203 was not "buildable today" either** — it lands after SPEC-199 and before SPEC-202, because it
depends on the API boundary, the identity layer, the transport and the route surface. What it had
was a window: SPEC-202 retires the Identity **Pool**, not the User Pool, so the Cognito claims
persist to the environment move and 203's parity assertion stays available for the whole of it.

**The arc was three specs and is now two.** SPEC-204 — the projection that replaces the tag once
principal tags are gone — was **cancelled on 2026-09-01** and its design moved to
[`transition_plan.md` §3.11](../transition_plan.md#311-shared-space-entitlements--the-projection-that-replaces-the-tag),
under the rule that work which can only be done in the successor account belongs in the plan rather
than in a spec. What the three shared is a subject — *where a shared-space membership becomes an AWS
permission* — and a lifetime: 203 is how that works while principal tags exist, §3.11 is how it works
once they do not, and §3.11's cutover ordering is the seam between them.

### Why 203 ships before the environment moves

SPEC-196 builds the `shared_space_k` session tags from Cognito custom-attribute claims, deliberately,
because byte-identical tags are what make its "not one IAM policy is rewritten" claim provable. In
the successor account those claims do not exist in either identity variant, so the tags have to come
from the registry — and **that is a real change to the credential-minting path**, not a
configuration flip: a registry read, new API-plane IAM, a latency cost, an availability coupling and
a defined behaviour when the read fails.

It ships before the move because it can only be **proved** before the move. While both sources exist the same user's
membership is knowable two ways and they must agree; in the successor account only one survives and
a wrong implementation is indistinguishable from a right one. That is SPEC-137's lesson — instrumented
code shipped whose layer attachment was missing while every gate was blind — and the parity
assertion (FR-006) is an assertion that **expires**, which is the argument for writing it while it
still can be.

The default stays `claims` through Arc B and every environment omits the variable. No user can
observe this spec.

### The decision 203 took, and the one it reversed under review

`transition_plan.md` said "compute the tags from the registry", which reads as *enumerate the user's
spaces*. **The registry cannot answer that cheaply** — one object per space, keyed by space name, no
per-user index, so enumeration is a full listing plus a read per space on every credential mint. So
203 builds the index that can: one object per user in the **admin bucket**, written by the same
fan-out that already writes the roster, at the same consistency point. SPEC-123's runs index and
SPEC-146's username directory are the precedents — CAS, user-unreachable.

**Its first draft avoided the index and was wrong, and the reason is worth carrying.** That draft
scoped the tags to *the spaces a request names* — bounded cost, least privilege, no new artifact.
It cannot work: SPEC-199's query route takes `{sql, database?}` and SPEC-077 makes every base table
fully qualified, so `SELECT * FROM finance_space.sales` names **no space and no database** anywhere
the API can see — and SPEC-199 Premise 2 makes the SQL opaque to the API by design, so the API may
not go looking. Every shared-space query would have failed. SPEC-198's `copy` route names *two*
spaces, which the rule also mishandled. Enumeration is required; the index is what makes it one
`GetObject`.

**The trap it names as a sweep rather than a review note**: there IS an object listing a user's
spaces, one `GetObject` away, keyed by username — `{username}/user_settings/shared-connections.json`.
It is in the user's own prefix and the user can write it (verified: `PutObject` on
`${bucket_arn}/${aws:PrincipalTag/username}/*`, no Deny under `user_settings/`, hidden client-side
only). Reading it would be a complete authorization bypass through a file the product invites the
user to own. That is the whole reason the index lives in the admin bucket.

**And 203 inverts a SPEC-146 rule deliberately.** The username directory is *advisory* — a tripwire
test forbids it being an authorization input. This index decides what a session may reach. Three
properties carry that: user-unreachable, written only by the plane that owns membership, written
under CAS at the registry's own consistency point. The residual is a staleness window, and it is
**smaller than the one it replaces** — `clear_slot` clears a Cognito attribute but the user's
existing token keeps the old claim until it refreshes, which is what
`useSharedSpaceAccessRecovery` exists to paper over. The sweep in `transition_plan.md` §3.11
closes it.

> **SPEC-203 IS COMPLETE (2026-08-31), and five of its own claims were wrong.** The index, its six
> writers and the `MEMBERSHIP_SOURCE` seam all shipped; the default is `claims` and the variable is
> in no Terraform, so nothing a user can see changed. What the build corrected, in the spec file and
> in [`decisions/identity-and-access.md`](../decisions/identity-and-access.md): FR-008's "no
> `ListBucket`, and that is the load-bearing half" **cannot stand beside FR-003** — S3 answers
> `NoSuchKey` only to a caller that can list, so a read-only grant makes an *absent* index arrive as
> a denial for every user in no shared space, and the settled remedy is a `s3:prefix`-conditioned
> grant. FR-003's "cached with the credentials under the existing key" is **not constructible**: that
> key is the tag set the read produces. FR-004's literal zero-AWS-calls refusal is **not satisfiable**
> under `index`; what is preserved is that the refusal itself reaches no service. FR-001 reasoned
> about a delete from the post-SPEC-205 world, where the record survives — today `reg.delete` frees
> the name, so the drops ride the member loop before it, in `forget`'s teardown path as well as
> `delete`'s. And Premise 4 — "a space name reaching a key builder has been through
> `CATALOG_IDENTIFIER_RE`" — **was not true when it was written**; `_from_index` makes it true on
> that path only, because a tag value of `*` is a wildcard grant and the claims source cannot check
> it without rewriting the equivalence it exists to preserve.
>
> **FR-007's live parity check is OWED and expires** — it needs an environment running
> `MEMBERSHIP_SOURCE=index`, and there is none. [`owed.md`](../testing/owed.md) carries the recipe
> and the caveat that it cannot be re-run after the environment moves.

### What 204 was, why it was cancelled, and what validating it found

204 specified the projection: once the tags retire, a member's access becomes **two grants** — an S3
Access Grant on the space prefix and a Lake Formation grant on the space database, per (member,
space), against the member's Identity Center principal — issued at six triggers, converged by a sweep
that must **revoke**, and cut over in an order with a wrong answer in both directions.

**It was cancelled on 2026-09-01 and the design is now `transition_plan.md` §3.11.** The reason is a
rule rather than a judgement about the work: it could not be built or tested in the current account —
it needs the Access Grants instance, the Identity Center association and an identity-enhanced session
— and a spec nobody can build is a spec whose claims drift with nothing to catch them. It had already
started to: last revised 2026-08-28, while 203 and 205 both completed on 08-31.

**Validating it on the way out is what makes the cancellation worth reading.** Two of its claims were
confirmed against the code and one was wrong:

- **Confirmed — the privilege-escalation finding.** Reusing the role's `DATABASE_PERMISSIONS` for a
  member would make `DROP` and `ALTER` on the Database live, because the only thing withholding them
  today is that **no** portal-role template grants `glue:DeleteDatabase` or `glue:UpdateDatabase`.
- **Confirmed — the cliff.** `shared-space-create` grants Lake Formation `Database` and `Table` to the
  **shared portal role** for every space, and the `$${aws:PrincipalTag/shared_space_k}` expansion in
  `portal-role-shared-space.json.tftpl` is the whole of the isolation. Remove the tags and leave the
  grants and every portal user holds catalog access to every shared space; remove them first and every
  member is locked out. **The current-account half of that coupling is now guarded** by
  `lambdas/test_shared_space_isolation_coupling.py`, which fails when either artefact moves without
  the other — the one piece of 204 that could be built here, and the one that expires once the
  environment moves.
- **Wrong — FR-011's delete semantics.** It said `delete_shared_prefix` and `drop_database` "stop
  being reachable on the `delete` route". They do not: `delete_space.py` branches on
  `reg.is_destroyable(fresh)` and on that branch calls them, plus `revoke_portal_role` and
  `reg.delete`, with `TeardownIncompleteError` reachable. The destroying route lives in `delete` as
  well as in `forget`, and §3.11 carries the corrected version.

**One thing 204 settled that the transition plan had open, and which survives in §3.11.** §3.9 asks
whether a storage entitlement is a literal per-user grant or one broad grant narrowed by
`${identitystore:UserId}` in the location role's policy. For **shared spaces the literal form is
forced**: a policy variable narrows by properties of the caller, and membership is a relation in our
registry that no IAM variable can consult. The two buckets may therefore use different forms, and the
personal-prefix decision does not have to wait for this one.

### 205 is not transition work, and it is what §3.11 is written against

`shared-space-delete` destroys a space: every object under its prefix, its Glue database, its Lake
Formation grants, its members' slots and its registry record. **SPEC-205 makes it remove people
instead of things** — every member's access ends, including the owner's, and the objects, the
database and the record survive with `status: "active"` and an empty roster.

**It ships independently of everything else here.** It needs no API, no Identity Center and no
Access Grants; it is a change to one verb and one registry write, and it stands on its own merits —
a deleted workspace becomes recoverable by an administrator, where today it is gone from a bucket
with versioning off.

**What it buys §3.11 is a whole failure class.** SPEC-151 exists because a partial teardown could
free a name while resources survived under it, and FR-011 was originally a teardown protocol
descending from that. On a route that releases no record the hazard is *unreachable*, so FR-011 is
three criteria and `TeardownIncompleteError` does not apply **on the emptying route**. It is
still reachable on the destroying one, which lives in `delete` as well as in `forget`.

**The seam is a durable field, and the obvious version of it was unsafe.** Retention keys on
`everActive`, stamped at `finalize` and never cleared — **not** on live `status`, which the first
draft used. `forget`'s owner path fires on `status != "active"`, meaning *any* non-active status, so
a delete that fails midway leaves a live workspace in `failed` and the Connections page's **Dismiss**
button would have destroyed it, while **Retry** — which calls `create` — would have revived it
through `_resolve_reserve_collision` with the roster reset to the owner alone. Both doors are closed
server-side, and the two buttons gain a failed-create/failed-delete distinction.

**The justification for the destroying route is narrower than it first read.** `create_space` assigns
the Cognito slot — which *is* the S3 grant — before `finalize`, so a never-`active` space *can* hold
data; the "no user data by construction" claim is withdrawn. What is true and sufficient: such a
space was reachable only by its creator, and the route is that creator discarding their own failed
create.

**The detail that looks cosmetic and is an authorization boundary:** the `owner` field is cleared
with the members. `shared-space-common/auth.py`'s `authorize` gates every owner-only action on
`actor != registry.get("owner")` — the field, never the roster — so an `owner` retained through a
delete leaves the original owner able to `add-members` on the emptied space and revive it in one
call, with the previous cohort's files intact and no confirmation. The previous owner survives as
`previousOwner`, which no authorization path reads, so an operator can still restore it. The
inert-state test is driven **as the original owner**, because as a stranger it passes over the
defect.

**Two user-visible costs, both stated rather than discovered.** A name any space once used can never
be claimed again — the record is the name lock and it is never released. And data a user asked to
delete is retained; the wording stays "delete" because from every user's view the space is gone, but
no copy anywhere may claim the data was destroyed, which is what FR-006's sweep enforces.

## Container-lambdas arc (SPEC-212 → 213 → 214)

Eighty-six functions, ten layers, two JSON tables and a literal attach-order loop. The arrangement
works. What is wrong with it is that **what a function can import is decided at deploy time, by a
join between two tables, and is observable nowhere else** — so a missing layer is a
`ModuleNotFoundError` at the next cold start, in production, behind a green suite. That is not
hypothetical: SPEC-137 shipped instrumented code that passed review, the unit tests and
`update-function-code`, then failed at every cold start and broke sign-up for nine days. Every gate
was blind because none of them ran the deployed artifact.

The arc replaces the join with an artifact. One image, dependencies installed once, shared code
copied once, every function running the same image with a different command. What a function can
import becomes a property of something you can pull and run — which is exactly what the arc's
central test does.

### Why it is three specs, and why this order

The three specs have three different risk profiles, and mixing them would give the whole arc the
worst of them.

**212 cannot break production.** It builds the image, proves it, pushes it to ECR and deploys it
nowhere. At the end of it not one `aws_lambda_function` has changed. This is where the import smoke
test is built — the check that runs every function's handler import inside the real image — and
building it before anything depends on it is what makes the rest of the arc a packaging change
rather than a leap.

**213 was where the risk was, and it had a known shape.** Terraform keeps owning the function and CI
keeps owning the code, so `image_uri` carries `ignore_changes`, so **CI must point every function at
the new image on every deploy.** A pipeline that builds and pushes and never calls
`update-function-code` leaves every function on the previous image and each of them keeps
working. Nothing goes red. This is not a new lesson: SPEC-193/194 hit exactly this with the SPA's
ECS service, where a pipeline that only registered a task-definition revision left a
`CannotPullContainerError` indistinguishable from the endpoint failure the platform was tested for.
The mitigation is the same one — CI points every function, reconciles by name, waits for each update
to settle, and fails loudly on a shortfall.

> **Shipped, and the risk that actually bit was one layer down.** `package_type` is ForceNew, so the
> cutover destroyed and recreated all 86 — and the thing that would have taken production out was
> not the replacement but the eleven `aws_lambda_permission` resources that would **not** have
> re-planned alongside it. See `decisions/infrastructure.md` → *A ForceNew packaging change is a
> rename in state plus 86 replacements*. Two other lessons are worth carrying into 214: a `moved`
> block whose `from` is not in state is tolerated **silently**, and the runtime interface emulator
> diverges from Lambda on the init-failure path, so it cannot settle a question about what a failed
> container logs.

**214's risk was the mirror image: a deletion, where the danger is a guard nobody misses.**
Its surface grew slightly when 213 removed `point-lambda.sh`'s zip branch: `deploy-lambda.sh` was
left called by nothing, while `lambdas/test_deploy_packaging.py` still extracted and RAN its copy
block — a suite pinning unreachable shell, green forever. Both were named in 214's In Scope and
both are deleted.
`lambdas/test_deploy_matrix.py` **was** the only thing standing between a missing layer and that
cold start — before 213, when layers still attached. Deleting it removes real protection unless something already replaced it, and a review will
not catch that — a reviewer reads what is there, and a deletion leaves nothing to read. So 214 does
not begin with a deletion. It began with a sweep that enumerated every function, every assertion
the matrix makes, and what now covers each one, printed before anything was removed. Three counts —
functions the image matrix imports, functions Terraform declares, function directories on disk —
are asserted equal.

**How it finished.** The 923 published layer versions were destroyed in CI and proved gone
account-wide, and the deploy role's layer grants came off in the apply after — that order forced,
since a grant removed first strands the versions with no identity able to reach them. Three fences
came out of it, each recorded in `docs/decisions/infrastructure.md`: Terraform named only eight of
the ten layers, so the enumeration could not be derived from it; **absence is zero versions, not an
exception**, measured against the live API rather than inferred from its documentation; and a sweep
of the wrong names deletes nothing while looking identical to a completed one, so the destroy
carried the count its own report found and refused a non-positive one.

### What the arc does not do

It does **not** merge the domain layers' source. `cpcommon` owns the algorithm and each domain layer
owns its wording, and `docs/decisions/` says do not merge them; an image that copies them into one
directory changes nothing about that. It does not convert `shared-space-common` from flat modules
into a package, which would be a refactor of every import in that plane. And it changes no
function's behaviour, environment, timeout, memory or role — 213 asserts that claim against a
fixture captured from the pre-cutover plan, rather than making it in prose.

### The one thing the arc makes worse, stated rather than glossed

A function used to be able to import only the layers attached to it. **Since 213 every function can
import everything** — including `shared-space-common`'s ten flat top-level modules, whose names (`config`,
`auth`, `registry`, `cache`, `notify`, `messages`, `membership`, `membership_index`, `casio`,
`teardown`) are generic enough to be imported from another plane by accident and would resolve. The image gives every
function a strictly larger import surface than its zip has. What keeps that from mattering is an AST
sweep, not the packaging — and the sweep has to count attribute-style usage (`import x` then
`x.y()`), because a submodule-path scan alone undercounts consumers.

### Its relationship to SPEC-215

214 moved CI's function list off a hand-maintained JSON file and onto the Terraform sources,
which is the same move SPEC-215 makes for the configuration values — the same idea arriving twice:
**a value Terraform computes is consumed from Terraform, not copied by a human into a settings page
or a JSON file.**

**They are order-independent, not independent**, and the distinction matters because an earlier
draft of this paragraph said the looser thing while both spec bodies described a coupling. Either
order works and each spec stated its own obligation for both. **What actually happened is neither
branch as written, and it is worth recording because the obligation was phrased around a read that
turned out to be the wrong one.** 215 landed first, but `deploy-lambdas.yml` does not go through
its `resolve-config.sh`: that resolver serves the configuration DOCUMENT, and the fleet is a
different read. The workflow shards over the commit's own `lambdas/fleet.py --plan` — deliberately
not a `tofu output`, which is last-applied state and would miss a function the same push adds — and
reads `tofu output -json lambda_function_names` only in the reconciliation, behind its own pinned
`tofu_version: '~1.8'`. So it joins 215 FR-001's version agreement on the predicate that spec
settled (*declares an OpenTofu version*, not *runs the resolver*), and adds the read directly. The one thing that
had to be settled between them is the predicate SPEC-215's version-agreement test derives — it is
*declares an OpenTofu version*, not *runs `tofu init`*, because a workflow using the resolver runs no
init of its own and an init-based predicate would exclude the very workflow the derivation was
widened to cover.

