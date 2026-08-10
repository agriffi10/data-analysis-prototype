# Key Decisions — full register

The settled architectural decisions, in full. **Don't re-litigate these.** `CLAUDE.md` carries a
one-line digest of each; this file carries the reasoning, the constraints, and the explicit
"do NOT build" fences. Pull the entry you need — you rarely need them all.

When a spec settles a *new* decision: full entry here **first**, then one line in `CLAUDE.md`
(completion-ritual step 5) — the digest line is never the only home of a fact. One `###` heading per
entry, label matching the CLAUDE.md bold label, listed in the Contents. When a decision **reverses an
earlier one**, update the old entry in place *and* add a superseded marker (short blockquote) at every
other doc site still stating the old claim (`ARCS.md` arcs, architecture.md sections).

## Contents

- [Auth](#auth)
- [Hosted UI = Managed Login v2](#hosted-ui--managed-login-v2)
- [No backend](#no-backend)
- [State](#state)
- [File ops = filesystem UX](#file-ops--filesystem-ux)
- [Analytics (032→036)](#analytics-spec-032036)
- [Usernames](#usernames)
- [Query workspace has NO active database (077)](#query-workspace-has-no-active-database-spec-077)
- [Multi-statement scripts (078)](#multi-statement-scripts-spec-078)
- [Bucket 2 (shared-space)](#bucket-2-shared-space)
- [Member join status (073)](#member-join-status-spec-073)
- [Member roster for members (075)](#member-roster-for-members-spec-075)
- [Table Builder (066→072)](#table-builder-spec-066072)
- [Table Share (088→094)](#table-share-spec-088094)
- [Data-quality report view (113)](#data-quality-report-view-spec-113)
- [Data-quality outcome notifications (114)](#data-quality-outcome-notifications-spec-114)
- [Data-quality runs index + dashboard (123)](#data-quality-runs-index--dashboard-spec-123)
- [Control-plane DLQ drain → user notification (126)](#control-plane-dlq-drain--user-notification-spec-126)
- [Structured-logging pipe (127→129)](#structured-logging-pipe-spec-127129)
- [Structured-logging narrative primitives & the one-door rule (130/131)](#structured-logging-narrative-primitives--the-one-door-rule-spec-130131)
- [The field rule — what may be logged (130)](#the-field-rule--what-may-be-logged-spec-130)
- [Per-plane instrumentation rules (132→137)](#per-plane-instrumentation-rules-spec-132137)
- [Control-plane table creation = TBAC (070/111 correction)](#control-plane-table-creation--tbac-spec-070111-correction)
- [No ASL state decodes an error Cause (PR #252)](#no-asl-state-decodes-an-error-cause-pr-252-control-plane-wide)
- [IaC](#iac)
- [Dev-unauth path](#dev-unauth-path)
- [Notifications (058→061)](#notifications-spec-058061)
- [Responsive (095)](#responsive-spec-095)
- [Help & guides (074)](#help--guides-spec-074)
- [User-facing error messaging (106)](#user-facing-error-messaging-spec-106)
- [Security scanning (138)](#security-scanning-spec-138)
- [IAM policy scanning = the rendered plan, not the templates (139)](#iam-policy-scanning--the-rendered-plan-not-the-templates-spec-139)
- [Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)](#deploy-role-refresh-deadlock-has-an-in-repo-lever-skip_refresh)
- [Response headers / CSP (140)](#response-headers--csp-spec-140)
- [Static-asset caching = three prefix-scoped sync passes (141)](#static-asset-caching--three-prefix-scoped-sync-passes-spec-141)
- [The username directory is built from S3, not Cognito (146)](#the-username-directory-is-built-from-s3-not-cognito-spec-146)
- [Every authenticated user can read the username directory (146)](#every-authenticated-user-can-read-the-username-directory-spec-146)
- [Compiler and coverage defaults are declared, never inherited (150)](#compiler-and-coverage-defaults-are-declared-never-inherited-spec-150)
- [A partial teardown never frees the space name (151)](#a-partial-teardown-never-frees-the-space-name-spec-151)
- [Every DDL literal goes through `literal()` (151)](#every-ddl-literal-goes-through-literal-spec-151)

---

### Auth

Cognito User Pool → Identity Pool (ABAC) stamps the `username` principal tag from the verified token claim **server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)

### Hosted UI = Managed Login v2

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.

### No backend

Browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).

### State

TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)

### File ops = filesystem UX

Download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md Known Constraints.

### Analytics (SPEC-032→036)

In-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.

### Usernames

Usernames are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.

### Query workspace has NO active database (SPEC-077)

Supersedes SPEC-047/076. Database *selection* is removed entirely — no "current database" anywhere. Queries carry **no** `QueryExecutionContext.Database`, so every base table must be **fully-qualified `database.table`** (an unqualified name fails); this enables cross-database joins in one statement. The schema rail (`useConnections` seam) is **browse-only** (no radio/active); per-table actions (View DDL/data/Drop) take the DB from the rail node; Create view **derives** its target DB from the body's qualified tables; autocomplete (`useAllSchemas`) spans **all** accessible databases with fully-qualified suggestions. The rail no longer inserts into the editor (FR-004 dropped, user decision). Results always land in the personal prefix; shared save destinations stay a Save-time choice (SPEC-049/055).

### Multi-statement scripts (SPEC-078)

The editor splits `;`-separated statements client-side and runs them **sequentially, stop-on-first-failure**, one history entry each; three run scopes — **Run Statement** (⌘⏎, selection/cursor), **Run Script single-result** (⌘⇧⏎), **Run Script tab-per-statement** (⌘⌥⏎, ephemeral per-run **result tabs**; DDL/DML earn none). No transactions (Athena has none); statements never run in parallel. Detail: SPEC-078 + delivery doc.

### Bucket 2 (shared-space)

User-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`) sharing a **`shared-space-common` Lambda layer** — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). The six Lambdas + the Step Function keep **one shared `orchestrator` role** (per-verb roles were descoped — user decision, SPEC-062 FR-005); the layer is CI-built/published (deploy-lambdas) with TF `ignore_changes=[layers]`. **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `docs/architecture.md` → *Control Planes → Shared Spaces*; Lambda rules: `docs/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.

### Member join status (SPEC-073)

The owner projection carries a per-member `pending`/`active` chip. Membership stays `members: string[]` (source of truth in the registry); join status is a separate `acknowledged: string[]` list — a legacy record without it reads as all-active (back-compat). A **seventh verb `acknowledge-membership`** (member-only, idempotent, same shared `orchestrator` role) flips pending→active; the browser enqueues it once/session when a member resolves a shared space (`useAcknowledgeMembership` from `FilesPage`). Display + bookkeeping only — access is still granted at add time.

### Member roster for members (SPEC-075)

SPEC-053's member-privacy stance is **reversed** — every member sees a **read-only** roster (owner tagged + first, same `Member[]` join-status projection the owner sees), via "View members" on their Connections card. `cache.write_roster_to_all` fans the roster out to the owner + every member on add/remove/leave (best-effort per member, CAS-safe); member entries now carry `members` too. No management power for non-owners; no new IAM (orchestrator already writes every user's cache). Legacy member entries backfill on the next membership change.

### Table Builder (SPEC-066→072)

"Create a Glue/Athena table from a folder of files" via a **dedicated** async control plane (its own FIFO SQS → EventBridge Pipe → **linear** Step Function → five single-task verb Lambdas `validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl`) sharing **one execution role** (all five verbs; consolidated from the SPEC-066 per-verb roles — user decision, mirroring shared-spaces) + a CI-built `table-builder-common` (`tbcommon` package) layer + a CI-built `polars` layer (infer-schema only). **Partitions:** keys are **user-declared in the modal in granularity order** (Hive `key=value/`, never auto-detected), exposed via **Athena partition projection** (no `MSCK REPAIR`); per-key type+range collected in the modal. **CSV is not type-inferred** (all-string, OpenCSVSerde); Parquet/JSON infer + parse dates. **The shared execution role creates tables via the `portal-managed` LF-Tag (TBAC), NOT via LF-admin status** (SPEC-070/111 correction — LF *admin* alone does NOT grant CREATE_TABLE; target DBs are dynamic per-user/per-shared-space so are tagged at provision time and the role is granted on the tag + a static per-bucket DATA_LOCATION_ACCESS; see the Control-plane TBAC decision below; IAM otherwise scoped, delete denied). Any **unexpected (non-Terminal/non-Transient) verb error notifies the actor** via `tbcommon.notify.notifies_on_failure` (no more silent failures); SFN terminal states record `{…, status: created|failed, reason}` (the outcome SPEC-072 notifies from). Decision record: `docs/architecture.md` → *Control Planes → Table Builder*. Do NOT build MSCK-based partition loading or auto-detect partition keys.

### Table Share (SPEC-088→094)

**COMPLETE:** "share a table across databases" — from the Query schema rail, copy a table's data files into recipient spaces under `shared_tables/{table}/` and create a clone table in each recipient DB (personal users and/or shared spaces). Its own **dedicated** async control plane (FIFO SQS+DLQ → Pipe → Standard SFN with a recipient `Map`, single-task Lambdas + `table-share-common`/`tscommon` layer, **one shared execution role** — creates tables via the `portal-managed` LF-Tag, not LF-admin status; SPEC-070/111 correction). SFN: validate-authorize (actor must have **source** access — personal=own DB, shared=active member) → inspect-source (**clone the source Glue table definition**, not re-infer; reject views/catalog-partitioned/non-external; cap object count+size) → Map(recipient): check-target-absent (fail-that-recipient on conflict, no overwrite) → copy-objects (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → create-table (repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Push** (no consent; recipient notified); **any shared space is a valid target** (sender needn't be a member — source access still gated); v1 sources = flat or projection-partitioned base external tables. UI = schema-rail per-table **"Share table"** (`features/table-share/` dialog + `useTableShare`, SPEC-093); **outcomes = SPEC-058 notifications** (sender per-recipient success/failure + whole-request failure; on success the recipient user / space **owner** is also told — `tscommon.notify`/`messages`, best-effort, `sqs:SendMessage` on the notifications queue only, SPEC-094). New browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`. Decision record: `docs/architecture.md` → *Control Planes → Table Share*. Do NOT build a consent/accept flow, schema re-inference, or catalog-partition-metadata copy in v1.

> **Amended (SPEC-160, 2026-08-10) — S3 Batch Operations is REJECTED, not deferred.** The original fence read "do NOT build … S3 Batch Ops … in v1", which recorded it as the scale path to reach for later. It is not one. Its Copy operation **cannot rewrite a key**: `TargetKeyPrefix` prepends to the *full* source key, so a job can only ever produce `bob/shared_tables/sales/alice/tables/sales/year=2024/part-0.parquet` — the sender's own prefix layout echoed inside the recipient's space, with the clone's `LOCATION` pointed at a path naming the sender's directory structure. It also caps objects at **5 GB**, where `tscommon.copy` already handles more via `UploadPartCopy`, and one job writes to exactly one destination bucket while recipients span two. The scale path is a **top-level Step Functions Distributed Map** over a flat `(recipient × object)` JSONL manifest in the admin bucket, running the existing copy code unchanged (SPEC-160), with the engine on `cpcommon.transfer` because the send-files plane (SPEC-164→167) is its second caller. **Do not re-propose Batch Ops** — the refusal is a property of the API, not of the current implementation.

### Data-quality report view (SPEC-113)

The report is read at `/data-quality/:space/:requestId` — **the space is in the route, not derived**, because `requestId` alone cannot say which space holds `{space}/_data-quality-reports/{requestId}/report.json`. Resolution precedence: the actor's **own username always wins**; shared-space names are consulted only when the segment differs (SPEC-114's link builder pins the same rule). An unreachable space renders the friendly denied state and **issues no S3 request** — no existence oracle. The SPA's report types mirror `dqcommon/report.py` byte-for-byte; the banner **warns on `hasIncompleteFigures`** and only softly qualifies on `hasApproximateFigures`, which is true on every report the arc can produce. Detail: `spec-delivery/SPEC-113`.

### Data-quality outcome notifications (SPEC-114)

The notification **is** the completion channel — the browser never waits and the reports folder is hidden from the file browser, so a success message without a **link to `/data-quality/{space}/{requestId}`** would leave the report unreachable. The link builder mirrors SPEC-113's resolution precedence and returns **nothing** where the view would resolve the wrong space (a shared space named like the actor, a personal space that isn't theirs) — no link beats a permanent not-found. **Every figure this arc produces is approximate**, so a flat "some figures are estimates" rides every success message and the real warning is reserved for `hasIncompleteFigures`, the flag that varies. Failure covers three layers: `@notifies_on_failure` on every verb, the `NotifyFailure` state for what no verb can catch (import/SFN-level errors, decoded in Python — never in ASL), and **SPEC-126** for what never starts an execution at all. **One dedup token per outcome, not per verb** (`{requestId}:failure` / `:completed`): `NotifyFailure` runs after the execution has left the failing verb and cannot know which one raised, so a per-verb token would send two messages for one failure; the collapse relies on SQS FIFO's 5-minute window. `TerminalError` gained an optional **`tokens`** mapping — the user-facing inverse of `detail`, which stays raw and operator-only. **FR-005's CloudWatch alarms were removed, not deferred** (user decision): an alarm with no target, on one arc of five, told the user nothing. Detail: `spec-delivery/SPEC-114`.

### Data-quality runs index + dashboard (SPEC-123)

The `/data-quality` list is backed by a per-space **`index.json`**, not by listing the reports prefix — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives NO chronology, and building rows from the reports themselves costs one GET per row and gets slower the more the feature is used. `assemble-report` appends one small entry (the row's fields and nothing else) under **optimistic ETag CAS** with bounded retry, because checks of DIFFERENT locations run in parallel (the queue serializes only same-location checks) — the same lost-update fix SPEC-082 applied to the registry. It was duplicated in `dqcommon` because `casio` sat in a layer the data-quality functions don't attach (**SPEC-125 did NOT merge it** — it folded the shared *client/config/JWT/notify* surface onto `cpcommon` and deliberately left the CAS retry loop domain-side).

> **Superseded (SPEC-156 FR-001, 2026-08-07) — the duplication ONLY.** The loop and the 409 predicate live in `cpcommon.cas`, which every data-quality verb already attaches; `DQ_INDEX_CAS_RETRIES` is gone and the cap is one value (6) for all callers. The twin had drifted before anyone merged it, which is this paragraph's real lesson. Everything below is unchanged and still live.

The index is **capped at 200, oldest dropped first**, and every failure is **logged and swallowed**: the report is the artefact, the index is a convenience, so write order is report → notification → index, most durable to least. The page **aggregates across spaces** (this is "my checks", not "checks in one folder") and one unreadable space is skipped rather than blanking it. It lists **completed checks only**, and the footer line saying failures live in notifications was worded **"usually"** until **SPEC-126** closed the never-started-an-execution hole; it now says **"always"**. No new IAM. Detail: `spec-delivery/SPEC-123`.

### Control-plane DLQ drain → user notification (SPEC-126)

Replaces SPEC-114 FR-005. Every control plane dead-letters a request it cannot process, and until this shipped the user was told **nothing at all** — no verb ran, so no `@notifies_on_failure` fired; no execution started, so no `NotifyFailure` state was reached. **One shared drain Lambda** (`lambdas/control-plane-dlq-drain/`, `infra/modules/control-plane-dlq-drain/`) sits on all four request DLQs (data-quality, table-builder, table-share, shared-spaces) and turns each dead-lettered message into one notification. Four things are load-bearing: (1) the recipient is the **verified `cognito:username` from the token inside the body** — a body-asserted `username` would let anyone route a notification to anyone; (2) **expiry is not enforced** on this path (`cpcommon.auth.verified_username_ignoring_expiry`, a **separately named** entry point, never a flag on the function every authorization path calls) because a dead-lettered message is old by construction while an ID token lives an hour — signature/issuer/audience still are, and this path **grants nothing**; (3) **no value from the untrusted body reaches the message** — every other producer interpolates what a verb already authorized, nothing here has authorized anything, and echoing an attacker-supplied path into a victim's inbox would make notifications a text-injection channel; (4) every per-message path is **total** — a throw means redelivery, and a message that always throws loops until retention expires, burning invocations on a failure nobody is watching, which is the invisibility this exists to end. The dead-lettered body is logged (**token redacted**) before the drain consumes it, trading the DLQ's 14-day copy for the log group's. The **notifications DLQ is deliberately undrained** and is the one hole this cannot close — the drain's only delivery channel is the queue that DLQ implies is broken; the honest answer there is operator-facing. **No redrive, no replay, no CloudWatch alarms** (an alarm with no target told the user nothing — the user decision that killed SPEC-114 FR-005). **Follow-up (2026-07-22): the four SQS event-source mappings became one EventBridge scheduled sweep** (`rate(10 minutes)`) — the mappings idle-long-polled four almost-always-empty DLQs around the clock, and that was the bulk of the account's SQS request volume (it was tripping the 1M/month free tier). The handler now polls all four DLQs itself (`DLQ_ARNS`, the same ARNs as an env JSON list) and **deletes every message it reads whether or not it could notify**, so "total by construction" now means *never redeliver* rather than *safe to be redelivered* — the redelivery-loop hazard in (4) is moot because nothing redelivers (the `_guarded_notify` belt stays, so one bad message can't abort the sweep). A resource-based `lambda:AddPermission` lets the rule invoke the function, so **no invoke role** is needed (unlike EventBridge Scheduler); the execution role is unchanged (it already held the four DLQ read/delete grants the mappings polled with). Cost fell from ~10⁵–10⁶ idle receives/month to a few thousand; the price is that a dead-lettered request surfaces within one interval (~10 min) rather than seconds, immaterial for a queue nothing watches live. Detail: `spec-delivery/SPEC-126`.

### Structured-logging pipe (SPEC-127→129)

The pipe every control-plane function logs through; it carried **boundaries only** until SPEC-130 added the narrative half (next entry). `log-foundry` (pinned **exactly**, core not `[aws]`) ships in the `cpcommon` layer. `LOGS_QUEUE_URL` is **optional** (`environ.get`, never `_require`) so a function missing it logs to stdout instead of crashing a whole plane at cold start. The logs queue is **FIFO** with `message_group_id` = the **service** (SPEC-129; it was standard only until `log-foundry` 0.5.0 could set `MessageGroupId`), with **no** content-based dedup (the library mints UUID dedup ids), and it is **swept** on a 10-min schedule, never long-polled (#270/#271). `service` = the **control plane**, and it is untrusted input on an S3 key: anything failing `^[a-z][a-z0-9-]{2,62}$` goes to `logs/_unrouted/`. Layout is `logs/service={s}/year=/month=/day=/data.jsonl` — **one appended object per service-day**, so every write is an **ETag-CAS read-modify-write** (a failed read must never overwrite a day) and the sweep role can **read** `logs/*`, reversing SPEC-127 FR-006. Delivery is put-then-delete (at-least-once; duplicates collapse on `log_id`). Partitions come from the **event's** timestamp. `logs/` is retained **forever**. `@traced` goes **outermost, above `@notifies_on_failure`**, or failed invocations close their span as `ok`. One run = **nine traces**, joined on `fields.request_id`.

### Structured-logging narrative primitives & the one-door rule (SPEC-130/131)

The pipe SPEC-127/128/129 built carries **boundaries only** (entry above), and SPEC-130 opens the door to the narrative half. `cpcommon.observability` gains `info`/`warning`/`error` and `step(name)` — the module's full surface is `init`/`flush`/`traced`/`step`/`stamp`/`info`/`warning`/`error` — and **nothing outside that module may import `log_foundry`**: an emitter sits in the middle of business logic where an exception is a real failure path, so the never-raise discipline needs one door rather than thirty-four. `step` is a **thin** alias for `lf.trace` and must stay one: the library decorator is non-swallowing, and `@traced` sits **outermost above `@notifies_on_failure`**, so a step that caught anything would cost the user their failure notification. Messages are **literals**, everything variable is a field (an f-string message mints a distinct string per run and can be neither counted nor filtered). The narrative **never reaches the console**: `echo=` is prohibited repo-wide and grep-tested, dropped-and-warned when passed as a field (with `**fields` it is otherwise a silent no-op emitting a field named `echo`); the one named exposure is `init`'s `StdoutSink` fallback when `LOGS_QUEUE_URL` is unset, which **stays** because it is the cold-start safety property the module is shaped around (PR #196) and is bounded by the `logging.getLogger()` calls already putting the same keys in the same log group.

Two identity defects fixed at the same time, because instrumenting on top of them would have multiplied the damage: `traced` now passes **`name=verb`** (without it `log-foundry` falls back to `fn.__qualname__` and every root span in the fleet read `function: "handler"`) — a **discontinuity in a store retained forever, accepted without migration** since rewriting appended NDJSON would risk a day of logs to save a `WHERE` clause, with `fields.verb` populated on both sides so a query spans the cutover; and **`verb` moved from a span default to baggage** (set after `_reset_baggage`, which clears the whole mapping), because a span default reaches that span's own events and nothing nested — the first `step` child would have carried `request_id` but not the verb that produced it. Consumers: SPEC-131 (sweep), 132 (data-quality), 133 (DLQ drain), 134→137 (the rest of the fleet).

**SPEC-131 added an eighth name, `stamp(**fields)`** (trace baggage), because the sweep needed an invocation-scoped join key on the boundary spans and the only alternative was importing `log_foundry` at a call site — the one-door rule survives by widening the door, not by excepting it; `_stamp_verb` and `_stamp_request_id` now delegate to it. **SPEC-131's own bound is structural:** the sweep emits into the queue it drains, so its event count is O(1) in messages and O(G) in day-groups (measured `6+4G`, 4 on an empty sweep) — a per-message emitter would give that queue a floor it could never get below, and the guard is a test that sweeps 20 then 200 messages over the same groups and demands an identical count. Its CloudWatch calls **stay alongside** the events, uniquely for that function: the sink is SQS-only, so a sweep that cannot write to S3 cannot report through the structured store that it could not write to S3. Detail: `spec-delivery/SPEC-130`, `spec-delivery/SPEC-131`.

### The field rule — what may be logged (SPEC-130)

**The line is drawn at file contents — not at user-derived data** (user decision, 2026-07-23): `logs/` lives in the admin bucket and is read by administrators, and that destination is what makes user-derived *metadata* the right thing to log — file names, S3 keys, prefixes, **usernames** (already the S3 prefix, the principal tag and the Glue DB name, SPEC-033), database/table/**column names**, space names, counts and durations are all permitted and encouraged, because an operator debugging a failed run needs to reach the object. **Absolutely never: data from inside a file** — a cell value, a sampled row, a result set, a decoded byte range — because it can be PII, it is never needed to debug a control plane, and `logs/` is retained forever (column *names* are schema and are in; column *values* are contents and are out). **Never regardless of provenance: tokens, credentials, email addresses** — a bearer credential is not metadata, and an email is the only personal contact detail that would exist in a forever-retained prefix. There is deliberately **no runtime redaction filter** and the module docstring says so: the rule turns on *provenance*, which no filter over a field name or value shape can see, and a filter that looked like enforcement would be worse than none because it would be trusted — enforcement is review plus per-call-site criteria.

**The no-file-contents rule is about FIELDS, and `error.stack` is an ACCEPTED exemption (user decision, 2026-07-23):** `log-foundry` attaches `traceback.format_exception` to every failed span unconditionally and it walks the `__cause__` chain, so a quoted cell (a polars parse error naming the value it could not convert) reaches `error.stack` regardless — suppressing `detail` does not help (see the per-plane entry below for the `detail` audit) and neither does fixing the raise site (`raise … from exc` is what puts it there). Rather than close it (an upstream `capture_stack=False`, or a strip in the sweep), the decision is to **accept it**: `logs/` is admin-only, and a stack is diagnostic metadata an admin debugging a failed run needs, so the absolute rule binds a **field a verb chooses to emit** — not an automatic traceback. **Do not read a stack trace as licence to relax the field rule.** The characterisation test (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`) is kept as a **tripwire, not deleted**: if it starts *failing*, `log-foundry` began stripping stacks and this decision should be revisited in the open.

**SPEC-137 put EMAIL on the never list** (user decision, 2026-07-23) in the shared module docstring: a username is not sensitive here (it IS the prefix, the tag and the DB name) but an address appears nowhere else, carries no operational meaning, and would be the only personal contact detail in a forever-retained prefix. The hazard is mechanical — a Cognito trigger event carries `request.userAttributes.email`, so **never log a raw event, an attributes map, or any dict you did not build field by field**; `pre-signup` logs the DOMAIN, which is what the rule turns on and is shared by every user of that provider.

### Per-plane instrumentation rules (SPEC-132→137)

**SPEC-132** spent the primitives on all nine data-quality verbs and settled two things the remaining planes inherit. **The `detail` audit is a deliverable, not a reassurance:** every `TerminalError` raise site is read, and any whose `detail` interpolates *parsed file content* logs the reason token and the exception type only — in data-quality that is `inspect-source`'s `_probe_columns` catch-all, whose detail carries a polars parse error that **quotes the offending cell**, and the suppression is unconditional for that verb rather than a denylist of reasons the next reason gets added without. And **a contents-shaped field NAME is banned even when the value is a count** — the tripwire caught `rows=` in `assemble-report` on its first run, so a row count is `row_count`; a field whose safety needs an argument is one whose name should say so instead. Failures are narrated **once per verb**, not per raise site.

**SPEC-133** took it to `control-plane-dlq-drain` (`service="dlq-drain"` — not a control plane, since it spans all four and is nobody's verb) and settled two rules the rollout inherits. **`request_id` is a FIELD wherever one invocation handles many requests, never baggage:** `_reset_baggage()` runs once per invocation, so on a function draining up to 400 messages, baggage would leak one request's id onto the next — the fabricated correlation key SPEC-128 FR-002 forbids. **And one event per item is right or wrong depending on which queue you emit INTO:** the sweep emits into the queue it drains, so per-message events give that queue an undrainable floor; the drain emits to the logs queue and drains the request DLQs, so per-message is correct there. The dead-lettered body is a **permanent forensic record** — redacted (every known token field), size-capped, and ONE serialized field, never re-parsed into fields or a body could shadow `request_id`/`verb`/`service`.

**SPEC-134** promoted the per-plane coverage guard to a **fleet-wide harness** in `control-plane-common`: registering a plane is one `Plane()` descriptor (its glob, service name, expected verb count as a LITERAL so a short enumeration fails rather than passing vacuously, and its decorator expectation), and a verb module is found by **defining a top-level `handler`** rather than by any filename convention. It also settled that **the decorator rule is per-plane and DECLARED**: shared-space verbs notify from inside the handler, so `@traced` is asserted to be their ONLY decorator — adding `notifies_on_failure` there later fails until someone establishes the ordering. And **per-item events are permitted where the bound is STRUCTURAL**: the roster fan-out emits per member because membership is capped at ten Cognito slots, which is the same rule as SPEC-131/133, not an exception to it.

**SPEC-135→137 finished the fleet.** 135 logs Athena's `StateChangeReason` **verbatim** alongside the stable token — that raw text is what would have named the missing `CREATE_TABLE` grant, and a token cannot carry a diagnosis — and moved the DDL poll's transition-only narrative into **`cpcommon.athena`**, since the loop is shared. 137's email decision lives in the field-rule entry above; 137 also verified empirically that **`cpcommon.observability` imports and emits with ZERO env vars** (`cpcommon/__init__.py` has no imports, `clients` lazy-imports boto3), which is what makes the layer safe to attach to functions that lack the six `config._require` variables — one `from cpcommon import config` added to `__init__.py` would arm PR #196's bomb for them. Detail: `spec-delivery/SPEC-132`, `spec-delivery/SPEC-133`.

### Control-plane table creation = TBAC (SPEC-070/111 correction)

Supersedes "execution role = LF admin ⇒ catalog-wide create". LF data-lake **admin status does NOT grant `CREATE_TABLE`** on a database the admin didn't create — so table-builder/table-share/data-quality (all admins) silently failed to create tables in user/shared DBs. Fix: a single **`portal-managed` LF-Tag** stamped on **every** personal + shared DB at provision time (`post_confirmation.py` / `create_space.py` call `AddLFTagsToResource`; backfill existing DBs via `scripts/backfill-portal-managed-tag.sh`), with **one tag-policy grant per execution role** (DB `CREATE_TABLE`… + inherited table perms) — **not** per-DB named grants. Locations (which LF-Tags can't express) get a **static per-bucket `DATA_LOCATION_ACCESS`** grant (3 roles × user-space + shared buckets). The portal role keeps its named per-DB grant (per-user isolation needs the named ARN). Not-in-scope-to-change: the "per-user isolation = username IAM principal tag, not LF-Tags" decision — that's a *different, per-user* tag. Detail: `infra/modules/analytics/lakeformation.tf`.

### No ASL state decodes an error Cause (PR #252, control-plane-wide)

`States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **neither retriable nor catchable anywhere** — not even by a `Catch` on the same state. The `ParseError` `Pass` states that did this killed executions *before* the recorded-failure/notify states on 3 of 4 real error shapes (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — verified live with `TestState`). Terminal states now carry the **raw `$.error` `{Error, Cause}`**; `cpcommon.errors.failure_reason` decodes it in Python. Enforced by `lambdas/control-plane-common/test_state_machines_cpcommon.py`. Related trap: a `Pass` state's JSONPath hard-fails on an **absent key** (a null *value* is fine), so anything a terminal `Pass` names must be seeded on every path — now **enforced by a test** (SPEC-114): every `Pass` reachable from a failure seed may read only keys that seed supplies. It has caught this arc twice (`$.location`, SPEC-112; `$.reportKey`, SPEC-114).

### IaC

OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.

### Dev-unauth path

`VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

### Notifications (SPEC-058→061)

Per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}` — plus an **optional `link`**, SPEC-113 FR-008: an in-app path the message renders as, gated at render by `isSafeInAppPath` so it can never become an open redirect; absent = plain text, which is every pre-113 producer). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues (`sqs:SendMessage`). Anti-spoofing = user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim (`create` = trusted-producer-only). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; **059 browser data layer done** — `features/notifications/` read service + `useNotifications` + prefetch; **060 UI done** — header `NotificationsBell` link + `/notifications` page (10/page, mark-read/all, optimistic + Toast); **061 done** — the 062 verb Lambdas emit `create` inline via `notify.emit_notification` (orchestrator role gains `sqs:SendMessage` to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` env), best-effort.)

### Responsive (SPEC-095)

Mobile-first with **two custom breakpoints** in `index.css` `@theme` — Tailwind defaults (`sm`/`md`/`lg`/`xl`/`2xl`) reset to `initial`, only `tablet:` (≥900) / `desktop:` (≥1300) compile; unprefixed = mobile. Reflow via responsive utilities on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); a separate markup branch is allowed only for genuine structural divergence (Files table vs card list) or mount-cost/mobile-chrome cases. One viewport hook `useBreakpoint`/`useIsMobile` (`src/lib/`) for **mount-gating only**, never styling. Mobile nav = Header hamburger → `AppNavDrawer`; shared `Menu` + `MobileActionBar` primitives; `Modal`/`Drawer` gain small-screen presentations. Detail: `best-practices/react/react.md` §20.

### Help & guides (SPEC-074)

In-app how-to surface — a header help icon → `/help` page (Files/Query left-rail shell: section sidebar + accordion guide cards, active section in the URL hash). **Presentation + authored content only** (no data layer/network/AWS/IAM/infra/env/deps). Content is a **static, code-grounded** module (`features/help/helpContent.ts`) documenting only shipped, wired-end-to-end behavior (FR-005) — **keep it in sync via the completion-ritual step 6** whenever a user-facing feature lands/changes.

### User-facing error messaging (SPEC-106)

Raw AWS/Cognito/Athena text is **never** shown to a user. One SPA mapping module (`lib/errorMessages.ts` `toUserMessage`) is the single source of error wording — app code → AWS/Cognito name → Athena pattern → generic "Contact the Administrator" fallback; never render `error.message` directly (route it through the mapper at the code-in-scope boundary). App-level `ToastProvider`/`useToast` + `ErrorBanner` replace per-page toasts; dev-only original-error log (`import.meta.env.DEV`). Lambda control planes (tb/tscommon, shared-space create/delete) emit friendly failure notifications + cache `reason`, keeping raw text in logs + the SFN/registry record. Detail: `spec-delivery/SPEC-106`.

### Security scanning (SPEC-138)

Five classes of scan across all three surfaces — SAST (Semgrep `p/owasp-top-ten` + language rulesets), dependencies (`npm audit` at **two scopes**, `pip-audit` over glob-discovered requirements), secrets (`gitleaks`, full history, redacted), IaC (`checkov` on `infra/`) and DAST (OWASP ZAP baseline, weekly, unauthenticated). Three decisions carry the weight. **(1) Gating is data, not code:** one `GATE_*` value per scanner in `security.yml`, all `report` at ship, and an unrecognised value is a *hard error* — a typo must never silently mean "not enforcing". The exception is `eslint-plugin-security` + `no-unsanitized`, which run inside `npm run lint` (now `--max-warnings 0`) and therefore **block**: an injection sink in code being written now should stop the PR, not become a line in a report. **(2) Every scanner is version-pinned**, for the reason `pyproject.toml` already records — ruff 0.16.0 widened its defaults and reddened `main` with 500 findings in untouched files (#311); a scanner that gains rules on release does that to every open PR at once. **(3) "Did not run" is never "clean":** unparseable output, a scanner exit ≥ 2, or Checkov `parsing_errors > 0` fails the job *even under `gate=report`*, and Semgrep's partial-parse count is published beside its finding count. That is SPEC-137's failure mode — three gates all satisfied by an import that could never resolve — and a zero from a broken scanner reads as evidence, which is worse than no scanner. **Not available, not declined:** CodeQL, SARIF upload and the Security tab need GitHub Code Security, which a private repo on a personal account does not have — hence the job-summary-plus-artifact substitute and the fact that each run is a fresh snapshot with no cross-run deduplication. **Declined on merit:** OWASP Dependency-Check (NVD-centric, slower and less accurate than the ecosystem-native audits) and a second `bandit` (ruff already selects `S`). **Known blind spot:** Checkov parses `.tf`, so the `.tftpl` IAM policies that implement the whole `${aws:PrincipalTag/username}` isolation model are opaque strings to it — a green Checkov job says nothing about the authorization model, and closing that needs `checkov -f plan.json` against a `tofu plan`. First-run findings and their dispositions: `docs/security-baseline.md`.

### IAM policy scanning = the rendered plan, not the templates (SPEC-139)

SPEC-138's Checkov step reads `.tf` and therefore evaluates **zero** IAM policy-document checks, because every policy in this system is a `templatefile()` call it cannot resolve. `deploy-infra.yml`'s plan job now saves the plan, renders it with `tofu show -json`, and scans that with `--framework terraform_plan`: **431 IAM checks against 55 IAM resources**, where the `.tf` scan evaluates none. It lives in `deploy-infra.yml` rather than `security.yml` because the plan and the AWS credentials already are, and that workflow is now in **its own path filter** — otherwise a change to how we scan the infrastructure could merge having never run. **Renaming the `.tftpl` policies to `.json` was raised and REJECTED on measurement:** Checkov emits nothing — zero findings, exit 0 — for a standalone policy file containing `"Action": "*", "Resource": "*"`, because it evaluates `aws_iam_policy` *resources*, not loose documents. The extension was never the blocker; the unevaluated `templatefile()` in the `.tf` was. Keeping `.tftpl` also keeps the signal that `$${aws:PrincipalTag/username}` escaping applies, which is the most error-prone thing about these files. (51 of the 57 templates happen to parse as JSON; 6 do not.) **Two scanners, deliberately:** the `.tf` scan runs every PR + weekly and reports checks the plan scan does not; the plan scan is the only one that reads IAM. Neither is redundant. **The scan asserts its own coverage:** if the plan holds `aws_iam_policy` resources but no IAM check was evaluated, the job fails — a silent regression to the `.tf`-only state would otherwise look identical to a clean run, and that tripwire caught a real matcher bug (`^aws_iam_` never matches `module.data.aws_iam_policy.x`) before CI did. First-run result: the isolation policies are **clean**; all 6 IAM findings are deploy-role `lambda:*EventSourceMapping` statements on `Resource: "*"`, an action AWS does not allow to be resource-scoped — the available hardening is a `lambda:FunctionArn` condition key. Detail: `docs/security-baseline.md`.

### A scanner gate blocks on a narrowed count, never a total (2026-08-09, completes SPEC-138)

SPEC-138 shipped every scanner as `report` and `docs/security-baseline.md` proposed a threshold for
each. Four now block: `gitleaks` and `pip-audit` at a true zero (2026-08-02), and **Semgrep** and
**Checkov** here, plus `GATE_CHECKOV_PLAN` on the rendered-plan IAM scan. Semgrep needed one thing —
`--exclude-rule` for a Flask template-injection rule in a fleet with no Flask, excluded **by rule ID**
rather than by dropping `p/owasp-top-ten`, with a test asserting there is exactly one exclusion so a
second cannot arrive without a disposition. Checkov needed a shape.

**The shape is an ENFORCE list, not a suppression list.** Checkov reports 373 failures over 22 rules
on `infra/`, nearly all of them documented accepts — no VPC, no CMK, no X-Ray, no WAF. Gating that
total would mean suppressing 22 rules to enforce a handful, producing a file nobody reads and a gate
whose meaning drifts every time the scanner adds a rule. So `.github/checkov-enforced.txt` names the
**52 check IDs measured at zero**, and the gate counts failures on those; the rest publish and do not
block. **The criterion is "passes today", not "matters most"** — two entries are merely operational
(`CKV_AWS_216`, `CKV_AWS_305`) and are in because they pass. Deciding which checks *deserve*
enforcement is an argument to re-litigate on every infra change; holding everything already clean is
not, and it costs no remediation to turn on. Same ratchet-at-the-measured-level shape as the coverage
floors (SPEC-150) and the mypy baseline.

**The plan scan accepts by check ID AND resource, never by ID.** Its two permanent findings —
`CKV_AWS_290`/`CKV_AWS_355` on `module.base.aws_iam_role_policy.github_actions_deploy` — exist because
the deploy role must create resources that have no ARN yet and no applicable condition key. Keyed by
resource, the same two rules firing on any other policy still fail; keyed by ID alone, the exemption
would silently cover the isolation policies, which is the one thing this scan exists to watch.

**Three implementation facts that are not obvious and will bite again:**

- **`--quiet` strips `passed_checks`**, and without them an enforced ID that passed is
  indistinguishable from one that never ran. The flag is gone from the `.tf` scan (the plan scan had
  already learned this) and a test pins its absence.
- **An enforced ID evaluated against nothing is a hard error, not a pass** — and so is a plan-scan
  acceptance that matches no finding. A typo, a rename in a scanner bump, or a resource class
  leaving the repo all yield a line that enforces nothing while reading as enforcement: "did not run
  is never clean", turned on the gate's own configuration. **Neither Checkov gate can redden a
  production deploy:** `deploy-infra.yml`'s `plan` job is `pull_request`-only and `apply` does not
  depend on it, so both gates block PRs and nothing else.
- **A gate's count defaults to a NON-NUMERIC sentinel, and its narrowing step assigns before it
  echoes.** These two together are what make the hard errors above reachable, and the first draft
  had neither — every one of them arrived at the gate as a silent green. `echo "VAR=$(script)"` does
  **not** fail the step when the script fails: `echo` exits 0, `set -e` sees success, and the empty
  value it writes wins over any earlier record. Only an assignment's failed substitution trips
  `set -e`. And `${VAR:-0}` substitutes on **empty** as well as unset, so a numeric default converts
  "no count was written" into "clean" — `apply-gate.sh` rejects a non-numeric count, which is what an
  absent count is. ZAP's pre-existing `no-report` default is the same idea; it was there to be copied
  and wasn't. **A pessimistic pre-write does not substitute for either**, which is what the first
  draft believed.

**One exposure accepted, and it is not the Checkov one.** Semgrep's binary is pinned but its
`--config p/*` rulesets are fetched from the registry at scan time and are **not** — so an upstream
rule addition can redden every PR with no code change, the shape #311 made this repo pin everything
to avoid. Accepted because `pip-audit` already blocks on a live advisory database with exactly the
same property, and because the alternative (vendoring 157 rules) trades a rare interruption for a
permanent staleness. The Flask false positive is the demonstration that these rulesets misfire here;
if a second arrives, the answer is another `--exclude-rule` with a disposition, not a narrowed count.

**Still not blocking, by decision:** `npm audit` — `apply-gate.sh` has no severity threshold and the
runtime scope carries two accepted `dompurify` advisories (monaco pins the version exactly), so a
flip would redden every PR; ZAP — two Lows survive by decision, so gate by `riskcode >= 2` or not at
all. Record: `docs/security-baseline.md` → *Addendum — The Gates Went On*.

### Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)

`deploy-infra.yml`'s `workflow_dispatch` takes an off-by-default `skip_refresh` boolean that adds `-refresh=false` to the apply. It exists because **the deploy role can lock itself out**: tighten (or widen) one of its own grants and the next refresh needs the permission the pending change would restore, so plan, apply **and revert** all fail on the same `AccessDenied`. Applying from cached state installs the fix and unblocks normal runs. **Deliberately unreachable from `push`** — skipping refresh means drift is not detected, so it must be a conscious act; the step emits a warning telling the operator to follow up with an ordinary run, and that follow-up is not optional (an apply that skipped refresh has proved nothing about drift). It replaces the out-of-band `aws iam put-role-policy` break-glass as the *preferred* escape, because it needs no AWS access outside CI — that break-glass stays as the fallback. First use: 2026-08-02, recovering from the SPEC-139 follow-up (`lambda:ListTags` removed from an event-source-mapping statement on the false assumption that the function-scoped grant covered it — a mapping ARN and a function ARN are different resource types). **Caveat worth knowing before trusting any single run:** during that incident `plan` passed twice while `apply` failed on the identical call with no policy change between them, so IAM's eventual consistency can make the deadlock look intermittent — a green plan is not evidence the permission problem is fixed. Full trap list: `architecture.md` → *Deploy-role IAM — adding a new resource type*.

### Response headers / CSP (SPEC-140)

One `aws_cloudfront_response_headers_policy` on the distribution's default cache behavior carries the browser-facing security posture — **enforcing** CSP, HSTS (`includeSubDomains`, **no `preload`**), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP — and strips `Server` and `x-amz-server-side-encryption`. Four decisions carry the weight. **(1) The CSP is assembled from variables, never literals.** `connect-src` *is* the app's network surface — there is no backend, so anything missing from it is a broken feature — and it is built from `var.aws_region`, the two bucket names and the Hosted UI domain, passed as **constructed strings from root locals** because `modules/app` is upstream of `base → data` and a module reference would be a dependency cycle. A hardcoded region or bucket would have to be hunted down during the client-environment transition. (**Correction 2026-08-04:** the Hosted UI domain was missing from the shipped list, and it broke sign-in outright once the policy went enforcing — Amplify's authorization-code exchange POSTs to `https://<hosted-ui-domain>/oauth2/token`, which is **not** `cognito-idp`, so the returning `?code=` was never redeemed and the app sat signed-out over a live Cognito session. Enumerate `connect-src` from the **hosts the app actually fetches**, not from the AWS services it uses.) **(2) Report-only first is not ceremony.** A CSP wrong about `worker-src` or `style-src` breaks the Monaco editor in production and nowhere else, because no unit test observes a CSP. It earned its keep twice: it caught that `src/index.css:1` `@import`s Inter from `fonts.googleapis.com` (Vite leaves remote `@import`s in built CSS, so an enforcing CSP would have stripped the typeface site-wide), and it exposed that **Safari refuses to evaluate a report-only policy naming no reporting endpoint** — logging "the policy will have no effect" and applying nothing, so a verification pass reports zero violations whether or not any occurred. Chrome and Firefox honour report-only without one, which is exactly why a Chromium-based harness cannot surface it; the same reason CDP `Runtime.evaluate` is useless for CSP probing, since it bypasses page CSP entirely (it reported `new Function` as *allowed* under `script-src 'self'`). Verify a CSP with a **same-origin page script**, and always include a negative control that proves enforcement is live. (**Correction 2026-08-04:** report-only also has a blind spot the promotion to enforcing walked straight into. Report-only **never blocks**, so the sign-in pass that "reported no violations" succeeded *because* the policy was inert, and the one violation it did raise was reported to an endpoint nobody read. A report-only pass proves a flow still works; it proves nothing about whether the flow would survive enforcement. **Read the violation reports, or re-run the flow against the enforcing policy before calling it verified.**) **(3) Three findings are accepted, not silenced.** `Cross-Origin-Embedder-Policy` is absent because `require-corp` buys cross-origin isolation this app cannot use (no `SharedArrayBuffer`, no high-resolution timers) at real risk to subresource loads. `preload` is absent because it declares an intent to submit to hstspreload.org that we do not have, on a shared-suffix `*.cloudfront.net` name a custom domain will replace, and it is near-irreversible once granted — this **fails Checkov `CKV_AWS_259`, whose sole objection is that flag**. (**Update 2026-08-03:** `preload` was flipped on, clearing `CKV_AWS_259` — it is inert without an hstspreload.org submission, so **never submit this `*.cloudfront.net` domain** to hstspreload.org.) `style-src 'unsafe-inline'` stays because Monaco injects `<style>` at runtime — this is a **new ZAP Medium introduced by the fix itself**, and removing it needs per-response nonces, impossible on a static S3+CloudFront origin without Lambda@Edge; `script-src` carries no such allowance, which is the one that matters. **(4) A finding total is not a signal.** `CKV2_AWS_32` clearing and `CKV_AWS_259` appearing cancelled at 305, so the Checkov total looked untouched; ZAP went 20 → 13 while gaining a Medium. Diff **per check ID and per resource**, never by count. Full account: `docs/spec-delivery/SPEC-140-cloudfront-response-headers.md`.

### Static-asset caching = three prefix-scoped sync passes (SPEC-141)

`deploy-app.yml` uploads `dist/` in **three passes**: hashed assets under `assets/` as `public, max-age=31536000, immutable`, then the shell and root files as `no-cache`, then a repeat of the assets pass carrying the **one** `--delete`. Four things make that shape non-negotiable. **(1) The bug was the BROWSER cache, not the CDN.** The deploy already invalidates `/*`, so CloudFront never served a stale shell; with no `Cache-Control` anywhere, browsers applied **heuristic freshness** to `index.html`, and `--delete` had already removed the hashed bundle that shell referenced — **a white screen, not stale content**, on exactly the users whose cache was warm, and unreproducible with devtools caching disabled. Reach for the origin object's headers, not an invalidation, when the symptom is "some users see a broken app after a deploy." **(2) `--exclude` PROTECTS destination keys from `--delete` — it does not endanger them.** The CLI filters the reverse (destination) generator with the same patterns re-rooted at the destination (`awscli/customizations/s3/filters.py` builds `dst_patterns` beside `patterns`; `subcommands.py` gives `rev_generator` its own filter), so an excluded object is never a deletion candidate. The consequence: **a pass that excludes a prefix can never reconcile it** — `--delete --exclude 'assets/*'` keeps every stale chunk forever. Scope passes by **prefix** (`dist/assets/` → `s3://…/assets/`) so each owns a disjoint key set. (*Corrected 2026-08-04 by the SPEC-141 review, which read the CLI source: the original entry, the workflow comment, and SPEC-141:108-109 itself all stated this backwards — claiming an excluded `index.html` would be deleted. The implementation was never affected; only the reason was wrong.*) **(3) No file may be uploaded by two passes.** `sync` compares size and mtime, and a fresh CI checkout makes every local mtime newer than the bucket's — the first deploy re-uploaded all 108 assets on a byte-identical build, confirming a second pass over the same files would overwrite the immutable header with that pass's `--cache-control`. **(4) Deletions therefore live on their own pass, and the surviving orphan class is a SPEC CHOICE rather than a CLI constraint.** `--delete` scoped to `assets/` leaves stale **root-level** objects behind (harmless, unreferenced, removable by hand). Adding `--delete` to the shell pass **would** reconcile those — `--exclude` protects every asset key from that same deletion (verified against the CLI's `dst_patterns`), and the assets pass still reconciles chunks, so nothing would be retained. What forbids it is SPEC-141's AC "exactly one sync pass carries `--delete`", **written on the same mistaken reading of `--exclude` corrected in (2)**. Revisit the AC deliberately if the manual cleanup becomes annoying; the cost to weigh is that a root-scoped `--delete` removes anything in the bucket not produced by `dist/` (nothing else writes it today). `icons.svg` is the first such orphan. The residual race is **accepted and documented**: a tab already open that lazy-imports after the delete pass still 404s inside `Suspense` — **both** lazy routes are exposed, `/query` (which loads Monaco beneath it) and `/connections`, so a fix must not be scoped to Monaco; closing it needs retained bundles behind an S3 lifecycle rule. Rule of thumb for the whole area: **a content-hashed URL is immutable, a stable URL must revalidate**, and prefer a path prefix over an extension list — `dist/assets/` carries a `.ttf` that a js/css rule would miss. Full account: `docs/spec-delivery/SPEC-141-cache-control-headers.md`.

### Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)

A refresh reads a table this run did not create, so before re-deriving anything it must answer *can
this be faithfully rebuilt from its own definition plus a fresh look at its files?* **It answers from
what Glue reports, never from a `portal.managed` marker** — and the marker exists anyway, written by
`cpcommon.ddl.build_create_table_ddl` from this spec onward. Both halves of that are deliberate.

**Why not the marker.** Every table created before SPEC-143 lacks it, so a marker test refuses the
entire existing estate. Worse, `TBLPROPERTIES` are user-writable through `ALTER TABLE SET
TBLPROPERTIES` from the query workspace — so it can be trusted neither as a permission nor as a
fact, and the moment a verb branches on it a user can grant themselves whatever that branch guards.
A test scans the whole Lambda tree and fails if anything outside `ddl.py` (which writes it) and
`glue.py` (which excludes it) so much as references it. That scan reads the **parsed AST**: a
literal-only grep waves through `from cpcommon.ddl import PORTAL_MANAGED`, and a text scan flags the
comments that warn against confusing `portal.managed` with `portal-managed`. **Those two names are
one character apart and unrelated** — the dotted one is a table TBLPROPERTY that records and grants
nothing; the hyphenated one is the Lake Formation tag on DATABASES that is how control-plane roles
get `CREATE_TABLE` at all (`infra/modules/analytics/lakeformation.tf`). Every site of both carries a
comment saying so.

**What the shape checks are.** `cpcommon.glue.clone_definition` — moved here from `tscommon.glue`
because table-share asks the identical question — refuses views, non-external tables, catalog-
partitioned tables and unusable locations. The refresh path **maps** its four codes to its own
vocabulary at its call site rather than parameterising them (the stems differ, so no substitution
produces both sets), and asserts its mapping covers `clone_definition`'s whole set. That assertion
is load-bearing: `cpcommon.glue` now registers those codes itself, because `TerminalError` validates
at the raise site and they were previously registered only as an import side effect of
`tscommon.messages`, which a table-builder Lambda never imports. Registration is what lets the
refresh path speak — and its cost is that an **unmapped** code no longer explodes; it would sail
through as a valid terminal and resolve to the generic `unexpected_error`.

**Beyond the shape: the reconstruction needs two guards, and neither suffices alone.** SPEC-069's
declared partition keys are recorded nowhere but on the table, as `projection.*` properties, and
`build_create_table_ddl` requires the declared shape (it raises a bare `ValueError` on a Glue-shaped
key). So the verb rebuilds them and then **re-renders each one through the create path's own
renderer, demanding exact equality** — which catches a dropped property, a rewritten one (a
zero-padded bound), and any extra `projection.*` option. What it structurally cannot see is the
**column type**: Athena permits a projection over a wider set than this builder writes, and an
`integer` projection on a `string` column is precisely how a zero-padded partition gets declared.
That table round-trips *perfectly* and would be rebuilt as `int`, retyping the column while
reporting success. Table-level `storage.location.template` is refused for the same reason — it sits
outside the namespace the per-key round-trip compares. **The rule: a reconstruction that cannot be
performed is a refusal, not a guess.**

**Three ASL/marker traps worth carrying.** (1) **A `Choice` rule whose `Variable` path is ABSENT
raises `States.Runtime`, which no Catch anywhere can catch — it does not fall through to `Default`,
which covers only a value that is present and matching no rule.** So the one input `Default` exists
for is the one a bare `StringEquals` kills; both rules are `And` + `IsPresent`. (2) The same hazard
on the success side — `RecordSuccess` reads `$.mode` and a `Pass` state's JSONPath hard-fails the
same way — is closed by `execute-ddl` defaulting the field, since only a create reaches it; the
window is an execution starting after the state machine deploys but before the Lambda code does,
which would otherwise die *after* the table was created and the actor notified. (3) **Marking is an
explicit `mark` argument, never inferred from `storage is None`.** That inference reads correctly
against today's two callers and is wrong for the next: SPEC-144's `apply-refresh` is a `DROP` +
`CREATE` supplying a rebuilt `Storage`, so inference would strip the marker from every table a
refresh touched. Full account: `docs/spec-delivery/SPEC-143-refresh-table-contract-and-eligibility.md`.

### Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)

A refresh that would drop a column does **nothing** and fails terminally with `columns_removed`,
naming the columns in the notification. The user re-submits with `allowRemovals: true`. Removal is
singled out because it is the one class of change that breaks things somewhere the person who ran
the refresh is not looking: every saved query, view and dashboard referencing the column starts
failing, and nothing tells them.

**Two designs were rejected, and they are the two a later reader will propose.** *A plan-then-apply
pair* — run one writes a plan artifact into the user's prefix, notifies, the user clicks Apply, run
two references the plan. The textbook shape, and it costs a new artifact, a new index, a new view, a
new IAM surface and two async round trips for what the user experiences as one button. *A
browser-side preview* — the browser can already read the table's Glue columns and list the folder,
but it **cannot infer types**: that needs polars over a bounded Parquet footer or CSV head, which is
why `infer-schema` exists and carries a 240 MB layer. A preview showing guessed types would be a
preview of something other than what the apply does.

**What the chosen design guarantees, stated honestly:** the *specific columns* are named to the user
in a durable notification before any removal happens. It does **not** guarantee they read it —
SPEC-145's dialog requires an explicit tick with explicit consequence copy, and names the columns
when it can via the notification's link. Do not overclaim this as consent.

**Three things about the mechanism are load-bearing.** (1) **`allowRemovals` is validated, not
coerced** — a non-boolean is refused, because truthiness reads the string `"false"` as opting *in*,
on the one flag that authorises data loss. (2) It is **persisted nowhere** — not on the table, not in
a registry, not in an index; a test greps the Lambda tree for it. The flag authorises one run, and a
stored copy would carry that authorisation into a refresh nobody opted into. (3) **The notification
link is the only channel that names the columns to the browser**, and its column names are
**percent-encoded** — column names are NOT catalog-safe (`infer-schema` reads them verbatim from a
file header and nothing validates them), so `Order ID` puts a raw space in a URL and `&` invents a
query parameter. SPEC-145 must not re-validate them as identifiers: `CATALOG_IDENTIFIER_RE` rejects
`id`, `ts` and `Amount`, which would discard the whole link for most real tables.

> **Superseded in part by SPEC-149 (2026-08-04): the apply is no longer a DROP + CREATE.** It is a
> single in-place `glue:UpdateTable`, so the metadata loss described below no longer happens and the
> reason codes named in it are gone. Everything above this line — the opt-in, the refusal-as-warning,
> the three load-bearing mechanism points — is unchanged. See *The refresh apply replaces the
> definition in place* below.

**The apply WAS a DROP + CREATE, and what that cost is recorded in SPEC-144 FR-004** — table
identity, `Description`/`Owner` and any table-level Lake Formation grant were destroyed with the
catalog entry (column comments were carried). `ALTER TABLE ADD COLUMNS` cannot retype or remove, so it
would have covered only the easiest third. Full account:
`docs/spec-delivery/SPEC-144-refresh-table-schema-diff-and-apply.md`.

### The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)

`apply-refresh` issues **one `glue:UpdateTable`**, not two Athena statements. There is no moment at
which the user's table does not exist, no new catalog entry, and therefore no loss of table identity,
`Description`, `Owner` or table-level Lake Formation grants. A **failed update changes nothing**,
which is what retires SPEC-144's "a committed drop followed by exhausted retries notifies nobody"
exposure: there is no committed destructive step left to be silent about. It also stops the portal
entrenching a pattern it would have to unpick for Iceberg, where drop-and-recreate destroys the
snapshot history that is most of the reason to adopt it.

**The one thing to understand before touching this verb: it is a READ-MODIFY-WRITE on the live table,
never a rebuild from SPEC-143's capture.** `UpdateTable` replaces the WHOLE definition — a
`TableInput` omitting a field does not leave that field alone, it **clears it** — and
`clone_definition` never carried `Description` or `Owner` and deliberately strips `EXTERNAL`. Building
the input from the capture would delete exactly what the change exists to preserve. The verb reads the
live table immediately before writing it and mutates only the **columns** and the **`projection.*`
parameters**.

**Three mechanism points are load-bearing.** (1) The `TableInput` is an **allowlist projection** of
the live `Table`, pinned against botocore's service model by a test — `Table` returns 25 members and
`TableInput` accepts 14, so a denylist of the extras goes stale whenever AWS adds a field, and four of
today's eleven already postdate the obvious set. (2) **Column names are lowercased on write**, because
AWS documents that Athena folds names created through DDL — the create path gets the fold for free and
this path, bypassing Athena, must reproduce it or leave a mixed-case entry the create path could never
produce. (3) **`portal.managed` is re-asserted through `ddl.mark_managed`, never named in the verb**,
so SPEC-143's guard against a verb branching on a user-writable marker stays strict.

**IAM moved the right way: `glue:DeleteTable` was REMOVED, `glue:UpdateTable` added.** No verb on this
plane deletes a table any more, and a test greps the table-builder modules to keep it so. The explicit
`Deny s3:DeleteObject` is untouched — it never depended on the drop, and it outlives the mechanism
that prompted it. Lake Formation needed no change: the `portal-managed` table tag policy already
grants `ALTER`.

**What is NOT fixed, and must not be claimed:** the concurrent-refresh race is **reduced, not
closed**. The Pipe still starts executions `FIRE_AND_FORGET`, and **Glue offers no compare-and-set on
`UpdateTable`** — `VersionId` is documented only as "the version ID at which to update the table
contents", with no precondition-failure error. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions. A real fix is a serialization change to the Pipe.

> **Superseded in part by SPEC-157 (2026-08-09).** The race is now serialized by a per-table lock
> outside Glue, so the second refresh is refused rather than raced — the paragraph above stands as
> the state SPEC-149 left, not as the state today. What it says about Glue is still true and is
> exactly why the lock exists: `UpdateTable` has no compare-and-set, and `VersionId` is still not a
> precondition. The fix was NOT a Pipe change — see *A per-table lock serializes refresh* below.

Full account: `docs/spec-delivery/SPEC-149-refresh-table-in-place-rebuild.md`.

### A per-table lock serializes refresh, because the catalog cannot (SPEC-157)

Two refreshes of one table could overlap. `MessageGroupId` is the target database, so SQS serializes
*delivery* per database — but the Pipe starts the machine `FIRE_AND_FORGET`, so **delivery ordering is
not execution ordering**. SPEC-149 reduced the damage to last-write-wins between two definitions and
could not close it, because **Glue offers no compare-and-set on `UpdateTable`**.

**The serialization is a lock object in the admin bucket, claimed under ETag CAS**, one per
`{database}/{table}` under `locks/table-builder/`. The loser is **refused, not queued**: a held lock
means a refresh of that table is already running *against the same files*, so a queued run would pay a
full `inspect-source` to compute an identical definition. The refusal is a `TerminalError` through the
plane's existing notify path — the refusal **is** the notification.

**Two rejected alternatives, recorded so they are not re-proposed.** `REQUEST_RESPONSE` on the Pipe is
**impossible, not merely undesirable**: botocore's `pipes` model states that it "is not supported for
STANDARD state machine workflows", so making the Pipe synchronous means converting the machine to
EXPRESS — rejected on two independent grounds, its 5-minute ceiling against `inspect-source`, and its
**at-least-once** semantics, which would introduce the duplicate executions this spec exists to
prevent. A finer `MessageGroupId` would change nothing, because delivery is already ordered.

**The lock releases by OVERWRITING, and that is forced rather than chosen.** The execution role
carries an explicit `Deny` on `s3:DeleteObject` for the whole admin bucket, which SPEC-149 kept when it
removed `glue:DeleteTable`. Releasing by deletion would mean amending a standing safety property for an
implementation convenience, so **"free" is a state of the object, not its absence**.

**The holder is the EXECUTION ARN and must never be the request id.** A request id identifies the
*message*; Pipes delivery is at-least-once, so a redelivered message runs a second execution carrying
the same id — and the re-entrancy branch (which exists so an SFN Task retry does not self-refuse) would
hand the lock to both, silently. The ARN reaches the verb through a `Pass` state, **not** the task's own
`Parameters`: reading `$$` there means building an object, which wraps the payload, and every
notification path in this plane reads the request at the **top level** of the event.

**A lock is stealable only because executions are bounded, so the bound came first.** The machine had
no `TimeoutSeconds` — a Standard execution may run for a year, against which no age threshold is
defensible. It is a **top-level field of the ASL**, not a resource argument (`aws_sfn_state_machine`
has none; `tofu validate` rejects it). A malformed body, an unparseable stamp and a **future-dated**
one are all stolen: a timestamp that cannot be true is no evidence a refresh is running, and the
alternative is a table that can never be refreshed again.

**The freshness guard narrows the residual window and does not close it.** `apply-refresh` compares the
`UpdateTime` captured at the start of the run against its own pre-write read. **A moved stamp is not by
itself another writer** — the state retries on faults that can fire *after* the update committed, so
the retry re-reads a table whose stamp this run moved; judging on the stamp alone failed a run that had
already succeeded and sent the user a notification contradicting the success one. The columns settle
it: a live table already carrying what this run intends to write was written by this run.

Full account: `docs/spec-delivery/SPEC-157-serialize-concurrent-table-refresh.md`.

### The username directory is built from S3, not Cognito (SPEC-146)

The daily builder enumerates the user-space bucket's **top-level common prefixes**. It makes **no
Cognito call**, and a test asserts the module never names `cognito` in any import, attribute or call.

**The reasoning inverts the obvious answer, which is why it is written down.** *Today* Cognito is the
complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by
`ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate no-backend decision), so a
confirmed user who has never opened the file browser has no prefix. On that reading Cognito wins.

*After the client transition it reverses.* `transition_plan.md` §2 item 7 settles that **sign-in
provisions nothing** — the sync pre-creates every existing user's space and database, the client's own
automation creates them for new users, and `ensurePrefixMarker` is deleted outright (§6.3). At the same
time federated login makes `cognito:username` a **synthetic `identitycenter_<subject>` value** rather
than the catalog-safe username (§6.1), and users appear in the User Pool only after their first
sign-in. So S3 becomes complete and Cognito becomes both incomplete **and wrong-keyed**.

Choosing the source that is right on the far side of a migration already in flight beats the one that
is right today, particularly when today's gap is bounded: pre-production, no production users, and the
failure mode is a name missing from a suggestion list that still accepts free text.

**Do NOT add Cognito as a union "to be safe."** A second source with different completeness properties
is a second thing to reason about every time the directory looks wrong.

**The directory is advisory and is never an authorization input.** No control plane reads it; every
existence check stays `admin_get_user` against the User Pool (`shared-space-common/membership.py`,
`tscommon/cognito.py`), and an unknown name is still reported to the user as a notification. A
tripwire test fails if any Lambda outside `user-directory-build` references the path, the prefix or
the key constants.

Full account: `docs/spec-delivery/SPEC-146-username-directory-daily-builder.md`.

### Every authenticated user can read the username directory (SPEC-146)

`_directory/usernames.json` is readable by **every authenticated portal user**, through one
`s3:GetObject` statement on the portal role. That disclosure is **intended and accepted**, not
incidental, and it is recorded here rather than left implicit because the object is a single file
listing everyone in the organisation.

What makes it acceptable is that the set is already disclosed several ways: a username **is** the S3
prefix, the `username` principal tag and the Glue database name (SPEC-033); it is visible on every
shared-space roster to every member (SPEC-075); and a prefix-search feature discloses the set by
construction — a typeahead that would not confirm whether `bob` exists is not a typeahead. The
document holds **usernames and nothing else**: no display names, no email addresses. An email is not
metadata under this repo's field rule and has no place in a document every user can read.

**What was deliberately NOT granted:** no `ListBucket` widening (the portal role's grant stays
conditioned on the caller's own prefix, so `_directory/` is invisible to the file browser and the file
browser needed no change), no `PutObject`, no `DeleteObject`. The user reads; the daily builder is the
only writer.

**The builder's own `s3:ListBucket` is unconditioned**, and what that grants is stated rather than
minimised: `Delimiter="/"` is a property of the *code*, not the grant, so the role can enumerate every
object key under every user's prefix. Accepted because it holds **no `s3:GetObject` anywhere** (it can
list names and read nothing), because key names are metadata under the field rule, and because it is a
Lambda role with no user-assumable path. The obvious tightening — an `s3:prefix` condition on the
empty string — is **rejected, not overlooked**: whether botocore serialises an empty `Prefix` into a
condition key at all is an implementation detail, and if it does not the grant fails closed and the
builder's only listing call breaks. `simulate-custom-policy` would agree with whatever context key the
author supplied, so it would confirm the assumption rather than test it. If the grant ever becomes
uncomfortable, the sound fix is a separate bucket, not an unverifiable condition key.


### Compiler and coverage defaults are declared, never inherited (SPEC-150)

`tsconfig.app.json` and `tsconfig.node.json` state `"strict": true` even though TypeScript 6 already
defaults it on, and both suites carry **literal** coverage floors. Adding the `strict` key changed
**zero** errors — that is the point, and a build that finds otherwise should stop and re-derive the
premise rather than "fix" the errors.

This reverses the implicit trade-off of leaving a default alone because it happens to be correct.
`pyproject.toml`'s ruff block is the precedent and says it outright — "THE RULE SET IS CHOSEN HERE,
NOT INHERITED" — after ruff 0.16 widened its own default set from 59 rules to 413 overnight and
turned `main` red with 500 findings in files nobody had touched (#311). A default is a decision
*someone else* gets to change; strict is this project's single most important type guarantee, and it
does not ride on one.

The coverage floors are the same principle pointed at a different kind of erosion: both suites
measured coverage and neither gated on it, so deleting tests passed CI identically to keeping them.
They are **ratchets at the measured level, not targets** — portal 91/86/89/93, lambdas 95 — and each
is a hard-coded literal on purpose. Nothing computes, inherits or reads them from a file, so lowering
one is a visible one-line diff in review rather than a number that drifted. Raise them when coverage
rises; never lower one to accommodate a regression.

**Do NOT read this as "enable strict"** — it was already on. The work is *declaring* an inherited
default, which is a much smaller and different thing.

**The typecheck gate itself is separate and already shipped** (#363): `ci.yml` runs `npm run build`
on every PR. Two traps are recorded in that file's header comment and should be read before touching
it — vitest does not typecheck, and `tsc --noEmit -p apps/portal/tsconfig.json` **exits 0 having
checked nothing**, because that config is solution-style (project references only, no
`files`/`include`). `tsc -b` is the only invocation covering the app *and* its `*.test.tsx` files.
SPEC-150 confirmed the gate empirically on a scratch PR: with the #361 defect reintroduced, Lint and
Format check passed, **Build failed**, and Test was skipped.


### A partial teardown never frees the space name (SPEC-151)

`delete_objects` and `batch_delete_table` both answer **HTTP 200 with a per-item `Errors` array** — a
key or table that failed individually does not raise. Both return values were discarded, so a
partially-failed teardown was indistinguishable from a complete one, and `delete_space` went on to
`reg.delete(space)` — the line commented "LAST — the name is now free to reuse". The next space
created with that name would inherit another tenant's objects.

Both helpers now raise `teardown.TeardownIncompleteError`, and the rule is: **a teardown that could
not finish must leave the registry record intact.** The record is what reserves the name, so keeping
it is what stops reuse; the caller's existing `except` already records a terminal `failed`, and
`reg.delete` is inside the `try` it never reaches. `forget-space` inherits this for free — both verbs
share the helpers.

Three details that are decisions rather than implementation:

- **Counts, never keys.** The message reaches logs and the registry's `failed` record, and the field
  rule binds what a call site chooses to emit. "3 object(s) under `sales/` could not be deleted" is
  enough to tell a partial failure from a total one.
- **Every page is attempted before raising.** A denial on one key must not strand the rest of the
  space's objects, and the count is only meaningful whole.
- **The Glue raise lands BEFORE `delete_database`.** Dropping a database whose tables survived is how
  the catalog and the bucket start disagreeing.

This meets **SPEC-054**'s written acceptance criterion — teardown leaves "never a dangling …
half-deleted resource" — which had been recorded and never implemented. **Do NOT "improve" this by
deleting the record and reporting the failure elsewhere:** the record IS the lock.

### Every DDL literal goes through `literal()` (SPEC-151)

`cpcommon.ddl` renders **every** string literal in a `CREATE EXTERNAL TABLE` through `literal()` —
`TBLPROPERTIES` keys and values and the `LOCATION`, alongside the column comments that already did.
Raw `f"'{value}'"` is forbidden in DDL construction.

The demonstrated consequence of the old form: a partition enum value of
`eu','projection.enabled'='false` rendered as
`'projection.region.values'='eu','projection.enabled'='false'`, **injecting a property that switched
partition projection off**. Blast radius is **self-scoped** — a user can only reach a table in their
own database and Athena rejects multi-statement DDL — so this is robustness, not cross-tenant
escalation. The sharper everyday path is data-quality, where the `LOCATION` and the partition values
both come from **S3 key segments**: a folder named `year=2024'` or `o'brien` broke the temp-table DDL
and killed the whole check as `query_failed`.

**Two escapers exist and must not be confused.** `cpcommon.ddl.literal` escapes with a **backslash**,
which is Hive's rule and what Athena parses `CREATE`/`DROP` with. `dqcommon.sql._literal_dml` **doubles
the quote**, which is Trino's rule and what Athena parses `SELECT` with. Using the Hive form in a
query would render a backslash into the S3 path being matched, and the predicate would silently match
nothing. Each lives in its own module with a docstring saying so; `tscommon.ddl._lit` is the
table-share twin of the DDL one and has always done this.

Ordinary values render **byte-identically** to the old form, which is why the golden-DDL tests are
untouched — a rendering change that moved any existing statement would have been a different and much
riskier decision.

**Corroborated, not demonstrated:** the escaped form has never been exercised against Athena itself.
The tests assert the rendered string. If a `'` in a partition segment ever still fails, suspect the
engine's acceptance of `\'` before suspecting the renderer.

### Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)

All four control planes now carry a `NotifyFailure` state ahead of their terminal `Fail`, reached on
every failure path, invoking a thin per-plane verb that decodes the raw `{Error, Cause}` with
`cpcommon.errors.failure_reason` and emits through the plane's own notifier.

**The gap this closes was named by the repo's own design and closed in one of four planes.**
`@notifies_on_failure` needs handler code to run. SPEC-126's DLQ drain covers requests that never
started an execution. Neither covers the middle: an execution that started and then failed **before or
outside** any verb's Python — a `States.Timeout`, a `States.DataLimitExceeded`, a task-level throttle,
a Lambda that fails at **import**. In that window the user got no notification, no DLQ message, and a
request that never completed — against SPEC-114's rule that the notification **is** the completion
channel, with no admin UI to check and no reason to suspect anything but slowness. Not theoretical:
SPEC-137's nine-day `ModuleNotFoundError` and PR #196's shared-layer cold-start crash are both exactly
this shape.

**A fifth plane cannot ship without it.** `test_state_machines_cpcommon.py` enumerates every
`state-machine.asl.json.tftpl` under `infra/modules/` and asserts each has a `NotifyFailure` Task with
a `States.ALL` Catch, plus that its `RecordFailure` copies `$.error` **whole**. The exemption list is
an empty dict — an entry is a decision to leave users in the dark, not a formality. The second
assertion is not redundant with the throwing-intrinsic guard: a plane could satisfy that one perfectly
by copying `$.error.Error` alone, and every message would silently degrade to the generic.

**The duplicate-suppression mechanism differs per plane, and the difference is forced, not stylistic.**
This state sits on *every* failure path, because the paths where no verb ran cannot be selected for in
ASL — so an ordinary failure would otherwise notify twice.

- **table-builder / table-share** suppress in Python via `_verb_already_notified`, on **one name**:
  `Error == "TerminalError"`. That is the only *positive* evidence available — a verb raised it
  deliberately and the decorator's `emit_terminal` fired — and it is the only case where the
  decorator's message is strictly better, because it carries `err.tokens` (without which a
  `columns_removed` refusal cannot name the columns). Everything else notifies, including an
  exhausted `TransientError`, which the decorator deliberately leaves un-notified — a gap this spec
  therefore also closes.

  **The obvious generalisation is wrong in the dangerous direction, and was caught in review.** An
  earlier version inferred the same thing from the *absence of a dot*: bare class name means a
  handler ran, dotted engine name means it did not. But `cpcommon.config` calls `_require` at
  **module scope** and raises a bare `RuntimeError` — not a hypothetical, this fleet's own recorded
  outage (`lambda.tf`: "check-table-absent: RuntimeError COGNITO_USER_POOL_ID unset", PR #196). The
  heuristic would have suppressed it, silencing the exact class of failure the spec exists to
  report. The set of dot-free names meaning "a verb notified" is unbounded and unknowable from the
  payload; the set meaning `TerminalError` is one string.

  **The price is a duplicate on the unexpected-exception path** — a `KeyError` inside a verb
  notifies through `emit_unexpected` and again here, same generic sentence. FR-002 settles it: a
  duplicate is preferable to none. A guess that suppresses is unrecoverable; a duplicate is a
  papercut on a path that is already a bug.

  **A seeded error must not wear a verb's name.** table-builder's `DiffMissingSeed` (the
  `RouteByChange` `Default`) manufactured `Error: "TerminalError"` for a case where `diff-schema`
  *returned successfully* without a `$.diff` — so no exception was raised and no decorator fired. It
  now seeds `DiffMissing`, because a defensive seed whose whole purpose is the shouldn't-happen case
  is the last thing that should buy itself a `Fail` state and silence. The user-facing text is
  unchanged: neither code is registered, so both render the generic clause.
- **shared-spaces** cannot use that test, because five of its seven verbs emit **no** failure message
  at all and a "did a verb run" guard would restore their silence. It reproduces the verb's **FIFO
  dedup token** byte-for-byte instead (`{requestId}:{action}-failed:{actor}`), so SQS drops the second
  message where a verb already spoke and delivers it where none did.
- **data-quality** is unchanged: `dqcommon` centralises one `FAILURE_STEP`, so its pair already
  collapses on an identical token. Unifying `tbcommon`'s per-verb steps to match would change
  notification behaviour on paths that already work.

**shared-spaces needed structural work, not just a state.** Its seven verb `Catch` blocks carried **no
`ResultPath`**, so the error object *replaced* the state and the verified actor was discarded — there
was no recipient to notify even in principle. They now merge under `$.error`; a `ValidateFailureSeed`
covers the pre-identity path (its Catch cannot carry a `ResultPath` — you cannot merge a key into an
array), and the router's `Default` gets an `UnknownActionSeed` whose **literal** `Result` merged under
`ResultPath` is the one seed form that reads no path and so cannot itself raise.

**`$.mode` on table-builder's `RecordFailure` supersedes the rule that forbade it.** The old test
banned `mode.$` there; its stated *reason* was that `ValidateFailureSeed` did not seed it and a Pass
state hard-fails on an absent key. The ban was never the invariant — the seeding was. `mode` is now
seeded, and the test asserts the general form: `RecordFailure` may read nothing `ValidateFailureSeed`
does not seed. Without it a failed **refresh** tells the user their **create** failed.

**shared-spaces gained a `failure_message` resolver** (`shared-space-common/messages.py`), the last
plane to get one. Its domain table is **empty on purpose**: every reason that can reach this path is a
raw engine name that SPEC-106 FR-008 forbids showing, so what varies is the **action**, not the reason.
Going through `cpcommon.messages.register` rather than hard-coding the clause means a code registered
later renders through the same path.

**No deploy-role IAM was needed, and that was verified rather than assumed.** All three planes' deploy
policies scope `lambda:CreateFunction`, `iam:PassRole` and `logs:CreateLogGroup` to
`{project}-*-<plane>-*` wildcards, and each plane's SFN invoke grant renders from the same `locals.tf`
map the new function was added to. SPEC-143's `load-table-definition` is the live precedent. The
spec's Phase 1 assumed an expansion and sequenced a separate land-and-apply around the self-grant
timing trap; neither was required.

**The cold-start probe is the one gate that would have caught SPEC-137.** `test_notify_failure_import_safety.py`
imports each new verb in a fresh interpreter whose `sys.path` is **exactly** what its deploy-matrix row
grants. `conftest.py` puts every layer root on `sys.path` for the whole suite by design, `update-function-code`
succeeds against a function that cannot import, and `test_deploy_matrix.py` reasons about **names** — it
cannot tell you the named layer actually publishes what the code imports. The environment is
**inherited**, unlike `test_layer_import_safety.py` which withholds `cpcommon.config`'s six: these verbs
reach their DOMAIN config through their notifier, whose import-time `_require` is *supposed* to run.
(`cpcommon`'s own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what
an import demands from anyone.) Only `sys.path` is scrubbed, because packaging is what is under test.

**One layer needs a second guard, and only one.** The probe puts layer SOURCE TREES on `sys.path`, so a
module present on disk but absent from a layer's *build* is invisible to it. Every layer copies a
**package** (`cp -r cpcommon`) except `shared-space-common`, which publishes **flat modules** from an
explicit `for m in config casio auth …` list in the workflow — so a new module there ships only if
someone remembers to name it. Review confirmed the gap was live: deleting `messages` from that list left
the entire suite green while the deployed layer lost it. A test now joins the workflow's list against the
directory — **SPEC-153 moved it to `test_deploy_matrix.py`**, the harness whose subject is packaging, and
generalised it; see *A layer gate must check the copy list, not the flag map* below.

---

### A layer gate must check the copy list, not the flag map (SPEC-153)

`test_deploy_matrix.py` exists because SPEC-137 shipped instrumented code whose layer attachment was
missing and every gate was blind. It joins each function's **imports** against the matrix **flags**.
That answers "which functions attach the layer" and says nothing about **what the layer contains** —
so adding a module to `lambdas/shared-space-common/`, importing it from a function whose row already
reads `layer: true`, passed every check, deployed green, and raised `ModuleNotFoundError` at cold
start. SPEC-137 again, straight through the gate built to stop it.

**The rule: for any layer packaged by an explicit per-file list, assert SET EQUALITY between that list
and the directory.** Both directions — a module in the directory and not the list never ships; a
module in the list and not the directory fails the `cp` at deploy time. Completing the flag map does
**not** substitute: all nine shared-space modules ship in one layer behind one flag, so a module that
never reaches the zip is invisible to the flag map no matter how complete it is. `LAYER_PACKAGES` was
corrected to all nine anyway, with a comment saying exactly that.

`shared-space-common` is the **only** such layer — every other copies a whole package directory or
pip-installs, so a new module ships by existing, and those are exempt for that named reason.
`test_no_unchecked_explicit_copy_list_was_added` fails if a second one appears, so the exemption
cannot quietly widen. A guard-the-guard asserts the parsed set is non-trivial: two empty sets are
equal, and a regex that stops matching would otherwise pass vacuously.

SPEC-152 shipped the shared-space half of this in
`test_notify_failure_import_safety.py`; SPEC-153 moved it to the packaging harness and generalised it,
rather than leaving two copies of one set-equality to drift apart.

---

### `ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)

The repo invented this idiom in SPEC-110 (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`).
SPEC-153 makes it the standard way to record a **load-bearing premise that is corroborated but not
discharged**, and a **documented behaviour someone will later mistake for a bug**.

A tripwire test pins **today's behaviour**, names the reasoning in its docstring, and ends with the
same instruction every time: **if it starts failing, revisit the decision — do not delete the test.**
That is the whole point. A premise held only in prose degrades silently; a premise held in an
assertion tells you the day it stops being true.

Four now exist. Two pin premises:

- **Athena's column-name fold** (`test_apply_refresh.py`). AWS documents that Athena lowercases every
  column name it creates through DDL, which is why SPEC-149 hard-codes the fold — but 149's in-place
  `UpdateTable` bypasses Athena, so the fold is now **ours**. If the premise is wrong, the first
  refresh of a mixed-case table silently re-cases every column while `diff-schema`, which folds case
  to compare, reports them unchanged: a mutation no test and no notification would report. The
  tripwire pins that a live `Order_ID` becomes `order_id` and the carried comment survives. Still
  **corroborated, not discharged** — the `GetTable` read-back that would discharge it is an owed live
  check.
- **The projection round-trip** (`test_load_table_definition.py`). The existing round-trip builds its
  fixture from `ddl.projection_properties` and compares the reconstruction re-rendered through the
  same function: render → parse → render vs render. It proves the parser is a left inverse of the
  renderer **on the renderer's own image**, which is worth having and is not "reads tables this
  pipeline did not write". It was **kept and renamed to say so**, and a second fixture whose
  properties did not come from our renderer was added beside it, with a guard test that fails if the
  fixture ever becomes the renderer's output.

Two pin accepted behaviour:

- **A redelivered notification create writes a second inbox row** (`test_notifications_writer.py`).
  These pipelines are at-least-once and `apply_create` mints a fresh `uuid4` per invocation; FIFO's
  producer-side dedup window does not bound a visibility-timeout redelivery. **Accepted:** the blast
  radius is one duplicated line in a read-only, dismissible list, while the fix with teeth is a
  producer-supplied idempotency key — a contract change across four control planes and the browser
  producer. `dqcommon.index_store` handles the equivalent case by replacing the row, and the
  asymmetry is now stated rather than accidental.
- **The runs-index cap evicts by position, not by timestamp** (`test_index_store_dqcommon.py`). Once
  a replay has moved a row to the end, position order and timestamp order disagree and the next new
  run drops a row that is newer in time. **Accepted:** the code says at the cap that the dashboard
  sorts by timestamp itself, and every evicted run's report object is untouched.

A tripwire is **not** a licence to leave a defect. It is the difference between a project that knows
what it has not verified and one that has forgotten.

### `components/` may not import from `features/` (SPEC-155)

`features/query/` had become a shared layer nobody declared: `components/ToastProvider` and
`components/Sidebar` imported from it, and five sibling features pulled `CATALOG_IDENTIFIER_RE`,
`Connection`, `isConnectionUsable` and `useConnections` out of it. That direction is backwards —
`components/` is the shared presentation layer that features compose, so it cannot depend on one.

The fix moved each shared thing to where its direction is correct: `Toast` to `components/`, the
identifier rule to `lib/catalogIdentifier.ts`, and the connections domain — `Connection`,
`ConnectionKind`, `isConnectionUsable`, `useConnections`, `connectionStatusLabel`, plus the two nav
surfaces `Sidebar` and `SpacesList` — into a new `features/connections/`.

**The rule is enforced, not documented.** `eslint.config.js` bans `features/**` imports under
`src/components/**`. Two things are exempt, both deliberately:

- **Tests.** Integration-style tests mount real features by design (`react.md` §21), so the rule can
  only produce noise on that glob.
- **`Header.tsx` and `ProtectedLayout.tsx`.** These are app *chrome*: they exist to wire features
  into the shell, so composing features is what they are for. Bringing them under the rule needs a
  separate app-shell layer, which is a re-layering rather than an import fix. They are **named in
  the config** rather than left as a silent violation, so a third such file requires an explicit
  edit to that list. Everything else that was on the list has been moved out of `components/`.

Two residuals, both recorded rather than hidden:

- `features/connections/useConnections.ts` still reads `queryKeys.connections` from
  `features/query/queryKeys.ts`. Feature-to-feature is allowed, and splitting the key factory would
  change key *values* that two tests assert.
- ~~**`lib/queryClient.ts` imports `features/file-browser/fileBrowserKeys`**~~ — **CLOSED 2026-08-09.**
  It was a lower layer importing a feature, and a strictly worse inversion than the one this decision
  targets. `invalidateListing` moved to `features/file-browser/invalidateListing.ts`, beside the key
  factory it builds from; `lib/queryClient.ts` now owns only the client and imports no feature.
  `features/query`'s save-results flow reaches it through the file-browser barrel — feature-to-feature,
  which is allowed, and which was already true transitively through `lib/`.

  **The rule widened with it**, to `src/lib/**` and `src/hooks/**`. That was the point of the move:
  fixing the one file without widening the glob leaves the next one to be found by hand.

  **The test exemption is load-bearing on `src/lib/**`, not a formality.** `lib/support.test.ts`
  imports seven feature service modules — it is the consolidated lib suite, and testing a lib helper
  against real feature callers is what it is for. Without `src/lib/**/*.test.{ts,tsx}` on the
  exemption list the rule reports **6** violations there and `npm run lint` fails. The
  `src/hooks/**` test glob is inert today (nothing under `src/hooks/` imports a feature) and is
  carried for symmetry. Non-test files in both directories were clean, which is what made the
  widening a one-line glob change rather than a migration.

  The mock count in the original note was wrong — **two** test files mocked the module by path
  (`fileOpHooks.test.ts`, `UploadQueueProvider.test.tsx`); the other four merely imported it. That
  overstatement is most of why this looked expensive enough to defer.

  **What the rule still does not catch:** a dynamic `await import('../features/…')`. Base
  `no-restricted-imports` only sees static import/export forms — type-only imports, `export … from`
  and deep relative paths are all caught. The hole predates the widening and is unchanged by it.

### Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)

`FormDialog` (SPEC-155 FR-002) turned eleven hand-written dialog chromes into one. Its body is a real
`<form>` with a `type="submit"` primary button — but **the browser's implicit submission is
suppressed on purpose**, and Enter submits only from the field named by `submitOnEnterRef`
(defaulting to `autoFocusRef`).

Adopting the form naively is the trap: implicit submission fires from *every* text input in a form.
The dialogs being consolidated each had exactly one field that submitted on Enter; handing it to all
of them filed a table build from a partition-key row the user was still editing — **measured before
the fix, not hypothesised**. A radio group is the same shape: arrow keys move a choice, Enter would
commit one the user never made.

A child that already handled the key wins over both, so a combobox's Enter-to-commit still works
inside a dialog.

### Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)

`useEscapeKey` now maintains a module-level registry of enabled handlers, each tagged with its
`EscapeLayer` depth, and dispatches Escape to **the innermost one only**. Nested dialogs are correct
by construction.

What this replaces: `Drawer`'s `closeOnEscape` prop, a per-component opt-out that every new nesting
had to remember. It is **gone**, not deprecated — it had no consumer left, and a prop nobody sets is
a rule nobody applies. `Modal`'s `dismissible={false}` now **swallows** Escape (`useEscapeBlock`)
instead of letting it fall through and dismiss the layer beneath — the case `dismissible` could not
express before without also disabling backdrop dismiss.

This sits beside, and does not contradict, the settled finding that `stopPropagation` from a React
handler DOES stop `useEscapeKey`'s `document` listener (SPEC-147, measured). That is still true: a
child that stops the event never reaches the registry at all. Depth-based dispatch decides between
layers that *do* reach it.

### The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)

`fileBrowser.format.formatSize` and `query.format.formatBytes` are documented as "deliberately not
merged", and on `undefined` handling that is defensible. On the **unit ceiling** it was not: a 3 TB
object read `3072.0 GB` in the file browser and `3.0 TB` in the query status bar, from the same
number, on two screens of one app.

**Decided: unify the ceiling at TB.** This is a **user-visible change**, which is why it is a
decision and not a refactor — SPEC-155's scope otherwise forbids one. The two functions stay
separate for their `undefined` handling; only the unit table is now shared. Silently keeping both was
explicitly not an outcome the spec allowed.

### The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)

Four helpers were duplicated across the Lambda layers *on purpose*, each with a comment saying so
and naming the condition under which the copies should converge. Those conditions had all expired,
and in two cases the drift the comments warned about had already happened — `dqcommon`'s CAS twin
handled a racing 409 that `casio`'s did not and used a different retry cap, and `cpcommon/auth.py`'s
"one JWKS-verification path for the whole repo" docstring was false because `notifications-writer`
could not import it.

**Decided: `cpcommon` owns the algorithm; a domain layer owns its wording and its constants.** The
conditional-write CAS loop (FR-001), the failure-message resolver (FR-002), the results-location
builder (FR-003), the JWKS path (FR-004), the SQS envelope parser and the Athena DDL runner (FR-005)
each exist once. The domain message modules keep only their **tables**: `cpcommon.messages.Resolver`
gained `prefix`, `access_denied` and `fallback` templates and an opt-in `blank_unfilled`, so a plane
expresses its whole sentence as configuration. `Resolver.__init__` refusing a re-defined base code
is what had kept two planes out — both re-definitions were byte-identical restatements, so deleting
them was a provable no-op rather than a wording change.

**The blocker was `cpcommon.config` resolving eagerly** (FR-004). Six `_require`d environment
variables at *import* meant a function that set three could not import `cpcommon.auth` at all, so it
grew its own verifier. That is the general shape worth carrying: **an eager module-level requirement
does not merely inconvenience an importer, it forces a fork.** Config resolves lazily now and still
fails loudly at first use.

**Byte-identity was measured, not asserted.** Every reason in all three planes was rendered under
every argument combination against both implementations — 2214 messages per side. Exactly one row
differed: `malformed_event` under table-share, a shared base code that plane never declared, which
used to fall to `tscommon`'s unknown-code fallback and now reads what it means. It is unreachable
there today (table-share's only `parse_sqs_request` call raises `unauthorized`), and it is pinned by
a test rather than left to be rediscovered in an inbox. **Reading three implementations side by side
would not have found it** — that is the argument for rendering both and diffing, on any future
consolidation.

**Do NOT** read this as licence to merge the domain layers into `cpcommon`. The layers stay; only
genuinely cross-plane helpers moved, and a move that would change which layer a function attaches to
is a `deploy-lambdas.yml` matrix change with SPEC-137's failure mode attached.


### No shared-space directory is published; suggestions come from your own cache (SPEC-158)

`TableShareDialog`'s space entry suggests only the shared spaces the signed-in user belongs to,
read from the connections cache `useConnections` already fetches. **A complete list of every space
in the organisation would be strictly more useful, and it was declined.**

Strictly more useful because sharing a table to a space does **not** require membership —
`test_recipient_space_membership_not_required` pins that any active space is a valid target — so the
suggestions cover less than the field accepts, on purpose. The cost of closing that gap is a
disclosure with **no existing equivalent**: today a non-member learns a space exists only by
colliding with its name at create time, and space names are user-chosen and often descriptive
(`acme_merger`, `q4_layoffs`). The username directory is not a precedent — a username is already the
S3 prefix, the principal tag and the Glue database name (see the entry above); a space name a user
does not belong to is disclosed nowhere. The trade was put to the user on 2026-08-05 and **declined
in favour of suggesting only what the user can already see.**

**Do NOT add a space directory "for symmetry with SPEC-146."** The absence is the decision. What
holds the line in the UI is that a space the user does not belong to **stays typeable and still
commits**, with a note that says it may exist and simply not be one of yours — worded that way
because this note is the one place a user could be misled into thinking the target was invalid.

Two consequences worth carrying:

- **The suggestion source is a prop, not a hook call** (`SuggestionSource = {status, search}`).
  `UsernameCombobox` reaching for `useUserDirectory` itself was the right reading with one source
  and the wrong one with two; a near-duplicate component would have been the alternative. A second
  source is the trigger to revisit that kind of deviation, not to fork.
- **A second source costs no request.** The space list is a query the app already makes for the
  Connections page and the Query rail, and the ranking is SPEC-147's `buildIndex`/`search`, which
  were never username-specific. No Lambda, no published document, no IAM, no env var, no new AWS
  call — a test asserts the space path issues none.

### An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)

A `user_settings/` read-modify-write that cannot read the live body **copies it aside and then
writes**, rather than refusing forever (the previous behaviour) or committing the empty document
over it (the behaviour before that). The copy is a **precondition**: if it fails the write is
refused exactly as before. **A failed quarantine must never become a silent overwrite.**

The refusal it replaces had no way out. `user_settings/` denies `s3:DeleteObject`, the bucket is
unversioned, there is no admin UI and there never will be (out of scope) — so one unreadable
document permanently disabled saving queries and recording history for that user, and the only
honest advice was "Contact the Administrator", whose only tool is the AWS console.

**A newer schema is not corruption, and quarantining one would BE the data loss this prevents.**
The classifier (`lib/s3Json.classifyDocument`) reports three outcomes, not two, and checks the
version **before** the shape — a `version: 2` document is newer whatever else it contains, because a
newer schema is free to have renamed the field this build validates. A newer document is refused
untouched and answered with "reload the page"; only `unparseable` is ever copied.

**The quarantine key carries a random token as well as a timestamp, and that is load-bearing.**
`CopyObject` copies whatever is live at copy time and nothing binds the copy to the body that was
classified. Two tabs finding the same corrupt document in the same second, keyed on a clock alone,
would collide: the first sets the corrupt bytes aside and repairs the document, the second copies
the now-**repaired** document over the first one's quarantine object — destroying the only surviving
copy, on a folder that denies delete. The token makes the loser write a redundant object instead.
Do **not** "simplify" the key back to a bare timestamp. (The ordinary last-writer-wins race on the
document itself is untouched and still accepted; `IfMatch` writes are a separate, complementary fix
that this neither needs nor blocks.)

**No IAM change, deliberately.** Everything is `GetObject` + `PutObject` inside the user's own
prefix — which is why the quarantine key is a sibling of its source rather than a separate folder.
Two consequences follow and are recorded here rather than discovered later:

- **Quarantine objects are themselves undeletable.** They inherit the `user_settings/` delete deny,
  so neither the app nor the user can remove one — only an administrator working directly in the
  console can. Accepted: one object per genuine corruption event is a smaller problem than the
  evidence being destroyed.
- **Accumulation is not a loop.** The document written after a quarantine is one the app serialized
  itself, so a second quarantine requires a second, independent corruption.

**Rejected, and recorded in the spec so they are not re-proposed:** granting the portal role
`DeleteObject` under `user_settings/` (trades away a standing safety property for convenience, and
destroys the only copy of what the user had); "click Save again to replace" (reintroduces the loss
behind a confirmation the user cannot make informed, since they cannot see the document); repairing
the document in place (a guess presented as a recovered library); writing the copy from bytes
already in memory (carries an unbounded untrusted body out through the parse contract, and costs a
second `GetObject`); and a fixed quarantine key overwritten each time.

### The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)

Sharing a table used to copy every object for a recipient inside **one** `copy-objects` invocation,
inside a `Map` over recipients. The share caps followed from that: `SHARE_MAX_OBJECTS = 1000` and
`SHARE_MAX_TOTAL_BYTES = 20 GiB` were sized backwards from a 900-second Lambda timeout. A user with
several hundred Parquet part files did not get a slow share; they got a refusal that read like a
product decision and was really an implementation detail.

The copy is now a **top-level Step Functions Distributed Map** over a flat `(recipient × object)`
JSON Lines manifest in the admin bucket, batching items into the same copy code as before.

**Top level, NOT nested inside the recipient `Map`.** The nested version is the obvious one and it
buys nothing: it fans out per recipient, so the ceiling stays per-recipient work. One Map over pairs
covers every recipient at once and never raises the nesting question. It costs exactly one thing,
and that cost is this decision's other half: **per-recipient isolation stops being a property of a
Map item.**

**So attribution became a verb, and it reads BOTH result groups.** `collect-transfer-results` reads
the Map Run's `ResultWriter` export. Step Functions files a child by its **execution status, not by
what its payload says** — and the batch copier deliberately **succeeds** while reporting per-item
failures, so those land in `SUCCEEDED_n.json`. A collector reading only `FAILED_n.json` would report
universal success while a recipient received an incomplete dataset **and a table over it**. It
therefore reads `SUCCEEDED_n` (per-item `failures` from the output) **and** `FAILED_n`/`PENDING_n`
(whole-batch failures, attributed from the child's *input*). A record whose payload Step Functions
omitted (`Included: false`) is **unattributable and fails the whole request** — never "no failures
found". One failed item means that recipient gets **no table**: a partial copy under a table
definition is worse than no table at all.

**`ToleratedFailurePercentage: 100` and `STANDARD` children.** The Map Run must always finish, or
there is nothing for the collector to attribute. Children are STANDARD because a batch may hold a
multi-GiB object whose multipart copy exceeds EXPRESS's five-minute ceiling, and EXPRESS's
at-least-once semantics would re-run whole batches.

**A WHOLE-batch failure fails every recipient in that batch, and that is fail-closed on purpose.**
Items are batched in recipient-major order, so a batch spans several recipients only when a
recipient has fewer objects than the batch size — but when it does, a child execution that dies
outright (an exhausted `TransientError` retry, a Lambda timeout) takes all of them down with it. It
reported nothing per item, so which of its items landed is genuinely unknown, and the conservative
answer is the only honest one. Pre-160 each recipient had its own invocation and its own retry
budget, so this is a real narrowing of isolation, accepted deliberately: the alternative is trusting
a copy nobody observed. A Distributed Map cannot partition batches by key, so a per-recipient
guarantee would mean a Map per recipient — the nested design this decision rejects.

**Attribution keys on `(kind, name)`, never the name alone.** A destination is a pair, and nothing
in this system stops a shared space being named after a user (the archival arc records the same
hazard for its key layout). Keyed on the name, one failed object in space `acme` would deny user
`acme` a table they actually received, and send them a failure notification for it.

**The export is reconciled against the manifest, not merely parsed.** Every unrecognised shape
raises — an entry naming no object, a result file that is not a list of records, a record with no
item count — because a reader that skips what it does not understand reports a clean run over an
export it never read. Shape checks alone are not enough, though: a well-formed export can still
cover only some of the batches, so the collector requires the item count the export accounts for to
equal the count `build-transfer-manifest` wrote. Anything less is a whole-request failure.

**The raw `{Error, Cause}` is decoded at the collector and NOT carried onward.** This is a payload
decision. A Cause runs to hundreds of bytes with its stack; leaving `guardResults` on the state
*and* re-emitting the raw error in the outcomes would put three copies of every refusal on the state
by the time the finish Map merges its results — measured at **108% of the 256 KB limit** for 50
conflicting recipients, which is the *ordinary* case of re-sharing a table most recipients already
have, and a breach there lands **on a Map** and destroys every per-recipient outcome. So the
collector **consumes** `guardResults` and carries `cpcommon.errors.failure_reason`'s decoded code;
the raw object remains in the execution history at the state that produced it. The two peaks — the
guard Map's output and the finish Map's — are both modelled by
`test_the_whole_map_state_stays_under_the_payload_limit`, at 42% and 45%.

**A deterministic item failure never raises; a transient one always does.** The batch returns
per-item outcomes and succeeds, so one unreadable key never costs its 49 siblings their copy. A
throttle raises after every in-flight copy settles, and the Map retries the whole batch — safe
because copy is idempotent and the conflict guard has already run. The `CopyObjects` child state
carries **no `Catch`**: catching there would SUCCEED a failed child, filing it under `SUCCEEDED_n`
with no per-item failures, and every item in it would be reported as copied.

**The manifest key is execution-unique; the copy plan beside it is deliberately not.** A plan is a
pure function of the request, and two overlapping executions colliding on one plan key is harmless
because both plans describe the same object set — that argument is written out in `plan_key`'s
docstring and still holds. It does **not** carry to the manifest: its lines depend on which
recipients the **guard accepted**, which is time- and destination-dependent, so a shared key would
let one execution's Map Run copy for a recipient the other's guard had just refused as `conflict`.
The execution name is stamped by a **Pass** state (SPEC-157's measured pattern: reading `$$` in a
task's own `Parameters` wraps the payload, and every notify path here reads the request at the top
level).

**The Distributed Map's permissions are the STATE MACHINE role's, not the Lambda execution role's.**
It is the state machine that calls `StartExecution` for each child and that reads the `ItemReader`
object and writes the `ResultWriter` export. Putting them on the execution role renders green,
applies green, passes a policy-render test, and fails on the first real share with `AccessDenied` at
the `ItemReader` — naming a role nobody was looking at. `StopExecution` is not granted;
`StartExecution` + `DescribeExecution` is the documented least-privilege pair. A test asserts the
`states:` actions appear in the SFN policy and **not** in the execution policy.

**The engine lives on `cpcommon.transfer`, not `tscommon`.** SPEC-164→167 (send files) is the second
caller and SPEC-168→172 (archive) the third; SPEC-156 already settled that `cpcommon` owns the
algorithm while a domain layer owns its wording and key layout. `tscommon.copy` was **deleted**, not
wrapped — a re-export shim is the deliberate twin that spec exists to prevent. Table-share keeps the
manifest **key layout** (`copy_plan.transfer_manifest_key`) and every user-facing sentence.

**S3 Batch Operations is rejected, not deferred** — see the amendment on the *Table Share* entry
above. The refusal is a property of the API (`TargetKeyPrefix` prepends to the full source key; 5 GB
per object; one destination bucket per job), not of the implementation it was proposed to replace.

**The caps did not move.** 160 changes the mechanism and nothing a user can see: same push, same
conflict rules, same notifications, same `SHARE_MAX_*`. That ordering is deliberate — a regression in
a new engine must not be able to hide behind a new limit. SPEC-161 raises the ceiling.

**Two numbers live in two places, and a test holds them together.** `MAX_ITEMS_PER_BATCH` (50) and
`MAP_MAX_CONCURRENCY` (20) are read by the batch verb from `cpcommon/transfer/config.py` and by the
rendered ASL from `locals.tf`, because Terraform cannot import Python. The batch size is sized
against S3's *worst case* — two 1024-byte keys and two 63-byte bucket names put an item near 2.3 KB,
so 50 items sit under half the 256 KB child-execution input limit — and that bound is **computed in
a test**, not asserted as a number.
