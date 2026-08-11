# ── File-send Step Function (SPEC-164 FR-001) ────────────────────────────────
# Standard state machine — validate-authorize, then a placeholder terminal. The
# copy states (SPEC-165/166) insert after Validated; the SPEC-152 failure path
# (ValidateFailureSeed → RecordFailure → NotifyFailure → Failed) is complete from
# day one.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on the verbs + log delivery); the verb Lambdas run under the ONE shared execution
# role. Standard (over Express) keeps per-execution history for debugging and allows
# the long per-recipient copies SPEC-166 adds — and Express is doubly rejected here,
# since a Pipe cannot use REQUEST_RESPONSE against a Standard machine (SPEC-157) and
# this plane's outcome is a notification, not a response.
#
# NO TOP-LEVEL TimeoutSeconds AT THIS STAGE, and that is a scope statement rather than
# an oversight. SPEC-161 established that a Standard workflow without one runs for a
# YEAR, and that the timeout cannot notify on its own (AWS catchers do not cover
# top-level execution failures) so it must ship WITH an EventBridge TIMED_OUT rule
# invoking notify-failure through a second door. This machine calls one 15-second
# validator and stops — there is nothing here that can wedge for hours. SPEC-166 adds
# the Distributed-Map copy, and it must add all three together: the timeout, the rule,
# and the deploy-role events: grant that manages the rule.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "file_send" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn = aws_lambda_function.functions["validate-authorize"].arn
    notify_failure_function_arn     = aws_lambda_function.functions["notify-failure"].arn
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
