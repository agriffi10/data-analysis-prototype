# ── Constructed names + ARNs (SPEC-108) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-108 PR1 grant) scopes to the same {project}-*-data-quality-*
# patterns, and so cross-resource ARNs referenced inside IAM policy templates are KNOWN
# AT PLAN TIME (constructed strings, not resource attributes) — the architecture.md
# "unknown ARN in list" discipline. This module plans standalone.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-data-quality-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-data-quality-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-data-quality-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-data-quality-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-data-quality-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-data-quality-sfn-role"

  # ONE shared execution role for all nine verb Lambdas (no per-verb roles — matching
  # table-builder and table-share). At SPEC-108 its policy is LOGS ONLY; the S3 grants
  # + the protected-object Deny arrive in SPEC-109, and the Glue/Athena/Lake-Formation
  # admin grants in SPEC-111 (the spec that first needs them). ARN is a constructed
  # string (known at plan time) so SPEC-111 can add it to the analytics LF admins list
  # without a cycle.
  execution_role_name = "${var.project_name}-${var.environment}-data-quality-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-data-quality-execution-role"

  # The nine single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/data-quality-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "data-quality-<suffix>"); value = the handler + the task's real timeout/memory.
  #
  # BOTH timeout AND memory_size are set explicitly for every verb (SPEC-108 FR-002).
  # The precedent this fixes, precisely: the shared-space verbs set `timeout = 60` but
  # NEVER set `memory_size` (infra/modules/shared-spaces/lambda.tf:46), leaving it at
  # the AWS default of 128 MB. It is the MEMORY default that was left implicit there,
  # not the timeout — and an unset memory tier is invisible in the plan and only shows
  # up as an OOM in production.
  #
  # NO VERB HERE STREAMS BULK DATA — Athena does the heavy work — which is why nothing
  # needs the maximum timeout or memory tier. byte-scan is the ONLY function that
  # touches file bytes, and its budget is bounded PER REQUEST (DQ_SCAN_TOTAL_BYTES,
  # default 2 GiB — SPEC-112 FR-001); 300 s / 1024 MB is sized against that. A
  # PER-FILE budget (v3's design: 256 MiB × up to 1000 files ≈ 276 GB) would need
  # ~920 MB/s sustained through one Lambda and is impossible — it would pass on a
  # three-file fixture and time out in production.
  data_quality_functions = {
    "validate-authorize"  = { handler = "handler.handler", timeout = 15, memory = 256 }
    "inspect-source"      = { handler = "handler.handler", timeout = 120, memory = 1024 }
    "create-temp-tables"  = { handler = "handler.handler", timeout = 60, memory = 512 }
    "start-profile-query" = { handler = "handler.handler", timeout = 30, memory = 512 }
    "check-query"         = { handler = "handler.handler", timeout = 15, memory = 256 }
    "byte-scan"           = { handler = "handler.handler", timeout = 300, memory = 1024 }
    "assemble-report"     = { handler = "handler.handler", timeout = 120, memory = 1024 }
    "drop-temp-tables"    = { handler = "handler.handler", timeout = 60, memory = 512 }
    "notify-failure"      = { handler = "handler.handler", timeout = 15, memory = 256 }
  }

  data_quality_function_names = {
    for suffix, _ in local.data_quality_functions :
    suffix => "${var.project_name}-${var.environment}-data-quality-${suffix}"
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything cpcommon/config.py _require()s must live in the COMMON
  # env instead — the shared layer's import-time fail-fast runs for every verb that
  # imports it, so a verb missing any required var crashes at cold start (PR #196).
  data_quality_verb_env = {}

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list and the Step Function tasks.
  data_quality_function_arns = [
    for suffix, name in local.data_quality_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  data_quality_log_group_names = {
    for suffix, name in local.data_quality_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-data-quality-* wildcard (one statement
  # covering all nine function log groups) rather than a per-verb ARN.
  data_quality_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-data-quality-*"

  # CI-built Lambda layers (deploy-lambdas.yml publishes + attaches them; TF ignores the
  # `layers` attribute). Named to match the deploy-role *-data-quality-* layer wildcard
  # (modules/base). Referenced here for documentation/parity only.
  #
  # dqcommon carries the DOMAIN surface only — no polars, no Excel engine, and NO
  # PyJWT/cryptography (those live once, in cpcommon — SPEC-107 FR-001).
  dqcommon_layer_name = "${var.project_name}-${var.environment}-data-quality-common"

  # polars, attached to inspect-source ONLY. The layer is unavoidable: Athena requires
  # an EXPLICIT COLUMN LIST for a Parquet or JSON external table and does NOT auto-detect
  # a Parquet schema, so that list must come from inspect-source's per-file probe — and
  # reading a Parquet footer needs a Parquet reader. "This arc needs no polars" would
  # make its own Parquet support (SPEC-110 FR-002) impossible to build. No fastexcel:
  # this arc does not support Excel (convert it first, then check the Parquet).
  polars_layer_name = "${var.project_name}-${var.environment}-data-quality-polars"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  # Bucket ARNs for the execution role's S3 statements (SPEC-109 FR-006).
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"

  # The dedicated Athena workgroup this pipeline's queries run in (athena.tf).
  athena_workgroup_name = "${var.project_name}-${var.environment}-data-quality-wg"
  athena_workgroup_arn  = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${local.athena_workgroup_name}"
}
