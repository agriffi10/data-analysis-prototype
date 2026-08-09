# ── Constructed names + ARNs (SPEC-066) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-066 PR1 grant) scopes to the same {project}-*-table-builder-*
# patterns, and so cross-resource ARNs referenced inside IAM policy templates are
# KNOWN AT PLAN TIME (constructed strings, not resource attributes) — the
# architecture.md "unknown ARN in list" discipline. This module plans standalone.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-table-builder-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-table-builder-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-table-builder-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-table-builder-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-table-builder-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-table-builder-sfn-role"

  # ONE shared execution role for every verb Lambda (user decision — reverses the
  # SPEC-066 per-verb roles, mirroring the shared-spaces single-orchestrator model in
  # SPEC-062). Its permission policy is the UNION of the verbs' needs (execution.json.tftpl),
  # and it is the table-builder Lake Formation admin (analytics data_lake_settings) so
  # check-table-absent + execute-ddl can Describe/CREATE in the DYNAMIC per-user +
  # per-shared-space target databases (they can't be statically LF-granted). ARN is a
  # constructed string (known at plan time) for cycle-free LF-admin wiring from root.
  execution_role_name = "${var.project_name}-${var.environment}-table-builder-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-builder-execution-role"

  # The single-task verb Lambdas, in pipeline order. Keyed by the function SUFFIX
  # (= the lambdas/table-builder-<suffix>/ subdir AND the deploy-lambdas.yml matrix
  # name "table-builder-<suffix>"); value = the handler + the task's real
  # timeout/memory need (a small validator ≠ the polars infer step — lambdas.md §4).
  # All share ONE execution role (execution_role above); the Step Function orchestrates
  # them as two branches over one shared spine (stepfunction.tf).
  #
  # load-table-definition (SPEC-143) is the refresh branch's entry verb and mirrors
  # check-table-absent in the negative — one Glue GetTable, no S3 — so it takes the same
  # 15 s / 256 MB. lambda.tf needs no edit for a new entry: it is entirely for_each over
  # this map, so the function, its log group and its placeholder zip all follow.
  # stepfunction.tf DOES need one — its templatefile() call passes an explicit per-function
  # map, not a loop. The DEPLOY role needs none either: modules/base's
  # github-actions-deploy-table-builder policy scopes to {project}-*-table-builder-*, which
  # already covers this function and its log group.
  table_builder_functions = {
    "validate-authorize"    = { handler = "validate_authorize.handler", timeout = 15, memory = 256 }
    "check-table-absent"    = { handler = "check_table_absent.handler", timeout = 15, memory = 256 }
    "load-table-definition" = { handler = "load_table_definition.handler", timeout = 15, memory = 256 }
    # SPEC-157. The refresh lock's two halves: one conditional S3 read + one conditional
    # write each, no Glue and no Athena, so both take the smallest shape here. The 15 s
    # timeout is an INPUT to the state machine's TimeoutSeconds derivation (stepfunction.tf's
    # comment; the field itself is in the ASL template)
    # and to tbcommon/table_lock.py's MACHINE_TIMEOUT_SECONDS — raising either one without
    # the other is caught by test_table_lock_timeout.py.
    "acquire-refresh-lock" = { handler = "acquire_refresh_lock.handler", timeout = 15, memory = 256 }
    "release-refresh-lock" = { handler = "release_refresh_lock.handler", timeout = 15, memory = 256 }
    "inspect-source"       = { handler = "inspect_source.handler", timeout = 60, memory = 512 }
    "infer-schema"         = { handler = "infer_schema.handler", timeout = 120, memory = 1024 }
    "diff-schema"          = { handler = "diff_schema.handler", timeout = 15, memory = 256 }
    "apply-refresh"        = { handler = "apply_refresh.handler", timeout = 300, memory = 512 }
    "execute-ddl"          = { handler = "execute_ddl.handler", timeout = 300, memory = 512 }
    # SPEC-152. The notification of last resort: one decode + one SQS send, reached only
    # on a failure path, so it takes the smallest shape any verb here has.
    "notify-failure" = { handler = "tb_notify_failure.handler", timeout = 15, memory = 256 }
  }

  table_builder_function_names = {
    for suffix, _ in local.table_builder_functions :
    suffix => "${var.project_name}-${var.environment}-table-builder-${suffix}"
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR
  # OPTIONAL action env only: everything tbcommon/config.py _require()s must live
  # in the COMMON env instead — the shared layer's import-time fail-fast runs for
  # every verb (each imports notify → config), so a verb missing any required var
  # crashes at cold start (the 2026-07-05 production break). The Cognito pair +
  # workgroup moved to the common env for that reason.
  table_builder_verb_env = {}

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list and the Step Function tasks.
  table_builder_function_arns = [
    for suffix, name in local.table_builder_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  table_builder_log_group_names = {
    for suffix, name in local.table_builder_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-table-builder-* wildcard (one statement
  # covering every function log group) rather than a per-verb ARN.
  table_builder_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-table-builder-*"

  # polars Lambda layer — CI builds + publishes it (deploy-lambdas.yml), exactly like
  # shared-space-common: the heavy artifact can't be vendored into TF, so CI owns it
  # and infer-schema attaches it via update-function-configuration (TF ignores the
  # `layers` attribute). Named to match the deploy-role *-table-builder-* layer
  # wildcard (modules/base). Referenced here for documentation/parity only.
  polars_layer_name = "${var.project_name}-${var.environment}-table-builder-polars"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"

  # Athena/Glue ARNs for the execution role's DDL statements (SPEC-070). The workgroup
  # + the catalog it creates tables in are scoped in execution.json.tftpl. Target
  # databases are DYNAMIC (one per user + per shared space), so Glue/table are scoped to
  # the account catalog's database/* + table/*/* — Lake Formation (the execution role is
  # an LF admin, wired in the analytics data_lake_settings) is what actually gates which
  # DB a table lands in.
  athena_workgroup_arn = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"
  glue_catalog_arn     = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any    = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any       = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"
}
