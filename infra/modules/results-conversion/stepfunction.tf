# ── Results-conversion Step Function ──────────────────────────────────────────
# Standard, which Express doubly cannot be: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds SHIPS FROM THE FIRST VERSION with its TIMED_OUT rule below —
# catchers do not cover top-level execution failures, so a ceiling without the rule is a
# silent failure mode rather than a bounded one. The arithmetic is in locals.tf.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "results_conversion" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn = module.functions["validate-authorize"].function_arn
    describe_results_function_arn   = module.functions["describe-results"].function_arn
    convert_function_arn            = module.functions["convert"].function_arn
    notify_function_arn             = module.functions["notify"].function_arn
    notify_failure_function_arn     = module.functions["notify-failure"].function_arn
    state_machine_timeout_seconds   = local.state_machine_timeout_seconds
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.orchestrator.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role_policy.sfn,
    aws_cloudwatch_log_group.orchestrator,
  ]
}

# ── The timed-out run's only route to a notification ─────────
# Catchers do not cover top-level execution failures, so the machine's own NotifyFailure path
# is unreachable on this one failure and the actor would be told nothing at all.
#
# TIMED_OUT ONLY, NEVER FAILED, or every caught failure double-notifies.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  name        = "${local.state_machine_name}-timed-out"
  description = "Notify the actor when a results-conversion execution is stopped by the state machine's own timeout."

  event_pattern = jsonencode({
    "source"      = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    "detail" = {
      status          = ["TIMED_OUT"]
      stateMachineArn = [local.state_machine_arn]
    }
  })
}

resource "aws_cloudwatch_event_target" "execution_timed_out" {
  rule = aws_cloudwatch_event_rule.execution_timed_out.name
  arn  = module.functions["notify-failure"].function_arn
}

# Resource-based grant, so the rule needs no invoke role. Bound to the module's function_arn
# OUTPUT, never a name: a name is config-known, plans no diff across a replacement, and lets
# the replacement take the resource policy.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = module.functions["notify-failure"].function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
