# Completed Spec — SPEC-066: Table Builder Foundation Infrastructure + polars Runtime

## What was completed?

The **dedicated, asynchronous control plane** for "create a table from a folder" — plumbing
+ Lambda stubs only, no request contract or action logic (those are SPEC-067→070). Mirrors
the shared-spaces control-plane **pattern** with **per-verb least-privilege roles** (not one
shared role). New `infra/modules/table-builder/`:

- **FIFO** request queue (`.fifo`) + **FIFO DLQ** (redrive `maxReceiveCount=3`); `MessageGroupId`
  = target database (set by the producer, SPEC-067).
- **EventBridge Pipe** (SQS → Step Function, batch 1, `FIRE_AND_FORGET`) + pipe role.
- **Standard Step Function** — a **LINEAR** pipeline (`validate-authorize → check-table-absent →
  inspect-source → infer-schema → execute-ddl → Succeed`; shared `Catch` → `Fail`), each Task with
  the transient-Lambda-error `Retry`. Each Task threads the running object via `Payload.$=$` +
  `OutputPath=$.Payload`. 14-day vended-logs group + SFN role (InvokeFunction on the five +
  log-delivery).
- **Five verb Lambdas** (placeholder zip + `ignore_changes=[…,layers]`), each its **own** role +
  14-day log group, per-verb timeout/memory (validator 15s/256MB … infer 120s/1024MB …
  execute-ddl 300s/512MB). Stub-shape role policies: validate/execute = logs only;
  check-table-absent = Glue read; inspect/infer = S3 read on both data buckets.
- **polars layer** — **CI-built/published** (`deploy-lambdas.yml` `polars_layer` job, pinned
  `polars==1.12.0`, **107 MB** unzipped, attached to `infer-schema` only). See the decision below.
- Wired into root `main.tf` as `module.table_builder`; cross-module ARNs are constructed-string
  locals (plans standalone). **No** in-module `time_sleep` guard — PR1's deploy grants are applied
  before the resources (notifications precedent).

Shipped per [[deploy-role-perms-before-resources]] as **two PRs**: **PR1 (#148)** the deploy-role
IAM (managed policy `dat-deploy-table-builder`, scoped `*-table-builder-*`; no S3-bucket statement —
the module creates no buckets) → applied → **PR2 (#149)** the module + stubs + CI + smoke doc.

## What changed from earlier specs?

- **`deploy-lambdas.yml`** gained the `polars_layer` build/publish job + 5 table-builder matrix rows
  (`infer-schema` attaches the polars layer). No change to the shared-space/notifications functions.
- **One in-session decision (reversible/technical):** the polars layer is **CI-built/published, NOT
  a Terraform `aws_lambda_layer_version`** — the 100 MB+ artifact can't be vendored for a TF-built
  zip, and the repo's code/infra split has CI own code + layers (the `shared-space-common` pattern;
  architecture.md §4 "consistent with the repo's existing packaging"). SPEC-066 FR-003 + outputs +
  file structure were updated to match (no `layer.tf`).

## Verification

`tofu validate` + `fmt` clean; all `*.tftpl` render to valid JSON; `templatefile` superset-vars
confirmed tolerated; Python stubs compile; workflow YAML valid; PR `plan` checks passed against real
AWS state; both fresh-context reviews **APPROVE** (no blockers). **Live smoke test (post-merge):** a
message on the FIFO queue drove the Pipe → SFN → all five stub Lambdas in order →
execution **SUCCEEDED**, no table created. polars layer measured at **107 MB** unzipped (CI cap 240
MB). Documented in `docs/testing/e2e.md`.
