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

**COMPLETE:** "share a table across databases" — from the Query schema rail, copy a table's data files into recipient spaces under `shared_tables/{table}/` and create a clone table in each recipient DB (personal users and/or shared spaces). Its own **dedicated** async control plane (FIFO SQS+DLQ → Pipe → Standard SFN with a recipient `Map`, single-task Lambdas + `table-share-common`/`tscommon` layer, **one shared execution role** — creates tables via the `portal-managed` LF-Tag, not LF-admin status; SPEC-070/111 correction). SFN: validate-authorize (actor must have **source** access — personal=own DB, shared=active member) → inspect-source (**clone the source Glue table definition**, not re-infer; reject views/catalog-partitioned/non-external; cap object count+size) → Map(recipient): check-target-absent (fail-that-recipient on conflict, no overwrite) → copy-objects (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → create-table (repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Push** (no consent; recipient notified); **any shared space is a valid target** (sender needn't be a member — source access still gated); v1 sources = flat or projection-partitioned base external tables. UI = schema-rail per-table **"Share table"** (`features/table-share/` dialog + `useTableShare`, SPEC-093); **outcomes = SPEC-058 notifications** (sender per-recipient success/failure + whole-request failure; on success the recipient user / space **owner** is also told — `tscommon.notify`/`messages`, best-effort, `sqs:SendMessage` on the notifications queue only, SPEC-094). New browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`. Decision record: `docs/architecture.md` → *Control Planes → Table Share*. Do NOT build a consent/accept flow, schema re-inference, S3 Batch Ops, or catalog-partition-metadata copy in v1.

### Data-quality report view (SPEC-113)

The report is read at `/data-quality/:space/:requestId` — **the space is in the route, not derived**, because `requestId` alone cannot say which space holds `{space}/_data-quality-reports/{requestId}/report.json`. Resolution precedence: the actor's **own username always wins**; shared-space names are consulted only when the segment differs (SPEC-114's link builder pins the same rule). An unreachable space renders the friendly denied state and **issues no S3 request** — no existence oracle. The SPA's report types mirror `dqcommon/report.py` byte-for-byte; the banner **warns on `hasIncompleteFigures`** and only softly qualifies on `hasApproximateFigures`, which is true on every report the arc can produce. Detail: `spec-delivery/SPEC-113`.

### Data-quality outcome notifications (SPEC-114)

The notification **is** the completion channel — the browser never waits and the reports folder is hidden from the file browser, so a success message without a **link to `/data-quality/{space}/{requestId}`** would leave the report unreachable. The link builder mirrors SPEC-113's resolution precedence and returns **nothing** where the view would resolve the wrong space (a shared space named like the actor, a personal space that isn't theirs) — no link beats a permanent not-found. **Every figure this arc produces is approximate**, so a flat "some figures are estimates" rides every success message and the real warning is reserved for `hasIncompleteFigures`, the flag that varies. Failure covers three layers: `@notifies_on_failure` on every verb, the `NotifyFailure` state for what no verb can catch (import/SFN-level errors, decoded in Python — never in ASL), and **SPEC-126** for what never starts an execution at all. **One dedup token per outcome, not per verb** (`{requestId}:failure` / `:completed`): `NotifyFailure` runs after the execution has left the failing verb and cannot know which one raised, so a per-verb token would send two messages for one failure; the collapse relies on SQS FIFO's 5-minute window. `TerminalError` gained an optional **`tokens`** mapping — the user-facing inverse of `detail`, which stays raw and operator-only. **FR-005's CloudWatch alarms were removed, not deferred** (user decision): an alarm with no target, on one arc of five, told the user nothing. Detail: `spec-delivery/SPEC-114`.

### Data-quality runs index + dashboard (SPEC-123)

The `/data-quality` list is backed by a per-space **`index.json`**, not by listing the reports prefix — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives NO chronology, and building rows from the reports themselves costs one GET per row and gets slower the more the feature is used. `assemble-report` appends one small entry (the row's fields and nothing else) under **optimistic ETag CAS** with bounded retry, because checks of DIFFERENT locations run in parallel (the queue serializes only same-location checks) — the same lost-update fix SPEC-082 applied to the registry, duplicated in `dqcommon` because `casio` is in a layer the data-quality functions don't attach (**SPEC-125 did NOT merge it** — it folded the shared *client/config/JWT/notify* surface onto `cpcommon` and deliberately left the CAS retry loop domain-side, so this duplication is still open). The index is **capped at 200, oldest dropped first**, and every failure is **logged and swallowed**: the report is the artefact, the index is a convenience, so write order is report → notification → index, most durable to least. The page **aggregates across spaces** (this is "my checks", not "checks in one folder") and one unreadable space is skipped rather than blanking it. It lists **completed checks only**, and the footer line saying failures live in notifications was worded **"usually"** until **SPEC-126** closed the never-started-an-execution hole; it now says **"always"**. No new IAM. Detail: `spec-delivery/SPEC-123`.

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

Full account: `docs/spec-delivery/SPEC-149-refresh-table-in-place-rebuild.md`.
