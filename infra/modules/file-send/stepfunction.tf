# ── File-send Step Function ─────────────────────────────────────────────
# Standard, which Express doubly cannot be here: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVED WITH THE THING THAT MADE IT NECESSARY — the transfer
# added the Map, the manifest and the copy, so it added the timeout AND the EventBridge rule
# AND the deploy-role events: grant, because a timeout that cannot notify is a failure path
# satisfied on paper and silent in practice. The arithmetic is in locals.tf. README.md.

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
    # The guard, the manifest, the copy and the collector.
    check_target_absent_function_arn      = aws_lambda_function.functions["check-target-absent"].arn
    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    # The outcome producer.
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
# Catchers do not cover top-level execution failures, so the machine's own NotifyFailure path
# is unreachable on this one failure and the sender would be told nothing at all.
#
# TIMED_OUT ONLY, NEVER FAILED, or every caught failure double-notifies. Same shape as
# table-share's: two planes with one failure mode should not have two answers to it.
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

# Resource-based grant, so the rule needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.functions["notify-failure"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
