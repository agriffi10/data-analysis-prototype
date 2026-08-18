# ── Table-share Step Function ──────────────────────────────
# Standard state machine — validate-authorize → inspect-source once per request,
# then a Map over $.recipients running check-target-absent → copy-objects →
# create-table PER RECIPIENT with a per-item Catch (one recipient's failure never
# aborts its siblings — docs/architecture.md Control Planes -> Table Share). The per-step bodies
# are STUBS here (pass-through) — the real logic + the structured recorded-failure
# outcomes land in SPEC-089→092.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on the five verbs + log delivery); the verb Lambdas run under the ONE shared
# execution role. Standard (over Express) keeps per-execution history for debugging
# the multi-step share flow and allows long per-recipient copies.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "table_share" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn       = aws_lambda_function.functions["validate-authorize"].arn
    inspect_source_function_arn           = aws_lambda_function.functions["inspect-source"].arn
    check_target_absent_function_arn      = aws_lambda_function.functions["check-target-absent"].arn
    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    create_table_function_arn             = aws_lambda_function.functions["create-table"].arn
    notify_failure_function_arn           = aws_lambda_function.functions["notify-failure"].arn
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

# ── SPEC-161 FR-003 AC2: the timed-out run's only route to a notification ─────
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT. Step Functions catchers
# cover Task, Parallel and Map states but NOT top-level execution failures, so the machine's own
# RecordFailure -> NotifyFailure path is unreachable on this one failure and the sender would be
# told nothing at all — the exact silence SPEC-152 exists to close. Listening for TIMED_OUT on an
# EventBridge bus is the documented remedy, and this is it.
#
# TIMED_OUT ONLY, never FAILED. Every other whole-request failure already reaches NotifyFailure
# through a Catch, so matching FAILED here would send a second notification for every one of them.
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
