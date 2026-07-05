# ── Constructed names + ARNs (SPEC-088) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-088 PR1 grant) scopes to the same {project}-*-table-share-*
# patterns, and so cross-resource ARNs referenced inside IAM policy templates are
# KNOWN AT PLAN TIME (constructed strings, not resource attributes) — the
# architecture.md "unknown ARN in list" discipline. This module plans standalone.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-table-share-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-table-share-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-table-share-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-table-share-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-table-share-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-table-share-sfn-role"

  # ONE shared execution role for all five verb Lambdas (user decision, recorded in
  # docs/table-share-architecture.md §7 — mirrors the table-builder's post-SPEC-072
  # consolidated model; per-verb roles are NOT used). At this stage its permission
  # policy is LOGS ONLY (execution.json.tftpl); the LF-admin / Glue / Athena / S3 /
  # Cognito grants are added by the spec that first needs each (SPEC-089/090/092).
  # ARN is a constructed string (known at plan time) for the later cycle-free
  # LF-admin wiring from root (SPEC-092).
  execution_role_name = "${var.project_name}-${var.environment}-table-share-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-share-execution-role"

  # The five single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/table-share-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "table-share-<suffix>"); value = the handler + the task's real timeout/memory
  # need (a small validator ≠ a long parallel S3 copy — lambdas.md §4).
  # validate-authorize + inspect-source run once per request; the other three run
  # per recipient inside the Step Function Map (stepfunction.tf).
  # Module names carry the table_share_ prefix so they can't collide with the
  # table-builder's identically-named verbs on sys.modules under one
  # `pytest lambdas/` process (the tbcommon-package lesson, applied to verb modules).
  table_share_functions = {
    "validate-authorize"  = { handler = "table_share_validate_authorize.handler", timeout = 15, memory = 256 }
    "inspect-source"      = { handler = "table_share_inspect_source.handler", timeout = 60, memory = 512 }
    "check-target-absent" = { handler = "table_share_check_target_absent.handler", timeout = 15, memory = 256 }
    "copy-objects"        = { handler = "table_share_copy_objects.handler", timeout = 900, memory = 1024 }
    "create-table"        = { handler = "table_share_create_table.handler", timeout = 300, memory = 512 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). Only
  # validate-authorize needs the Cognito pool/client (offline token verify) + the
  # admin bucket (registry reads) at this stage (SPEC-089); later verbs' action env
  # is added by their owning specs.
  table_share_verb_env = {
    "validate-authorize" = {
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
      ADMIN_BUCKET          = var.admin_bucket_name
    }
  }

  # ARNs for the execution role's SPEC-089 grants (constructed, known at plan).
  admin_bucket_arn  = "arn:aws:s3:::${var.admin_bucket_name}"
  user_pool_arn     = "arn:aws:cognito-idp:${var.aws_region}:${var.account_id}:userpool/${var.user_pool_id}"
  glue_catalog_arn  = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any    = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"

  table_share_function_names = {
    for suffix, _ in local.table_share_functions :
    suffix => "${var.project_name}-${var.environment}-table-share-${suffix}"
  }

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list and the Step Function tasks.
  table_share_function_arns = [
    for suffix, name in local.table_share_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  table_share_log_group_names = {
    for suffix, name in local.table_share_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-table-share-* wildcard (one statement
  # covering all five function log groups) rather than a per-verb ARN.
  table_share_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-table-share-*"

  # table-share-common (tscommon) Lambda layer — CI builds + publishes it
  # (deploy-lambdas.yml), exactly like table-builder-common: the layer artifact is
  # CI-owned, and every verb attaches it via update-function-configuration (TF
  # ignores the `layers` attribute). Named to match the deploy-role *-table-share-*
  # layer wildcard (modules/base). Referenced here for documentation/parity only.
  tscommon_layer_name = "${var.project_name}-${var.environment}-table-share-common"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
