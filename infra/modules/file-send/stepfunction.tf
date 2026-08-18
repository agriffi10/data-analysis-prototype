# ── File-send Step Function ────────────────────────────────────────────────
# Standard state machine — validate-authorize and inspect-source once per request,
# then the guard Map, the top-level Distributed-Map transfer, the collector and the
# per-recipient summary. The whole-request failure path (a seed → RecordFailure →
# NotifyFailure → Failed) has been complete since day one.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on the verbs + log delivery); the verb Lambdas run under the ONE shared execution
# role. Standard (over Express) keeps per-execution history for debugging and allows
# the long per-recipient copies — and Express is doubly rejected here,
# since a Pipe cannot use REQUEST_RESPONSE against a Standard machine and
# this plane's outcome is a notification, not a response.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVES WITH THE THING THAT MADE IT NECESSARY. Source resolution alone
# recorded that this machine could not wedge for hours because nothing in it WAITED: no
# Map, no poll loop, no copy. The transfer adds all three, so it adds the timeout — and with
# it the EventBridge rule below and the deploy-role events: grant that manages that
# rule, because a timeout that cannot notify is a failure path satisfied on paper and silent
# in practice. The arithmetic behind the number is in locals.tf, where a test computes
# it from the caps.

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
    # SPEC-166.
    check_target_absent_function_arn      = aws_lambda_function.functions["check-target-absent"].arn
    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    # SPEC-167.
    notify_function_arn       = aws_lambda_function.functions["notify"].arn
    guard_map_max_concurrency = local.guard_map_max_concurrency
    # Mirrored from cpcommon/transfer/config.py; a test holds the two together.
    transfer_max_items_per_batch = local.transfer_max_items_per_batch
    transfer_map_max_concurrency = local.transfer_map_max_concurrency
    # A TOP-LEVEL ASL field. See the local for the arithmetic.
    state_machine_timeout_seconds = local.state_machine_timeout_seconds
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
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT. Step Functions catchers
# cover Task, Parallel and Map states but NOT top-level execution failures, so the machine's own
# RecordFailure -> NotifyFailure path is unreachable on this one failure and the sender would be
# told nothing at all — the exact silence the failure path exists to close. Listening for TIMED_OUT on an
# EventBridge bus is the documented remedy, and this is it. Same shape as table-share's, which is
# the point: two planes with one failure mode should not have two answers to it.
#
# TIMED_OUT ONLY, never FAILED. Every other whole-request failure already reaches NotifyFailure
# through a Catch, so matching FAILED here would send a second notification for every one of them.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  name        = "${local.state_machine_name}-timed-out"
  description = "Notify the sender when a file-send execution is stopped by the state machine's own timeout."

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
  arn  = aws_lambda_function.functions["notify-failure"].arn
}

# Resource-based grant so the rule (events.amazonaws.com) may invoke the notifier — the same
# reason the DLQ drain's sweep needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.functions["notify-failure"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
