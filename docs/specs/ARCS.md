# Spec Arcs — narrative context

Why each arc exists and how its specs fit together. **Pulled on demand**, not at session start —
`INDEX.md` carries status, this file carries reasoning. Most arcs below are shipped; their
authoritative detail lives in `docs/spec-delivery/SPEC-XXX-*.md` and the per-arc architecture docs.

**Arcs** — one `##` per arc; read only the one you're in:

- File-operations arc (SPEC-015 → 020, + 039 copy — shipped)
- Analytics arc (SPEC-032 → 036 — shipped)
- Query-editor UX follow-ups (SPEC-040 → 042 — shipped)
- Query-editor UX, round 2 (SPEC-043 → 044, + 041 amend — shipped)
- Query-editor UX, round 3 (SPEC-046 → 049, one-offs — shipped)
- Shared-connections arc (SPEC-050 + 056 → 055 — shipped)
- Notifications arc (SPEC-058 → 061 — shipped)
- Control-plane refactor (SPEC-062, standalone — shipped)
- Query-editor UX, round 4 (SPEC-063 → 065, user-feedback one-offs — shipped)
- Create-Table-from-Files / "Table Builder" arc (SPEC-066 → 071, + 072 producer — shipped)
- Query-editor UX, round 5 + file-browser one-off (SPEC-077 → 080, + 081 — shipped)
- Table-Share arc (SPEC-088 → 093, + 094 producer — shipped)
- App-shell / schema-rail UX one-offs (SPEC-085, 086 — shipped)
- Best-practice audit follow-ups (SPEC-082 → 084 — shipped)
- Responsive & Files-UX arc (SPEC-095 → 104 — shipped)
- Control-plane-common prerequisite (SPEC-107 — shipped)
- File-converter arc (SPEC-115 → 122 — cancelled)
- Data-quality arc (SPEC-108 → 114, + 123 → 124 — shipped)
- Observability arc (SPEC-127 → 137, fleet-complete)
- Refresh-table arc (SPEC-143 → 144 → **149** → 145 — active; 143 and 144 COMPLETE)
- Username-directory arc (SPEC-146 → 147 → 148 — shipped)

---

## File-operations arc (SPEC-015 → 020, + 039 copy — shipped)

Turns the read-only browser into a filesystem:
download, upload, create-folder, metadata, delete, move, rename, large-file upload, copy. All
build on SPEC-013 (authenticated user-space bucket). Move/rename = copy-then-delete; copy (039)
reuses the same `copyObject` minus the delete (additive, same-folder auto-suffix). Folder ops are
recursive + non-atomic. See architecture.md Known Constraints.

---

## Analytics arc (SPEC-032 → 036 — shipped)

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

---

## Query-editor UX follow-ups (SPEC-040 → 042 — shipped)

Refines the SPEC-035/036 workspace without touching the data
layer or IAM: 040 persists the un-run editor draft across tab switches/reloads (`sessionStorage`,
per-user) and adds a **Clear** button; 041 turns the editor into **query tabs** (`Query N`, monotonic
labels, closable-with-confirm, per-tab persisted text) and supersedes 040's single-draft storage;
042 paginates the history drawer (7/page, Prev/Next, newest-first, client-side). 041 needs a design
pass (new tab strip in `query-workspace.html` + §6) before code.

---

## Query-editor UX, round 2 (SPEC-043 → 044, + 041 amend — shipped)

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

## Query-editor UX, round 3 (SPEC-046 → 049, one-offs — shipped)

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
> text above as history; full entry in `docs/decisions.md`.

---

## Shared-connections arc (SPEC-050 + 056 → 055 — shipped)

Bucket 2 (`dat-prod-shared-space`): user-created, uniquely-named,
non-renameable shared connections (name = shared S3 prefix = shared Glue DB), provisioned by an async
**SQS → EventBridge Pipe → Step Function** pipeline (validate → create → update permissions). Access is
gated by a **membership principal tag** on the shared role (10 bounded Cognito attribute slots; LF grants
the role per shared DB, IAM tag is the gate — same shape as the personal `username`-tag model). Source of
truth = an **S3 control-object registry** in the analytics admin bucket (`shared-spaces/` prefix,
pipeline-only); each user's `{username}/user_settings/shared-connections.json` is a UI **cache** the pipeline
writes (pending/active/failed status). Shared-DB query results route to the shared prefix. Decision record:
`docs/architecture.md` → *Control Planes → Shared Spaces* (reverses the "no backend" decision for shared-space mutations only).
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

## Notifications arc (SPEC-058 → 061 — shipped)

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

## Control-plane refactor (SPEC-062, standalone — shipped)

The shared-space control plane shipped (050→054) as a **single
711-line provisioner Lambda** with an `action`-switch (create/add_members/remove_members/leave/delete) + inline JWT
verify + all helpers, under one broad orchestrator role. SPEC-062 decomposes it to the architecture's original intent
(§7 "provisioning Lambda(s)"): the **Step Function orchestrates single-task Lambdas** — `entry → validate-authorize →
Choice(action) → <verb Lambda> → success/failure` (Retry/Catch in the state machine), one Lambda per verb, shared
code (auth/registry/clients/cache/notify) in a common module/layer, and **per-verb least-privilege roles** replacing
the monolith role. **Behavior, the request contract (056), the membership-tag model, and registry/cache shapes are
unchanged** — structure only — plus two clarifications: **create stays creator-only** (no member-add at create; adds go
through 053 from the Connections tab), and each verb **emits its SPEC-061 notifications inline** via the shared helper.
The old provisioner function/role/tests are removed at cutover. Follows `docs/best-practices/lambdas/lambdas.md`;
decision recorded in `docs/architecture.md` → *Control Planes → Shared Spaces*.

> **The per-verb least-privilege roles were descoped (user decision, SPEC-062 FR-005):** every verb runs on **one
> shared orchestrator role**. Read the roles claim above as history; full entry in `docs/decisions.md` → *Bucket 2
> (shared-space)*.

---

## Query-editor UX, round 4 (SPEC-063 → 065, user-feedback one-offs — shipped)

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
> fully-qualified `database.table` names. Read the active-DB references as history; full entry in `docs/decisions.md`.

---

## Create-Table-from-Files / "Table Builder" arc (SPEC-066 → 071, + 072 producer — shipped)

A new
**dedicated** async control plane (its own FIFO **SQS → EventBridge Pipe → Step Function**, **single-task Lambdas**
with per-verb least-privilege roles) that turns a folder of data files into a Glue/Athena **external table** in the
database the space maps to (personal = username; shared = space name). Decision record:
`docs/architecture.md` → *Control Planes → Table Builder* (read first). Reuses the **pattern** of the shared-spaces control plane
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
> on **one shared execution role**. Full entry: `docs/decisions.md` → *Table Builder (SPEC-066→072)*.

---

## Query-editor UX, round 5 + file-browser one-off (SPEC-077 → 080, + 081 — shipped)

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

## Table-Share arc (SPEC-088 → 093, + 094 producer — shipped)

Filed 2026-07-04; "**share a table** across databases." From the Query schema rail, a user shares any accessible table to one or more **users** and/or **shared spaces**: the data files are **copied** into each recipient's space under `shared_tables/{table}/` and a table of a chosen name is **created** over the copy in the recipient DB. A **new dedicated** async control plane (its own FIFO **SQS+DLQ → EventBridge Pipe → Standard Step Function**, single-task Lambdas + a **`table-share-common` (`tscommon`)** layer, **one shared execution role that is an LF admin**) mirrors the table-builder/shared-spaces pattern (reuses the pattern, not the resources). The SFN: **validate-authorize** (ID-token actor; actor must have **source** access — personal = own DB, shared = active member) → **inspect-source** (`GetTable`, **clone the source table definition**; reject views / catalog-partitioned / non-external; list objects; enforce object/size caps) → **`Map` over recipients** (per-item Catch): **check-target-absent** (fail that recipient on name conflict / non-empty prefix) → **copy-objects** (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → **create-table** (clone def, repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Decisions (2026-07-04):** push (no consent; recipient notified), clone-not-infer (format-agnostic), parallel `CopyObject` (Batch Ops deferred), **any space is a valid target** (source access still gated), conflict = **fail that recipient only** (no overwrite), v1 sources = **flat or projection-partitioned** base external tables. Build order 088→…→093; **094** (notifications: actor per-recipient outcome + recipient "shared with you") after SPEC-058 + the verb Lambdas. Decision record: `docs/architecture.md` → *Control Planes → Table Share* (read first). New infra: `infra/modules/table-share/`; new browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`.

> **Superseded in part by SPEC-160 (2026-08-10):** "parallel `CopyObject` (Batch Ops deferred)" no
> longer describes the plan. **S3 Batch Operations is rejected, not deferred** — its Copy cannot
> rewrite a key (`TargetKeyPrefix` prepends the full source key) and it caps objects at 5 GB. The
> scale path is a top-level **Step Functions Distributed Map** over a flat `(recipient × object)`
> manifest, running the same copy code. Full entry: `decisions.md` → *Table Share*.

> **"An LF admin" is history in one load-bearing way (SPEC-111 correction):** admin status does **not** confer
> `CREATE_TABLE` — table creation rides the `portal-managed` LF-Tag (TBAC). Full entry: `docs/decisions.md` →
> *Control-plane table creation = TBAC*.

---

## App-shell / schema-rail UX one-offs (SPEC-085, 086 — shipped)

Filed 2026-07-02, both presentation-only (no data-layer/IAM/infra).
**085** adds a **collapsible side nav**: the Files spaces `Sidebar` and the Query `SchemaBrowser` share the same 248px rail
chrome, so it's factored into one **`CollapsibleRail`** base component with a collapse control; collapsed = **fully hidden +
a reopen handle** (not a slim icon rail), and the state is **persisted per browser in `localStorage` under one shared key**
so the choice carries across both rails. Below-`tablet` behavior (rail hidden) and the top-bar tabs are untouched. **086** adds a
**per-database Refresh** control to each schema-rail `DatabaseNode` (SPEC-063) that re-reads only that database's tables/views
(`queryKeys.schema(database)` invalidate/refetch via the existing `useSchema`/`invalidateSchema`) — manual, per-node, error
non-destructive; mirrors the SPEC-046 history-refresh pattern. Both are independent of each other and of everything else.

---

## Best-practice audit follow-ups (SPEC-082 → 084 — shipped)

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

## Responsive & Files-UX arc (SPEC-095 → 104 — shipped)

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

## Control-plane-common prerequisite (SPEC-107 — shipped)

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

## Data-quality arc (SPEC-108 → 114, + 123 → 124 — shipped)

**Data-quality arc (108 → 114)** and **file-converter arc (115 → 121)** — filed 2026-07-11 from
their architecture decision records (data-quality since folded into `docs/architecture.md` → *Control Planes → Data Quality*; the file-converter record and the 2026-07-11 review doc are removed), both **re-architected (v3)** after that review **and** the 250 GB source-file requirement. Two **independent** dedicated async control
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
> creation rides the `portal-managed` LF-Tag (TBAC). Full entry: `docs/decisions.md` → *Control-plane table
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
**Note:** the shipped notifications pipeline is *not* a safe model to copy — see `docs/security-baseline.md` →
*Design finding — notifications `create` spoofing* (real, shipped, low-severity, tracked there). SPEC-122 is **additive and
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

## Observability arc (SPEC-127 → 137, fleet-complete)

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
> history; `decisions.md` and `spec-delivery/SPEC-129` carry the current shape. Delivery is a **pull, not a push**, for the reason
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

## Refresh-table arc (SPEC-143 → 144 → **149** → 145 — active; 143 and 144 COMPLETE)

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
> last-write-wins between two definitions instead of one run seeing no table. See `decisions.md` → *The refresh apply
> replaces the definition in place*.
>
> **Superseded by SPEC-157 (2026-08-09):** the overlap no longer survives. A per-table lock in the admin bucket,
> claimed under ETag CAS, serializes refresh outside Glue — the second run is refused with a notification rather
> than racing. Glue still offers no compare-and-set, which is *why* the lock exists. See `decisions.md` →
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

## Username-directory arc (SPEC-146 → 147 → 148 — shipped)

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
is deleted outright (§6.3) — while federated login makes `cognito:username` a synthetic `identitycenter_<subject>` value
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
> reached for. What survives is the reason there is no space *directory*: see `decisions.md`.

**Explicitly not built:** a shared-space directory, display names or emails (an email is not metadata under the field rule
and has no place in a document every authenticated user can read), server-side search, fuzzy matching, and any
authorization use. The all-users disclosure is **accepted and recorded** rather than left implicit: a username already *is*
the S3 prefix, the principal tag and the Glue database name (SPEC-033), it is already on every shared-space roster
(SPEC-075), and a prefix-search feature discloses the set by construction. Build order **146 → 147 → 148**; 146 ships as
two PRs; 147 and 148 add no IAM, no AWS resource and no env var — 147 derives the object's location from the existing
`userSpaceBucket()` helper, so the four-point `VITE_*` wiring dance is avoided across the whole arc.

## Audit-remediation arc (SPEC-150 → 156 — active, all Draft)

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

## Follow-ups from the shipped arcs (SPEC-157, 158 — filed 2026-08-05)

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

## Table-share-at-scale arc (SPEC-160 → 161 — filed 2026-08-10; **COMPLETE**)

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
> `docs/testing/table-share-e2e.md` → *SPEC-161*. What shipped:
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

## Feature-flags arc (SPEC-162 → 163 — filed 2026-08-10; **COMPLETE 2026-08-11**)

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
unhidden — the failure mode `process.md` records from `log-forge`'s SPEC-033. So the surfaces live in
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

## Send-files arc (SPEC-164 → 165 → 166 → 167 — filed 2026-08-10)

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

## Archival arc (SPEC-168 → 169 → 170 → 171 → 172 — filed 2026-08-10; 168 and 169 COMPLETE)

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

## Saved-queries-in-spaces arc (SPEC-173 → 174 → 175 — filed 2026-08-11)

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
