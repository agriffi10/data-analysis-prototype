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

  # The five single-task verb Lambdas, in pipeline order. Keyed by the function
  # SUFFIX (= the lambdas/table-builder-<suffix>/ subdir AND the deploy-lambdas.yml
  # matrix name "table-builder-<suffix>"); value = the handler + the task's real
  # timeout/memory need (a small validator ≠ the polars infer step — lambdas.md §4).
  # Each runs under its OWN per-verb role (no shared "god" role — lambdas.md §7);
  # the Step Function orchestrates them as a LINEAR sequence (stepfunction.tf).
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
  # later verbs' action env is added by their owning specs.
  table_builder_verb_env = {
    "validate-authorize" = {
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
    }
  }

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list and the Step Function tasks.
  table_builder_function_arns = [
    for suffix, name in local.table_builder_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  table_builder_role_names = {
    for suffix, _ in local.table_builder_functions :
    suffix => "${var.project_name}-${var.environment}-table-builder-${suffix}-role"
  }

  table_builder_log_group_names = {
    for suffix, name in local.table_builder_function_names :
    suffix => "/aws/lambda/${name}"
  }

  table_builder_log_group_arns = {
    for suffix, group in local.table_builder_log_group_names :
    suffix => "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${group}"
  }

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
}
