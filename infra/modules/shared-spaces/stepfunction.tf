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
    validate_function_arn       = aws_lambda_function.functions["validate"].arn
    create_function_arn         = aws_lambda_function.functions["create"].arn
    add_members_function_arn    = aws_lambda_function.functions["add-members"].arn
    remove_members_function_arn = aws_lambda_function.functions["remove-members"].arn
    leave_function_arn          = aws_lambda_function.functions["leave"].arn
    delete_function_arn         = aws_lambda_function.functions["delete"].arn
    forget_function_arn         = aws_lambda_function.functions["forget"].arn
    acknowledge_function_arn    = aws_lambda_function.functions["acknowledge-membership"].arn
    notify_failure_function_arn = aws_lambda_function.functions["notify-failure"].arn
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
