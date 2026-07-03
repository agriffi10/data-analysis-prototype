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

  # ONE shared execution role for all five verb Lambdas (user decision — reverses the
  # SPEC-066 per-verb roles, mirroring the shared-spaces single-orchestrator model in
  # SPEC-062). Its permission policy is the UNION of the verbs' needs (execution.json.tftpl),
  # and it is the table-builder Lake Formation admin (analytics data_lake_settings) so
  # check-table-absent + execute-ddl can Describe/CREATE in the DYNAMIC per-user +
  # per-shared-space target databases (they can't be statically LF-granted). ARN is a
  # constructed string (known at plan time) for cycle-free LF-admin wiring from root.
  execution_role_name = "${var.project_name}-${var.environment}-table-builder-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-builder-execution-role"

  # The five single-task verb Lambdas, in pipeline order. Keyed by the function
  # SUFFIX (= the lambdas/table-builder-<suffix>/ subdir AND the deploy-lambdas.yml
  # matrix name "table-builder-<suffix>"); value = the handler + the task's real
  # timeout/memory need (a small validator ≠ the polars infer step — lambdas.md §4).
  # All five share ONE execution role (execution_role above); the Step Function
  # orchestrates them as a LINEAR sequence (stepfunction.tf).
  table_builder_functions = {
    "validate-authorize" = { handler = "validate_authorize.handler", timeout = 15, memory = 256 }
    "check-table-absent" = { handler = "check_table_absent.handler", timeout = 15, memory = 256 }
    "inspect-source"     = { handler = "inspect_source.handler", timeout = 60, memory = 512 }
    "infer-schema"       = { handler = "infer_schema.handler", timeout = 120, memory = 1024 }
    "execute-ddl"        = { handler = "execute_ddl.handler", timeout = 300, memory = 512 }
  }

  table_builder_function_names = {
    for suffix, _ in local.table_builder_functions :
    suffix => "${var.project_name}-${var.environment}-table-builder-${suffix}"
  }

  # Per-verb extra env, merged over the common bucket-name env (lambda.tf). Only
  # validate-authorize needs the Cognito pool/client (offline token verify, SPEC-067);
  # execute-ddl needs the analytics workgroup to run the CREATE (SPEC-070); later
  # verbs' action env is added by their owning specs.
  table_builder_verb_env = {
    "validate-authorize" = {
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
    }
    "execute-ddl" = {
      ATHENA_WORKGROUP = var.athena_workgroup
    }
  }

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
  # covering all five function log groups) rather than a per-verb ARN.
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
