# ── File-send Step Function (SPEC-164 FR-001) ────────────────────────────────
# Standard state machine — validate-authorize, inspect-source, then a placeholder
# terminal. The per-recipient guard and the Distributed-Map copy (SPEC-166) insert
# after Planned; the SPEC-152 failure path (a seed → RecordFailure → NotifyFailure →
# Failed) is complete from day one.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on the verbs + log delivery); the verb Lambdas run under the ONE shared execution
# role. Standard (over Express) keeps per-execution history for debugging and allows
# the long per-recipient copies SPEC-166 adds — and Express is doubly rejected here,
# since a Pipe cannot use REQUEST_RESPONSE against a Standard machine (SPEC-157) and
# this plane's outcome is a notification, not a response.
#
# STILL NO TOP-LEVEL TimeoutSeconds, and SPEC-165 re-checked the reasoning rather than
# inheriting it. SPEC-161 established that a Standard workflow without one runs for a
# YEAR, and that the timeout cannot notify on its own (AWS catchers do not cover
# top-level execution failures) so it must ship WITH an EventBridge TIMED_OUT rule
# invoking notify-failure through a second door. This machine is now two Tasks, and
# every one of its states is bounded by its own Lambda timeout — 15s + 120s, with the
# Retry ceilings on top. There is still nothing here that can wedge for hours, because
# there is still nothing here that WAITS: no Map, no poll loop, no copy. SPEC-166 adds
# all three, and it must add the timeout, the rule and the deploy-role events: grant
# that manages the rule together with them.

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
    inspect_source_function_arn     = aws_lambda_function.functions["inspect-source"].arn
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
