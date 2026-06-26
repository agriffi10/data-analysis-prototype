# ── Orchestrator Step Function (SPEC-050 FR-003) ─────────────────────────────
# Standard state machine — the single privileged broker. SPEC-050 ships a SKELETON:
# an entry Task that invokes the provisioner Lambda, with Retry on transient Lambda
# errors and a Catch routing any failure to a terminal Fail state, else a terminal
# Succeed. Per-action bodies (validate → create → grant → cache-write, the SPEC-051→
# 055 logic) are filled in later; here the Lambda just dispatches/echoes.
#
# Runs under the shared orchestrator role (iam.tf). Execution history + data are
# logged to a dedicated CloudWatch log group (the user chose Standard over Express
# precisely to keep this per-execution history for debugging the multi-step pipeline).

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
    provisioner_function_arn = aws_lambda_function.provisioner.arn
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
