locals {
  prefix = "${var.project_name}-${var.environment}-${var.name}"

  requests_queue_name = "${local.prefix}-requests.fifo"
  dlq_name            = "${local.prefix}-requests-dlq.fifo"
  pipe_name           = "${local.prefix}-pipe"
  pipe_role_name      = "${local.prefix}-pipe-role"
  state_machine_name  = "${local.prefix}-orchestrator"
  sfn_role_name       = "${local.prefix}-sfn-role"
  execution_role_name = coalesce(var.execution_role_name, "${local.prefix}-execution-role")

  function_names = {
    for verb, _ in var.functions :
    verb => "${var.project_name}-${var.environment}-${var.name}-${verb}"
  }

  constructed_function_arns = [
    for verb, name in local.function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  function_arns = { for verb, function in module.functions : verb => function.function_arn }

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  ceiling_vars = {
    for key, value in { state_machine_timeout_seconds = try(var.ceiling.seconds, null) } :
    key => value if value != null
  }
}
