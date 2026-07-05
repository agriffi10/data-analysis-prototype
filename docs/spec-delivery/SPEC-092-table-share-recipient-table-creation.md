# Completed Spec — SPEC-092: Table Share Recipient Table Creation & Terminal States

## What was completed?

- **Real `create-table`** (`table_share_create_table.py`): renders the SPEC-090 cloned definition as `CREATE EXTERNAL TABLE IF NOT EXISTS` with `LOCATION` repointed to `s3://{destBucket}/{destPrefix}`, runs it via Athena against the **recipient database** in the shared workgroup, polls to terminal. Results route to `s3://{destBucket}/{database}/athenaresults/{actor}/` (SPEC-055/070 convention). Athena `FAILED`/`CANCELLED` → `TerminalError("create_failed", StateChangeReason)`; poll-cap → `create_timeout`; throttle/5xx → `TransientError` (SFN retry). Replay-safe (`IF NOT EXISTS` + the SPEC-091 guard).
- **`tscommon.ddl.render_create_external`**: faithful clone DDL — columns (+ escaped comments), `PARTITIONED BY`, explicit `ROW FORMAT SERDE`/`WITH SERDEPROPERTIES`/`STORED AS INPUTFORMAT/OUTPUTFORMAT`, `TBLPROPERTIES` (projection props carried ⇒ no `MSCK`).
- **`tscommon.athena.run_ddl`** (+ `clients.athena()`): start+poll ported from the table-builder's proven `athena_run` (fake-clock seams for tests). `ATHENA_WORKGROUP` added to `tscommon.config` (required ⇒ in the COMMON Lambda env, PR #196 lesson).
- **SFN terminal states**: `RecipientSucceeded`/`RecipientFailed` now emit flat `{kind, name, status, reason?}` entries; new `ShapeSummary` Pass shapes the Succeed output `{actor, source, tableName, results:[…]}` — what SPEC-094 notifies from. Whole-request failures still land in `RecordFailure` (`{status:'failed', reason}`).
- **Execution role finalized**: + `glue:CreateTable`, Athena run/poll on the shared workgroup ARN, `lakeformation:GetDataAccess`, athenaresults read/write on both buckets (delete-deny unchanged). Role added to the **analytics LF admins list** (constructed ARN from root, compact()-safe) so Describe/CREATE resolve in the dynamic recipient DBs; `module.analytics depends_on module.table_share`.

## What changed from earlier specs?

- SPEC-088's create-table placeholder replaced — all five verbs are now real; SPEC-091's `target_not_readable` LF blocker is lifted by the LF-admin designation. The spec's illustrative per-recipient `outcome` shape was normalized to the SPEC-091 uniform `{kind, name, status:'ok'|'failed', reason:'slug: detail'}` (reason slugs, incl. `create_failed`, live in `reason`; no ASL string-splitting).

## Verification

19 new unit tests (12 create-table/DDL render/escaping + 7 athena start-poll outcome mapping) — full Lambda suite 311 green; `tofu validate` + rendered-ASL JSON/shape check. Live end-to-end proof (flat + projection share to user + space, conflict isolation) is deferred to the SPEC-093 UI session — the browser enqueue is the arc's real entry point and the first practical way to mint a valid actor token; recorded there. Backend-only (no Help change; the component inventory is SPA-only, so `tscommon.ddl`/`tscommon.athena` live in code + this doc, per the SPEC-091 precedent).
