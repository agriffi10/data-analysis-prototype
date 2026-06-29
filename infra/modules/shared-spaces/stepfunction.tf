# ── Orchestrator Step Function (SPEC-050 FR-003; SPEC-062 decomposition) ──────
# Standard state machine — the orchestration that routes by action (SPEC-062): a
# Validate task (verify token + authorize), a Choice state that routes on the
# validated `action`, then exactly one single-task verb Lambda. Retry on transient
# Lambda errors; Catch routes any failure to a terminal Fail state; else Succeed.
#
# Runs under the shared orchestrator role (iam.tf), which is also the exec role for
# every verb Lambda it invokes. Execution history + data are logged to a dedicated
# CloudWatch log group (Standard over Express precisely to keep this per-execution
# history for debugging the multi-step pipeline).

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
