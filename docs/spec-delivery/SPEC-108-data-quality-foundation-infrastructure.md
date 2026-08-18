# Completed Spec — SPEC-108: Data Quality — Foundation Infrastructure + `dqcommon` + Athena Workgroup

The dedicated async control plane for "check data quality on a file or folder" — plumbing
only, no behaviour. Shipped in two PRs: deploy-role IAM (#224) → applied → the module +
stubs + CI + smoke doc (#225).

No component-inventory rows (infra + Lambda stubs only — the inventory tracks app code,
matching the SPEC-088 precedent) and no Help-content change (nothing user-facing shipped).

## What was completed?

- **`infra/modules/data-quality/`** — FIFO request queue + FIFO DLQ (redrive,
  `maxReceiveCount = 3`, **content dedup OFF** — the producer's explicit
  `MessageDeduplicationId = requestId` is the dedup key); an EventBridge Pipe (SQS →
  SFN, `batch_size = 1`, FIRE_AND_FORGET) + role; a **Standard** Step Function + role;
  nine placeholder Lambdas on **one shared execution role**; 14-day log groups for every
  function + the machine.
- **The canonical state list is complete in the skeleton** (`state-machine.asl.json.tftpl`)
  — later specs *wire* states, none adds one. Two structural decisions are baked in on
  purpose:
  - **The Athena poll lives in the STATE MACHINE** (`StartProfileQuery → WaitForQuery(30s)
    → CheckQuery → Choice(QUEUED/RUNNING → loop)`), not inside a Lambda. table-builder's
    `execute-ddl` polls inside a 300 s Lambda — fine for a `CREATE TABLE`, fatal for a
    profiling query over 250 GB against Lambda's 900 s ceiling. A Standard execution runs
    for up to a year, so the time ceiling disappears. This is the whole reason the arc works.
  - **Every `Catch` reaches cleanup before `Fail`** (`ParseError → DropTempTablesOnFailure
    → RecordFailure → NotifyFailure → Fail`). The failure-path twin invokes the same
    `drop-temp-tables` Lambda (a state has one `Next`, hence the twin) and its own Catch
    goes straight to `RecordFailure` — cleanup is best-effort and must never mask the
    original error, and that is what stops the failure path looping into itself. Without
    it every failed request leaks a temp Glue table into the user's own database.
- **Nine Lambdas, explicit `timeout` AND `memory_size` each** (15 s/256 MB validator →
  300 s/1024 MB byte-scan). Recorded precedent: the shared-space verbs set `timeout = 60`
  but never set `memory_size`, leaving the AWS default of **128 MB** — it was the *memory*
  default left implicit, and an unset memory tier is invisible in the plan and shows up
  only as a production OOM. `notify-failure` is provisioned here as a placeholder and
  wired by SPEC-114 (the foundation-provisions / producer-wires pattern).
- **Layers** — `dqcommon` (domain surface only: `config` caps, `sql`, `report`,
  `messages`, `index_store` stubs; **no polars, no Excel engine, no PyJWT** — that lives
  once in `cpcommon`, SPEC-107 FR-001), attached to all nine **with `cpcommon`**; plus a
  **polars layer on `inspect-source` alone**, which is unavoidable because Athena requires
  an explicit column list for Parquet/JSON external tables and does not auto-detect a
  Parquet schema — the list comes from inspect-source's per-file probe, and reading a
  Parquet footer needs a Parquet reader. The SPEC-107 FR-004 **combined** size guard now
  covers `inspect-source` (cpcommon + dqcommon + polars) — the function it actually has to
  work for.
- **Dedicated Athena workgroup** `dat-prod-data-quality-wg` with
  **`bytes_scanned_cutoff_per_query` unset** (the portal workgroup's 10 GiB cutoff is 25×
  under a 250 GB check and would fail *every real check*) and
  `enforce_workgroup_configuration = false` (result location is per-query — a workgroup has
  one static location, so per-space routing is impossible otherwise). Comments record that
  this deliberately removes the project's only cost guardrail, and that **there is no
  workgroup query-timeout field**.
- **Config style settled for the arc:** per-deployment values are env vars validated at
  import (in `cpcommon.config`); `DQ_*` tuning caps are module constants in
  `dqcommon.config` (`DQ_MAX_OBJECTS`, `DQ_MAX_COLUMNS`, `DQ_SCAN_TOTAL_BYTES` = 2 GiB
  **per request**, never per file).
- **Deploy-role IAM** as a separate customer-managed policy (PR1, applied first);
  `states:ValidateStateMachineDefinition` isolated on `"*"`; log groups in both ARN forms.
  The Athena workgroup needed no new grant (the main policy already covers
  `workgroup/dat-*`), and `cpcommon`'s layer grant came from SPEC-107.
- **Smoke procedure** — `docs/testing/e2e.md`. The `check-query` stub returns
  `RUNNING` then `SUCCEEDED` off a `pollCount` it threads, so the loop **provably iterates
  once and terminates** with no Athena query in existence.

## What changed from earlier specs?

- The execution role is **logs-only** at this stage by design: S3 + the protected-object
  `Deny` land in SPEC-109, Glue/Athena/LF-admin in SPEC-111 — each grant in the spec that
  first needs it. Two boundaries are permanent: **`s3:DeleteObject` is granted nowhere in
  this arc** (`drop-temp-tables` touches Glue only, which is what makes it safe to reach
  from every failure path, including a validator failure where the location is still
  untrusted), and the `Deny` on `*/user_settings/*` + `*/DO_NOT_DELETE.txt`.
- `deploy-lambdas.yml`'s "bundle the shared requirements" test now also excludes
  `cpcommon: true` functions — PyJWT comes from the cpcommon layer, and a second bundled
  copy would double-count against the combined size guard.

## Deviations / notes

- **The Athena DML query-timeout quota increase is deliberately NOT requested** (user
  decision, 2026-07-14). SPEC-108 FR-003 framed it as a ship-blocking prerequisite; while
  the arc is in testing/concept the 30-minute account default is sufficient, so the
  increase (30 → up to 240 min, a support ticket) is deferred until real 250 GB sources
  arrive. Recorded in `athena.tf` and the smoke doc so it isn't lost.
- No component-inventory rows — see above.
