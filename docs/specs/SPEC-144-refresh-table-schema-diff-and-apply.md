---
type: Spec
id: SPEC-144
title: "Refresh Table — Schema Diff & Apply"
description: "Adds the refresh pipeline's schema diff, classifying changes as additive, retyped or removed and refusing column removals unless the request opts in, naming the columns in a notification."
spec_status: Completed
depends_on: [SPEC-143, SPEC-069, SPEC-070, SPEC-111, SPEC-114]
arc: refresh-table
arc_order: 2
---

**Dependency notes:** SPEC-143 (the `mode` branch, `load-table-definition`, and the normalised state this spec diffs against), SPEC-069 (polars inference — reused unchanged), SPEC-070 (`cpcommon.athena.run_ddl` and the terminal-state pair), SPEC-111 (the drop-and-recreate precedent — data-quality's temp tables), SPEC-114 (`TerminalError.tokens` and the notification-is-the-completion-channel rule)
> **Reference:** `docs/architecture.md` → *Control Planes → Table Builder* (DDL + projection). Second of the refresh-table arc (143 → **144** → 145).
>
> **What 144 ships:** the two states that replace SPEC-143's `not_implemented` stub — `diff-schema`, which compares the freshly inferred columns against the table's existing ones and decides whether the change is permitted, and `apply-refresh`, which rebuilds the table. Together they make the feature real. The browser still cannot request one; SPEC-145 does that.
>
> **The one decision to read before anything else is FR-003.** The requirement was *warn about removals, then require explicit confirmation.* The obvious implementation — a dry-run that returns a diff and waits — does not fit this architecture: the control plane is fire-and-forget, results arrive as notifications, and there is no synchronous channel to return a preview on. Two designs were considered and rejected in favour of a third; FR-003 records all three, because the rejected ones are the ones a later reader will propose.
>
> **This spec does more message-layer work than it looks like it should**, and FR-009 explains why: `tbcommon/messages.py` is a *failure* table whose renderer hard-codes `Couldn't create table "{name}": …`, `success_message` takes no reason and hard-codes *"is ready to query"*, and `emit_failure` never reads `TerminalError.tokens`. Every one of those is correct for a plane that only ever created tables, and every one of them is in the way now.
>
> **Rulebooks:** `lambdas/info/best-practices/lambdas/lambdas.md`.

## Overview

At this point in the pipeline the system knows two schemas: the one the table currently declares, threaded forward by `load-table-definition`, and the one the data now implies, freshly inferred by `infer-schema` from a bounded read of the folder's files. This spec is about the gap between them.

Most of the time the gap is additive — someone added columns — and the right behaviour is to apply it without ceremony. Sometimes a column's type has widened or a source file changed shape and a column is now typed differently. And sometimes a column is simply gone, which is the case that deserves friction, because removing a column from a table is not a cosmetic change: any saved query, view, or dashboard that references it starts failing, and the failure surfaces somewhere the person who ran the refresh is not looking.

So the diff is classified, not just computed, and one class of change — removal — is refused unless the request explicitly opted into it. The refusal is the warning: it names the columns, in the notification, and changes nothing. The user then re-runs with the opt-in set.

The apply itself is a drop and a recreate. The table is external, so the data is never touched; what is dropped is a catalog entry that this pipeline can regenerate exactly, from the definition it is holding.

---

## Scope

### In Scope

- **A new verb `table-builder-diff-schema`** — classifies the change into added / removed / retyped / unchanged, enforces the removal opt-in, and **emits the no-change notification** (FR-002).
- **`allowRemovals`** on the request envelope — a boolean, default `false`, validated in `validate-authorize`, meaningful only when `mode == "refresh"`.
- **A new verb `table-builder-apply-refresh`** — regenerates the create statement from the preserved definition plus the new columns, and applies it as `DROP TABLE` followed by `CREATE EXTERNAL TABLE`, both through Athena.
- **A short-circuit on a no-op refresh** — an unchanged schema succeeds without issuing any DDL.
- **`glue:DeleteTable`** added to the table-builder execution role's permission policy.
- **`cpcommon.ddl` gains a `no_if_not_exists` option and a `table_properties` passthrough** so `apply-refresh` reproduces the table it is replacing rather than one that merely resembles it, and so a failed drop cannot be masked (FR-004).
- **`RecordSuccess` becomes mode-aware** — it hard-codes `"status": "created"` today.
- **A refresh-aware message layer** in `tbcommon` — a second failure prefix, a refresh success variant, and a `tokens` channel.
- **The `columns_removed` notification carries an in-app link** whose query string names the removed columns, which is what makes SPEC-145's dialog able to show them (FR-009).
- **Deploy-matrix rows and observability** for both verbs.

### Out of Scope

- **Any browser surface** — SPEC-145.
- **Preserving `TBLPROPERTIES` beyond what `clone_definition` captured.** Its `_EXCLUDED_PARAMETERS` list is the filter and it is not changed here.
- **Reordering columns to match source file order.** The rebuilt column list is the newly inferred list, in inference order. Safe for the formats in play — Parquet and JSON resolve by name, CSV via OpenCSVSerde resolves positionally but is re-inferred from the same files in the same order. Called out because "the columns moved" is a plausible bug report with a boring cause.
- **Atomic replacement.** There is a window, typically a second or two, in which the table does not exist. FR-006 bounds it rather than pretending otherwise.
- **Rolling back a failed recreate.** FR-006 covers what the user is told.
- **Changing partition keys** — SPEC-143 FR-005 reconstructs them and never re-derives them.

---

## Functional Requirements

### FR-001: `diff-schema` classifies the change

#### Description

A pure comparison of two column lists, matched by name.

**AMENDED DURING BUILD (2026-08-04): the match is CASE-INSENSITIVE, reversing this FR as first written.** The original premise — that Athena treats `Amount` and `amount` as distinct — is not what this pipeline sees. The create path issues `CREATE EXTERNAL TABLE` through Athena, whose Hive-backed DDL **folds column names**, so a CSV header of `Amount` is stored in Glue as `amount`. Neither side normalises: `infer-schema` reads the header verbatim, `load-table-definition` reads Glue verbatim. Case-sensitively, **every column of every mixed-case table would be reported as both added and removed** on a folder where nothing changed — firing FR-003's data-loss warning over the user's entire schema — and it would be unescapable, because opting into the removal rebuilds with `Amount`, Athena folds it again, and the next refresh repeats it. The repo already recorded the correct behaviour in two places (`pre-signup/test_pre_signup.py`, `control-plane-common/test_state_machines_cpcommon.py`). A true rename (`amount` → `total`) is still caught; the only undetectable change is a pure case change, which under those semantics is not a change. Names are **reported** as they appear.

#### Acceptance Criteria:

- [ ] The verb reads `existingColumns` (from `load-table-definition`) and `columns` (from `infer-schema`) off the threaded state and emits `diff`.
- [ ] `added` = names in the new list absent from the existing list, with their new types.
- [ ] `removed` = names in the existing list absent from the new list, with their existing types.
- [ ] `retyped` = names in both whose Hive type differs, each carrying `from` and `to`.
- [ ] `unchanged` is a count, not a list — it is the one part of the diff nobody needs by name and it would dominate the state payload.
- [ ] **`compute_diff` excludes partition-key names itself.** It must not assume an upstream verb did: `infer_schema.py` sets `out["columns"] = columns`, the **full** inferred list, and the partition-collision drop happens inside `build_create_table_ddl` (affecting only the DDL body), so a colliding column *does* reach this verb. A test pins this with a partitioned fixture whose data files carry a column named after a partition key.
- [ ] The diff is a pure function with no AWS calls, tested directly against column-list pairs.

### FR-002: A no-op refresh succeeds without DDL, and says so

#### Description

The most common refresh, once users get in the habit, will find nothing to do. That must be cheap, must not drop the table, and must be legible — "nothing changed" is a useful answer, not a failure. It also needs an owner: the state machine has **no notification state**, every notification in this plane is emitted in-Lambda, and on this path no Lambda runs after `diff-schema`. So `diff-schema` emits it.

#### Acceptance Criteria:

- [ ] When `added`, `removed` and `retyped` are all empty, `diff-schema` emits `changed: false` and a `Choice` routes past `ApplyRefresh` straight to `RecordSuccess`.
- [ ] **`diff-schema` emits the `unchanged` notification itself** before returning, through the same best-effort `cpcommon.notify` path every other emit uses (never raises, no-op without `NOTIFICATIONS_QUEUE_URL`).
- [ ] No `DROP TABLE` and no `CREATE` is issued on this path — a test asserts `run_ddl` is never called.
- [ ] The wording distinguishes "no changes found" from "table updated". A refresh that looks identical to one that changed nothing is how a user concludes the button is broken.
- [ ] `apply-refresh` owns the `refreshed` notification on the changed path, mirroring `execute_ddl.py`'s `emit_created`. A test asserts exactly one notification is emitted per run on each path.

### FR-003: Removals require an explicit opt-in, and the refusal is the warning

#### Description

**The mechanism.** `allowRemovals` is a boolean on the request. When `diff.removed` is non-empty and `allowRemovals` is false, the run ends as a terminal failure carrying the removed column names, and **nothing is changed**. The user reads the notification, which names the columns, and re-submits with the opt-in set.

**Two rejected designs, recorded so they are not re-proposed.**

*A plan-then-apply pair.* Run one writes a plan artifact into the user's own prefix (as data-quality writes reports), notifies, the user opens it and clicks Apply, run two references the plan. The textbook shape, and it costs a new artifact, a new index, a new view, a new IAM surface and two async round trips for what the user experiences as one button. Rejected as disproportionate.

*A browser-side preview.* The browser can already read the table's Glue columns and list the folder's objects. It cannot infer types — that needs polars over a bounded Parquet footer or CSV head, which is why `infer-schema` exists and carries a 240 MB layer. A preview showing added columns with guessed types would be a preview of something other than what the apply will do. Rejected.

**What the chosen design does and does not guarantee.** It guarantees that the *specific columns* are named to the user before any removal happens, in a durable notification. It does **not** guarantee the user read that notification before ticking the box — SPEC-145's dialog always requires an explicit tick with explicit consequence copy, and shows the specific names when it can (via FR-009's link). That is the honest statement of the safety property, and it is stated here rather than overclaimed.

#### Acceptance Criteria:

- [ ] The envelope accepts `allowRemovals?: boolean`, defaulting to `false`, **validated in `validate-authorize`** alongside `mode`, and rejected with `TerminalError("removals_flag_not_applicable")` when `mode != "refresh"` and the flag is `true`.
- [ ] `validate-authorize` emits `allowRemovals` on its output payload, normalised to a boolean.
- [ ] `diff.removed` non-empty and `allowRemovals` false raises `TerminalError("columns_removed")` with the removed column names in the error's `tokens` (FR-009 makes `tokens` actually reach the message).
- [ ] The notification names every removed column, up to 20 with an "and N more" tail, and states plainly that nothing was changed.
- [ ] `diff.removed` non-empty and `allowRemovals` true proceeds to `ApplyRefresh`.
- [ ] A test asserts that on the `columns_removed` path `run_ddl` is never called and the table's definition is untouched.
- [ ] `allowRemovals` is **not** persisted anywhere — not on the table, not in a registry, not in an index. A test greps for it outside the request path.

### FR-004: `apply-refresh` rebuilds the table from the preserved definition

#### Description

The statement is regenerated, not patched. Everything except the data columns comes from SPEC-143's capture. `ALTER TABLE ADD COLUMNS` was considered and is not used — it cannot retype, cannot remove, and behaves inconsistently across the three SerDes in play, so it would be a fourth code path covering only the easiest case.

**WHAT A DROP + CREATE COSTS, raised during build (2026-08-04) and recorded rather than hidden.** The rebuild replaces the *catalog entry*, so anything Glue holds that SPEC-143's capture does not carry is destroyed: the table's `CreateTime` and identity, its `Description`/`Owner`, and any Lake Formation grant made **directly on the table** rather than through the `portal-managed` tag. **Column comments were the one loss a user would actually notice, and they are now carried** — `clone_definition` captures them, `load-table-definition` threads them, and `apply-refresh` re-attaches each surviving column's comment by folded name before rendering. Inference returns names and types; it has nothing to say about what a column *means*, so a comment is metadata only the old table holds.

**The alternative this FR did not weigh is `glue:UpdateTable`**, which replaces the definition in place: no window in which the table does not exist, table identity preserved, and it handles the retype and remove that `ALTER` cannot. Its cost is that it bypasses the Athena DDL path SPEC-070 chose deliberately ("the same LF-enforced create path users already exercise"), needs a new IAM action, and needs its own verification story. **Filed as its own spec rather than amended in here** — and it matters most if the portal ever moves to Iceberg, where a drop-and-recreate destroys snapshot history and time travel, which is most of the reason to choose Iceberg at all. Nothing in the repo uses Iceberg today, so there is no lineage to lose yet; the point is not to entrench a path that makes that migration worse.

Two details in `cpcommon/ddl.py` need care because its real shape differs from what a reader would assume. Its `storage` parameter is **not** a bag of SerDe fields — it is a `Storage` NamedTuple of `(clause: str, tblproperties: tuple[tuple[str, str], ...])`, where `clause` is the **pre-rendered** `ROW FORMAT SERDE … STORED AS INPUTFORMAT …` text. And the builder emits `CREATE EXTERNAL TABLE **IF NOT EXISTS**`, which on this path is actively dangerous: after a drop that silently did not take, `IF NOT EXISTS` turns the recreate into a successful no-op and the user is told their table was refreshed when its schema is unchanged.

#### Acceptance Criteria:

- [ ] `apply-refresh` builds a `cpcommon.ddl.Storage` from SPEC-143's `storage` state via a new `storage_from_definition` helper, living in `cpcommon/ddl.py` beside `Storage` so the renderer and the shape it renders into cannot drift.
- [ ] **`storage_from_definition` is pinned by a round-trip test, not by inspection.** For each of the three formats the create path builds, the `Storage` it produces from that table's *captured* definition must equal the `Storage` the create path's own format map produces. Two known traps make this more than a formality: the shipped `CSV_OPEN_SERDE` clause writes `'escapeChar'='\\'` in DDL source, which Hive unescapes and Glue reads back as a single `\` — so a verbatim re-render produces `'escapeChar'='\'`, a different statement; and Parquet's shipped clause is the short `STORED AS PARQUET`, while rendering from the captured input/output formats yields the long `STORED AS INPUTFORMAT … OUTPUTFORMAT …` form. Equivalent to Athena, textually different, and the round-trip test is what forces both to be handled rather than discovered.
- [ ] Where the captured definition matches a known format, `storage_from_definition` returns the **create path's own clause** for that format; the rendered long form is the fallback for anything it does not recognise. **Sharpened during build (2026-08-04): the shortcut is taken only when the capture REALLY IS that clause**, parameters included. Matching on the SerDe library alone would rebuild a tab-separated table with `separatorChar=','` and would rebuild a Hive-JSON table with the OpenX SerDe this repo documents as potentially non-deterministic around nulls — both are captures a hand-created table can present, which FR-004 explicitly keeps in scope. This keeps the two paths producing one statement rather than two that happen to behave alike.
- [ ] `build_create_table_ddl` gains **`if_not_exists: bool = True`**. The create path keeps the default and its existing tests pass unmodified; `apply-refresh` passes `False`. A test asserts the refresh statement contains no `IF NOT EXISTS`.
- [ ] `build_create_table_ddl` gains **`table_properties: dict | None = None`**, merged with `Storage.tblproperties`, so the captured `skip.header.line.count` and any other surviving property are reproduced. **Corrected while building SPEC-143 (2026-08-04): `portal.managed` is NOT among them and must not be.** `clone_definition` strips the marker into `_EXCLUDED_PARAMETERS` (SPEC-143 FR-007 AC2), so it never reaches the captured properties. It is re-emitted instead by `build_create_table_ddl`'s own `mark` argument, which defaults to `True` — so a refresh, which supplies a `storage=` but not `mark=False`, re-marks the table it rebuilds. That default is the reason `mark` is a separate argument rather than inferred from `storage is None`: under the inferred rule every refreshed table would come back **unmarked**, erasing the record on exactly the tables most likely to be asked about.
- [ ] **A test asserts a refreshed table is still `portal.managed`.** `apply-refresh` is a `DROP` + `CREATE`, so the marker survives only because the rebuild re-emits it.
- [ ] **`projection.*` and `projection.enabled` are stripped from `table_properties` before the merge.** `clone_definition` copies *all* Glue `Parameters`, so a partitioned table's captured properties always include them, and `_tblproperties` regenerates the same keys from the reconstructed partition keys — merging naively emits every projection key **twice** inside one `TBLPROPERTIES (…)`. A test asserts a partitioned refresh emits each `projection.*` key exactly once, and that the emitted values match the regenerated ones.
- [ ] `EXTERNAL` is **not** a table property and is never written back — `clone_definition._EXCLUDED_PARAMETERS` already strips it, and it is expressed by `CREATE EXTERNAL TABLE`. Neither is `transient_lastDdlTime`.
- [ ] The verb issues `DROP TABLE IF EXISTS {db}.{table}` then the create, as **two** `cpcommon.athena.run_ddl` calls in that order, each polled to a terminal state before the next begins.
- [ ] Athena output goes to **the same location the create path uses** — reuse `execute_ddl`'s own output-location construction (helper or verbatim expression) rather than re-deriving it from this spec's prose. The shape `s3://{space.bucket}/{space.database}/athenaresults/{actor}/` is illustrative for a shared space; the create path's code is authoritative for both space kinds, and a test asserts the two verbs produce the same `OutputLocation` for the same threaded state.
- [ ] Identifiers are quoted through `cpcommon.ddl.quote` (backticks); a test covers a table name that is a reserved word.
- [ ] Athena throttling raises `TransientError` and is retried by the state machine; a failed drop raises `TerminalError("drop_failed")`; a failed create raises `TerminalError("recreate_failed")`; a timeout raises `TerminalError("ddl_timeout")`.
- [ ] **A post-condition read.** After the create, the verb calls `glue.get_table` and asserts the table exists and its COLUMN NAME SET matches what the statement declared; a mismatch raises `recreate_failed`. **Corrected during build (2026-08-04): comparing a COUNT against `len(columns)` is wrong** — `build_create_table_ddl` drops a data column colliding with a partition key while `infer-schema` emits the full list, so a perfectly good rebuild of a partitioned table looked short by one and reported *"the old table was removed and could not be rebuilt"* on a table that was exactly right. The name set costs the same and also catches a rebuild that landed against a stale catalog entry. **The read is TERMINAL, never transient**, including on a throttle: the drop and create are committed, so a retryable verification would re-run the destructive pair because a read failed. SPEC-135's lesson — this plane's canonical failure was a verb that *completed* while the table was not created (four PRs, #243–246) — is why this is checked rather than assumed.
- [ ] Raw Athena `StateChangeReason` never reaches the user (SPEC-106 FR-008); it is logged as a field and mapped to the reason code.
- [ ] On success the verb emits `status: "refreshed"` and the applied column count.

### FR-005: IAM

#### Acceptance Criteria:

- [ ] `infra/modules/table-builder/policies/execution.json.tftpl` gains `glue:DeleteTable` on the same `catalog` + `database/*` + `table/*/*` resources as the existing Glue actions.
- [ ] The **existing** explicit `Deny s3:DeleteObject` (Sid `NoDataObjectDelete`) is untouched, and a comment records why it is safe alongside a `DROP TABLE`: the table is external, so dropping it removes a catalog entry and no objects. **This is the property the whole design rests on.** If a future change makes a table-builder table non-external, this apply becomes destructive and must be revisited.
- [ ] Lake Formation needs **no change** — the `portal-managed` tag-policy grants already give every control-plane role `DROP` at both DATABASE and TABLE level (`infra/modules/analytics/lakeformation.tf`). A comment records this so the next reader does not go looking for a missing grant.
- [ ] `aws iam simulate-custom-policy` confirms the execution role can `glue:DeleteTable` on a table in a user database and cannot delete any S3 object.

### FR-006: The replacement window is bounded and its failure is legible

#### Acceptance Criteria:

- [ ] ~~The window is serialized against other table-builder work on the same database by the existing FIFO `MessageGroupId`.~~ **FALSE, corrected during build (2026-08-04) — the guarantee does not exist.** The Pipe invokes `StartExecution` as `FIRE_AND_FORGET` (`infra/modules/table-builder/pipe.tf`), so a message is done when the execution STARTS, not when it finishes: the group id serializes DELIVERY, not EXECUTION, and two requests on one database run concurrently. A second refresh reaching `GetTable` inside the drop window sees `table_not_found`; a racing `CREATE` (now without `IF NOT EXISTS`) surfaces as `recreate_failed` on a table that exists. **Accepted for now and recorded as owed** (user decision, 2026-08-04): refresh is not browser-reachable until SPEC-145, which is the gate to revisit it, and the alternative — a synchronous Pipe target — changes throughput and timeout behaviour for every CREATE on a plane that is otherwise working. What actually bounds the damage is narrower: the two statements are issued back to back with nothing between them, and both carry an idempotency token so a Retry re-attaches instead of re-dropping.
- [ ] **A committed drop followed by exhausted retries notifies nobody, and that is recorded rather than fixed here** (added 2026-08-04). `notifies_on_failure` deliberately stays quiet on `TransientError` — right for a create, wrong once a destructive statement has landed — and `RecordFailure` is a `Pass` state with no notification path. This is a pre-existing gap for EVERY verb on this plane; the novelty is only that this one has a committed side effect. **Owed:** decide the mechanism once the live check has exercised the real failure modes.
- [ ] **Both statements carry an Athena `ClientRequestToken`** derived from the `requestId` (added 2026-08-04). Without one, a Step Functions Retry after a transient error that arrived *after* submission runs the statement a second time — on this pair, that is a retry dropping the table it just rebuilt. `cpcommon.athena.start_query` has carried this warning since SPEC-111; `run_ddl` simply never offered the parameter.
- [ ] **The two statements share ONE poll budget** (added 2026-08-04). Two independent 240 s caps inside a 300 s function would let Lambda be killed BETWEEN the drop and the create — table gone, and no notification at all, because the process dies before `notifies_on_failure` can run.
- [ ] The two DDL calls are issued back to back; a test asserts no S3, Glue or SQS call occurs between the drop and the create.
- [ ] The `recreate_failed` notification states explicitly that **the table was removed and could not be rebuilt**, names the database and table, and tells the user their files are untouched and the table can be rebuilt from the Files browser. It does not say "refresh failed" — a user who reads that will assume nothing happened, and something did.
- [ ] `recreate_failed` logs the full generated DDL as a field (schema, not file contents — permitted by the field rule) so an operator can reproduce it by hand.
- [ ] A test simulates a create failure after a successful drop and asserts the reason and its distinct wording.

### FR-007: State machine wiring

#### Acceptance Criteria:

- [ ] SPEC-143's `not_implemented` stub is deleted and the second `Choice`'s refresh target becomes `DiffSchema`.
- [ ] `DiffSchema → Choice($.diff.changed) → {true: ApplyRefresh, false: RecordSuccess}`.
- [ ] `ApplyRefresh → RecordSuccess`.
- [ ] **`RecordSuccess` is changed.** It hard-codes `"status": "created"` today; it must carry `"created"` on the create path and the verb-supplied `"refreshed"` / `"unchanged"` on the refresh path. Threading `$.status` through the Pass result is the change; a test asserts the create path still reports `"created"`.
- [ ] Both new Task states carry the uniform `Retry` block with the `Lambda.`-prefixed error names and the `Catch: States.ALL → ResultPath $.error → RecordFailure`.
- [ ] No state decodes `$.error.Cause` — SPEC-143's rendered-ASL assertion still passes.

### FR-008: Infrastructure, deploy matrix and observability

#### Acceptance Criteria:

- [ ] `table-builder-diff-schema` (15 s / 256 MB) and `table-builder-apply-refresh` (300 s / 512 MB, mirroring `execute-ddl`) are added to `infra/modules/table-builder/locals.tf`'s function map. **`lambda.tf` needs no edit** — it is `for_each` over that map — but **`stepfunction.tf` does**: its `templatefile()` call passes an explicit per-function `_function_arn` map, so both new states need keys there or the template fails at plan time.
- [ ] Both carry the full common environment block; the `_require` assertion covers them.
- [ ] Matrix rows: `{ name: table-builder-diff-schema, layer: false, polars: false, tbcommon: true, cpcommon: true }` and the same for `table-builder-apply-refresh`. `lambdas/test_deploy_matrix.py` passes.
- [ ] `@observability.traced` is the outermost decorator on both, above `@notifies_on_failure`.
- [ ] `diff-schema` logs `added_count`, `removed_count`, `retyped_count`, `unchanged_count`, the added and removed **names**, `allow_removals` and `request_id`. Column names are schema and are permitted; **no column values, no sampled rows.**
- [ ] `apply-refresh` logs the generated DDL, both Athena query execution IDs, and the post-condition result.
- [ ] Both functions are picked up by `test_instrumentation_coverage.py`'s handler sweep; the table-builder `Plane`'s hard-coded `verb_count` literal is bumped **by two** (to 8, after SPEC-143's bump to 6) — `PLANES` carries a count, not a verb list, and `test_the_enumeration_actually_found_the_verbs` asserts it.

### FR-009: The message layer learns to talk about refreshes

#### Description

`tbcommon/messages.py` was built for a plane that only created tables, and three of its properties are now obstacles rather than defects. `_BODIES` is a failure table and `failure_message` renders every entry as `Couldn't create table "{name}": {body}` — so a refresh failure would read *"Couldn't create table sales_2026: this table is a view"*. `success_message(table_name, database)` takes no reason and hard-codes *"is ready to query"*. And `emit_failure` calls `failure_message(err.reason, …)` without ever reading `err.tokens`, which `cpcommon/errors.py` documents as deliberate — tokens exist so that table-builder and table-share, *"whose message tables carry no per-request markers,"* stay untouched. FR-003 needs exactly that channel.

#### Acceptance Criteria:

- [ ] `failure_message` takes the request's `mode` and selects the prefix: `Couldn't create table "{name}"` or `Couldn't refresh table "{name}"`.
- [ ] **The `unauthorized` / `forbidden` short-circuit is made mode-aware too.** `failure_message` returns `"You don't have access to create a table here."` for those two reasons **before** any prefix is chosen, so a refresh refused by `_authorize_space` — which is the ordinary outcome of a stale rail cache — would tell the user they cannot *create* a table they were trying to refresh. A test covers both reasons in both modes.
- [ ] `success_message` gains a refresh variant covering `refreshed` (naming the counts) and `unchanged`.
- [ ] `emit_failure` passes `err.tokens` into `failure_message`, and bodies may reference them by name. Bodies with no token references are rendered identically to today — a test asserts every existing table-builder failure message is byte-for-byte unchanged.
- [ ] `_BODIES` gains entries for `columns_removed`, `drop_failed`, `recreate_failed` (FR-006's distinct wording), `removals_flag_not_applicable`, `cannot_refresh_view`, `cannot_refresh_managed_table`, `cannot_refresh_catalog_partitioned`, `cannot_refresh_location_unsupported`, `table_not_found`, `table_outside_space`, `projection_not_reconstructable`, `format_changed` and `definition_too_large`.
- [ ] Every reason code is registered with `cpcommon.messages.register_reasons` so `TerminalError` validates at raise time.
- [ ] The dedup token is one per **outcome**, not per verb (SPEC-114): `"{requestId}:refresh"`.
- [ ] **The `columns_removed` notification carries a `link`** of the form `/query?refreshTable={database}.{table}&removed={comma-separated names}`. **Correction (2026-08-04, during build): only `database` and `table` are catalog-safe identifiers — COLUMN NAMES ARE NOT.** `infer-schema` takes them verbatim from a CSV header or a polars schema and `load-table-definition` copies them out of Glue; nothing validates them. A header of `Order ID` puts a raw space in the URL, one containing `&` invents a query parameter, one containing `#` truncates the rest into a fragment. **Each name is therefore percent-encoded individually**, keeping the comma as the separator, and SPEC-145 FR-005 is corrected not to re-validate them as identifiers. The link passes `isSafeInAppPath` (SPEC-061); a test asserts it does. This is what lets SPEC-145's dialog name the specific columns without a new AWS call, and it is specified here because this spec owns the message layer.
- [ ] **The link needs a channel that does not exist yet, and building it is part of this FR.** `cpcommon.notify.emit_notification` accepts `link=`, but `tbcommon.notify.emit_failure` never passes one and `TerminalError` has no link field. `emit_failure` therefore **constructs** the link itself for the `columns_removed` reason, from the database and table it already holds plus `err.tokens` — rather than `TerminalError` growing a transport field it would carry for one caller. A test asserts the link reaches `emit_notification` and that every other failure reason still emits with `link=None`. **SPEC-145 FR-005 rests entirely on this criterion**; if it is dropped, that spec has no way to name the columns.
- [ ] The link's `removed` list is capped at 20 names to bound the URL, and the message body is capped the same way with an "and N more" tail. **Both come from one helper (`messages.removed_tokens`)**, which returns the display string and a JSON-encoded name list as separate tokens: re-splitting the display string would put the literal tail `and N more` into the URL as though it were a column, and would mangle any name containing the separator.
- [ ] No raw AWS text appears in any body.

### FR-010: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run lint` and the Python suite pass.
- [ ] Tests cover: the diff across added / removed / retyped / unchanged / all-four-at-once; partition-key exclusion **inside `compute_diff`** with a colliding-column fixture; the no-op short circuit issuing no DDL and emitting exactly one notification; `columns_removed` blocking with names in `tokens` and issuing no DDL; the link's shape, its `isSafeInAppPath` result, and that it reaches `emit_notification` while every other reason emits `link=None`; the opt-in proceeding; `removals_flag_not_applicable`; **the `storage_from_definition` round trip per format**; **each `projection.*` key emitted exactly once on a partitioned refresh**; the absence of `IF NOT EXISTS` on the refresh statement and its presence on the create statement; drop-then-create ordering; the post-condition mismatch raising `recreate_failed`; `drop_failed`; throttle → `TransientError`; a reserved-word table name; `unauthorized` / `forbidden` wording in both modes; `RecordSuccess` still reporting `"created"` on the create path; and every existing table-builder failure message unchanged.
- [ ] **The casing premise is confirmed in the live check** (added 2026-08-04): build a table from a CSV whose header carries a mixed-case name such as `Amount`, then `GetTable` and read back what Glue actually stored. If it comes back folded, FR-001's amendment is confirmed; if it comes back verbatim, the fold is harmless but the reasoning should be corrected. No unit test can settle this — the fixtures on both sides are written by us.
- [ ] A live check is owed and recorded in the delivery doc: build a table from a CSV folder, add a file with a new column, refresh, confirm the column appears and the data is queryable; remove a column from the source, refresh, confirm the block and its named columns and the link; then refresh with the opt-in and confirm the column is gone.

---

## Data Model

```jsonc
// SQS body — extends SPEC-143's envelope with one field.
{
  "idToken": "...",
  "mode": "refresh",
  "allowRemovals": false,      // NEW. default false; validated in validate-authorize
  "space": { "kind": "personal", "bucket": "...", "prefix": "...", "database": "alice" },
  "tableName": "sales_2026",
  "partitionKeys": [],
  "requestId": "<uuid>"
}
```

```python
# Threaded state added by validate-authorize (not diff-schema — it is a request field).
{"allowRemovals": False}

# Threaded state added by table-builder-diff-schema.
{
    "diff": {
        "changed": True,
        "added":   [{"name": "channel", "type": "string"}],
        "removed": [{"name": "legacy_id", "type": "bigint"}],
        "retyped": [{"name": "amount", "from": "int", "to": "bigint"}],
        "unchanged": 14,                       # a count, never a list
    },
}

# Threaded state added by table-builder-apply-refresh.
{
    "status": "refreshed",                     # "refreshed" | "unchanged"; threaded into
                                               #   RecordSuccess, which hard-codes "created" today
    "appliedColumnCount": 16,
    "ddl": "CREATE EXTERNAL TABLE `alice`.`sales_2026` (...)",   # no IF NOT EXISTS
}

# Terminal reasons added by this spec:
#   removals_flag_not_applicable
#   columns_removed          # carries the removed names in TerminalError.tokens
#   drop_failed
#   recreate_failed          # the table is gone and was not rebuilt — distinct wording
# Terminal reason removed by this spec:
#   not_implemented          # SPEC-143 FR-008's stub
```

---

## API / Interface Contract

```python
# lambdas/control-plane-common/cpcommon/ddl.py — extended, not replaced.
# NOTE the SHIPPED shape: `Storage` is a NamedTuple carrying a PRE-RENDERED clause,
# not a bag of serde fields, and the second positional is `table_name`.

class Storage(NamedTuple):
    clause: str                                    # rendered ROW FORMAT / STORED AS text
    tblproperties: tuple[tuple[str, str], ...]


def storage_from_definition(storage_state: dict) -> Storage:
    """NEW. Turn SPEC-143's captured {serializationLibrary, parameters, inputFormat,
    outputFormat} into a Storage.

    Where the captured definition matches a format the create path knows, RETURN THE
    CREATE PATH'S OWN CLAUSE — do not re-render it. Two reasons, both measured:
    CSV_OPEN_SERDE writes `'escapeChar'='\\\\'` in DDL source, which Hive unescapes and
    Glue reads back as one backslash, so a verbatim re-render is a DIFFERENT statement;
    and Parquet's shipped clause is the short `STORED AS PARQUET` while the captured
    formats render as the long INPUTFORMAT/OUTPUTFORMAT form. The long form is the
    fallback for anything unrecognised. Pinned by a round-trip test per format.
    """


def build_create_table_ddl(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str,
    location: str,
    storage: Storage | None = None,
    *,
    if_not_exists: bool = True,        # NEW — apply-refresh passes False
    table_properties: dict | None = None,  # NEW — captured props, merged with Storage's.
                                       # CALLER MUST STRIP projection.* first: clone_definition
                                       # copies all Glue Parameters, and _tblproperties
                                       # regenerates the same keys from partition_keys.
) -> str:
    """`if_not_exists=False` matters more than it looks: after a drop that silently
    did not take, IF NOT EXISTS turns the recreate into a successful no-op and the
    user is told the table was refreshed when nothing changed."""


# lambdas/table-builder-diff-schema/diff_schema.py

def compute_diff(
    existing: list[dict],
    inferred: list[dict],
    partition_key_names: set[str],
) -> dict:
    """Pure. No AWS calls. Matched by name, CASE-INSENSITIVELY (amended 2026-08-04 —
    Athena's Hive-backed DDL folds column names, so the create path's own output comes
    back lowercase; see FR-001). Names are REPORTED as they appear.

    It excludes partition-key names ITSELF. infer-schema emits the full inferred list;
    the partition-collision drop happens inside build_create_table_ddl and affects only
    the DDL body, so a colliding column does reach here.
    """
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/
├── control-plane-common/cpcommon/
│   ├── ddl.py                          # + storage_from_definition, if_not_exists, table_properties
│   └── messages.py                     # + reason codes
├── table-builder-common/tbcommon/
│   ├── messages.py                     # + mode-aware prefix, refresh success, tokens, new bodies
│   └── notify.py                       # emit_failure now passes err.tokens
├── table-builder-diff-schema/          # NEW
│   ├── diff_schema.py
│   └── test_diff_schema.py
├── table-builder-apply-refresh/        # NEW
│   ├── apply_refresh.py
│   └── test_apply_refresh.py
├── table-builder-validate-authorize/
│   └── validate_authorize.py           # + allowRemovals validation
└── test_deploy_matrix.py               # + two rows

infra/modules/table-builder/
├── locals.tf                           # + two functions (lambda.tf is for_each — no edit)
├── stepfunction.tf                     # + two _function_arn keys — an EXPLICIT map, not a loop
├── policies/execution.json.tftpl       # + glue:DeleteTable
└── state-machine.asl.json.tftpl        # - the stub, + DiffSchema, + Choice, + ApplyRefresh,
                                        #   + RecordSuccess threading $.status

.github/workflows/deploy-lambdas.yml    # + two matrix rows
```

## Implementation Phases

### Phase 1: The message layer

- Mode-aware `failure_message`, the refresh `success_message` variant, the `tokens` channel through `emit_failure`, and the new `_BODIES` entries.
- **Tests:** every existing table-builder failure message byte-for-byte unchanged — that is the gate for this phase; then the new bodies and the token substitution.

### Phase 2: The diff

- `allowRemovals` in `validate-authorize`; `compute_diff` and the `diff-schema` verb with its own partition-key exclusion, its `unchanged` notification, its `locals.tf` entry, matrix row and observability.
- Wire `DiffSchema` and its `Choice`; route the changed-true case to the surviving stub for now.
- **Tests:** the full diff matrix; the colliding-column fixture; `columns_removed` with tokens and the link; `removals_flag_not_applicable`; the no-op short circuit and its single notification.

### Phase 3: DDL regeneration and the apply

- `storage_from_definition`, `if_not_exists`, `table_properties`.
- `apply-refresh` with the post-condition read, its IAM (`glue:DeleteTable`), matrix row and observability.
- Delete the stub; thread `$.status` through `RecordSuccess`.
- **Tests:** regeneration for three formats; no `IF NOT EXISTS` on refresh and present on create; drop-then-create ordering; the post-condition mismatch; `drop_failed`; `recreate_failed` and its wording; throttle → `TransientError`; the create path still reporting `"created"`.

### Phase 4: Live check and closing out

- Run the FR-010 live check end to end and record the result in the delivery doc.
- Completion ritual: `INDEX.md` status, delivery doc, component-inventory rows, and a `decisions/` entry for the removal-opt-in mechanism — the two rejected designs and the honest statement of what the guarantee is and is not belong in that entry, not in `CLAUDE.md`, which gets one line. **No help-content change yet** — the feature is not user-reachable until SPEC-145.
