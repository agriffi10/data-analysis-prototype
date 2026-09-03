# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Names are what the deploy policy scopes to, and every ARN here is KNOWN AT PLAN TIME.
# This module plans standalone. ../../info/control-plane-shape.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-table-builder-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-table-builder-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-table-builder-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-table-builder-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-table-builder-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-table-builder-sfn-role"

  # The ARN is a constructed string so the LF-admin wiring from root is cycle-free.
  execution_role_name = "${var.project_name}-${var.environment}-table-builder-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-builder-execution-role"

  # The verb Lambdas, in pipeline order. Keyed by the function SUFFIX, which is also the
  # lambdas/table-builder-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # A NEW ENTRY needs no edit to lambda.tf (for_each) and none to the deploy role, but DOES
  # need a key added in stepfunction.tf, whose templatefile() map is explicit. README.md.
  table_builder_functions = {
    "validate-authorize"    = { handler = "validate_authorize.handler", timeout = 15, memory = 256 }
    "check-table-absent"    = { handler = "check_table_absent.handler", timeout = 15, memory = 256 }
    "load-table-definition" = { handler = "load_table_definition.handler", timeout = 15, memory = 256 }
    # These 15 s timeouts are INPUTS to the machine's TimeoutSeconds derivation and to
    # tbcommon/table_lock.py's MACHINE_TIMEOUT_SECONDS. Raising one without the other is
    # caught by test_table_lock_timeout.py.
    "acquire-refresh-lock" = { handler = "acquire_refresh_lock.handler", timeout = 15, memory = 256 }
    "release-refresh-lock" = { handler = "release_refresh_lock.handler", timeout = 15, memory = 256 }
    "inspect-source"       = { handler = "inspect_source.handler", timeout = 60, memory = 512 }
    "infer-schema"         = { handler = "infer_schema.handler", timeout = 120, memory = 1024 }
    "diff-schema"          = { handler = "diff_schema.handler", timeout = 15, memory = 256 }
    "apply-refresh"        = { handler = "apply_refresh.handler", timeout = 300, memory = 512 }
    "execute-ddl"          = { handler = "execute_ddl.handler", timeout = 300, memory = 512 }
    # The notification of last resort: one decode + one SQS send.
    "notify-failure" = { handler = "tb_notify_failure.handler", timeout = 15, memory = 256 }
  }

  table_builder_function_names = {
    for suffix, _ in local.table_builder_functions :
    suffix => "${var.project_name}-${var.environment}-table-builder-${suffix}"
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything tbcommon/config.py requires belongs in
  # the COMMON env in lambda.tf. README.md.
  table_builder_verb_env = {}

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  table_builder_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard statement covers them
  # rather than a per-verb ARN.
  table_builder_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-table-builder-*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"

  # Target databases are DYNAMIC, so these are the account catalog's database/* + table/*/*.
  # LAKE FORMATION, not this scope, is what gates which database a table lands in.
  athena_workgroup_arn = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"
  glue_catalog_arn     = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any    = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any       = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"
}
