# ── Archive Step Function (SPEC-168 FR-003) ──────────────────────────────────
# Standard state machine — validate-authorize, then the archive/restore branch and its
# two placeholders. The SPEC-152 failure path (a seed → RecordFailure → NotifyFailure →
# Failed) is complete from day one.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction on
# the verbs + log delivery); the verb Lambdas run under the ONE shared execution role.
# Standard (over Express) keeps per-execution history for debugging and allows the long
# Glacier retrieval wait SPEC-171 adds — and Express is doubly rejected here, since a Pipe
# cannot use REQUEST_RESPONSE against a Standard machine (SPEC-157) and this plane's
# outcome is a notification, not a response.
#
# NO TOP-LEVEL TimeoutSeconds AT THIS STAGE, and the absence is deliberate rather than
# forgotten. Nothing in this machine WAITS: no Map, no manifest, no copy, no poll loop.
# SPEC-169 adds the transfer and SPEC-171 adds a retrieval that waits HOURS, and each must
# arrive with the ceiling AND the EventBridge TIMED_OUT rule that makes the ceiling
# reachable by a notification — AWS catchers cover Task, Parallel and Map states but NOT
# top-level execution failures, so a timeout without the rule is SPEC-152 satisfied on
# paper and silent in practice (file-send's recorded finding, inherited rather than
# rediscovered).

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "archive" {
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
