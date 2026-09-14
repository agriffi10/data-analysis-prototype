# ── Table-share Step Function ──────────────────────────────
# Standard. Each per-recipient Map carries a PER-ITEM Catch, so one recipient's failure never
# aborts its siblings. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "table_share" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn       = module.functions["validate-authorize"].function_arn
    inspect_source_function_arn           = module.functions["inspect-source"].function_arn
    check_target_absent_function_arn      = module.functions["check-target-absent"].function_arn
    build_transfer_manifest_function_arn  = module.functions["build-transfer-manifest"].function_arn
    copy_objects_function_arn             = module.functions["copy-objects"].function_arn
    collect_transfer_results_function_arn = module.functions["collect-transfer-results"].function_arn
    create_table_function_arn             = module.functions["create-table"].function_arn
    notify_failure_function_arn           = module.functions["notify-failure"].function_arn
    # Mirrored in cpcommon/transfer/config.py; a test holds the two together.
    transfer_max_items_per_batch = local.transfer_max_items_per_batch
    transfer_map_max_concurrency = local.transfer_map_max_concurrency
    # a TOP-LEVEL ASL field. See the local for the arithmetic.
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

# ── The timed-out run's only route to a notification ─────
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT, and catchers do not
# cover top-level failures — so the machine's own NotifyFailure path is unreachable on this
# one failure and the sender would be told nothing at all.
#
# TIMED_OUT ONLY, NEVER FAILED: every whole-request failure a Catch takes already reaches
# NotifyFailure, so FAILED would double-notify every one of them. The two errors no Catch here
# takes, States.DataLimitExceeded and States.Runtime, reach neither door. README.md.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  name        = "${local.state_machine_name}-timed-out"
  description = "Notify the sender when a table-share execution is stopped by the state machine's own timeout."

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

# Resource-based grant, so the rule needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = module.functions["notify-failure"].function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
