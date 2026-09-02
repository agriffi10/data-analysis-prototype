# ── Orchestrator Step Function ────────────────────────────────────────────────
# Standard, routing by action: Validate → Choice(action) → exactly one verb. A Choice-routed
# fan-out rather than a pipeline. It runs under the shared ORCHESTRATOR role, which is also the
# exec role for every Lambda it invokes. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_sfn_state_machine" "orchestrator" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.orchestrator.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_function_arn           = module.functions["validate"].function_arn
    create_function_arn             = module.functions["create"].function_arn
    add_members_function_arn        = module.functions["add-members"].function_arn
    remove_members_function_arn     = module.functions["remove-members"].function_arn
    leave_function_arn              = module.functions["leave"].function_arn
    delete_function_arn             = module.functions["delete"].function_arn
    forget_function_arn             = module.functions["forget"].function_arn
    acknowledge_function_arn        = module.functions["acknowledge-membership"].function_arn
    transfer_ownership_function_arn = module.functions["transfer-ownership"].function_arn
    notify_failure_function_arn     = module.functions["notify-failure"].function_arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.orchestrator.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role_policy.orchestrator,
    aws_cloudwatch_log_group.orchestrator,
    time_sleep.wait_for_deploy_policy,
  ]
}
