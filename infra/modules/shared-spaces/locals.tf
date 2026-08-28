# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Names are what the deploy policy scopes to, and every ARN here is KNOWN AT PLAN TIME.
# ../../info/control-plane-shape.md.

locals {
  requests_queue_name    = "${var.project_name}-${var.environment}-shared-space-requests.fifo"
  dlq_name               = "${var.project_name}-${var.environment}-shared-space-requests-dlq.fifo"
  orchestrator_role_name = "${var.project_name}-${var.environment}-shared-space-orchestrator-role"
  pipe_role_name         = "${var.project_name}-${var.environment}-shared-space-pipe-role"
  state_machine_name     = "${var.project_name}-${var.environment}-shared-space-orchestrator"
  pipe_name              = "${var.project_name}-${var.environment}-shared-space-pipe"

  # The verb Lambdas, keyed by the function suffix, which is also the lambdas/ subdirectory
  # suffix and the deploy-lambdas.yml matrix name. `forget` is a durable "clear from my list".
  shared_space_functions = {
    "validate"               = "validate.handler"
    "create"                 = "create_space.handler"
    "add-members"            = "add_members.handler"
    "remove-members"         = "remove_members.handler"
    "leave"                  = "leave.handler"
    "delete"                 = "delete_space.handler"
    "forget"                 = "forget_space.handler"
    "acknowledge-membership" = "acknowledge_membership.handler" # join-status ack
    "notify-failure"         = "ss_notify_failure.handler"      # last-resort notify
  }

  shared_space_function_names = {
    for suffix, handler in local.shared_space_functions :
    suffix => "${var.project_name}-${var.environment}-shared-space-${suffix}"
  }

  # Known at plan time — fed to the orchestrator policy's InvokeFunction list.
  shared_space_function_arns = [
    for suffix, name in local.shared_space_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  # CI builds, publishes and attaches this. Named to match the deploy-role wildcard.
  common_layer_name = "${var.project_name}-${var.environment}-shared-space-common"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"

  # One wildcard covers every function's group — the orchestrator is the exec role for all.
  lambda_log_groups_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-shared-space-*:*"

  state_machine_arn = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
  sfn_log_group_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"

  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.athena_admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"

  # Constructed from the role name, so there is no cross-module resource dependency.
  portal_role_arn = "arn:aws:iam::${var.account_id}:role/${var.portal_role_name}"
}
