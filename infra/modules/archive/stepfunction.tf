# ── Archive Step Function (SPEC-168 FR-003, completed by SPEC-169) ───────────
# Standard state machine — validate-authorize and inspect-source once per request, then the
# transfer manifest, the top-level Distributed-Map copy into the vault, the collector, the
# COMMIT GATE and, on its one committing arm, the record, the source deletion and the
# receipt. The SPEC-152 failure path (a seed → RecordFailure → NotifyFailure → Failed) is
# complete from day one.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction on
# the verbs + log delivery + the Distributed Map's own grants); the verb Lambdas run under
# the ONE shared execution role. Standard (over Express) keeps per-execution history for
# debugging and allows the long copies SPEC-169 adds and the Glacier retrieval wait
# SPEC-171 will — and Express is doubly rejected here, since a Pipe cannot use
# REQUEST_RESPONSE against a Standard machine (SPEC-157) and this plane's outcome is a
# notification, not a response.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVES WITH THE THING THAT MADE IT NECESSARY. SPEC-168
# recorded that this machine could not wedge because nothing in it WAITED: no Map, no
# manifest, no copy. SPEC-169 adds all three, so it adds the ceiling — and with it the
# EventBridge rule below, notify-failure's second door and the raise from 15s to 60s that
# door needs, because a timeout that cannot notify is SPEC-152 satisfied on paper and
# silent in practice. The deploy-role `events:` grant that manages the rule shipped one PR
# ahead of it (SPEC-168's merge apply went red for exactly that ordering). The arithmetic
# behind the number is in locals.tf, where a test computes it from the caps.

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
    # SPEC-169.
    inspect_source_function_arn           = aws_lambda_function.functions["inspect-source"].arn
    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    rollback_function_arn                 = aws_lambda_function.functions["rollback"].arn
    write_manifest_function_arn           = aws_lambda_function.functions["write-manifest"].arn
    delete_source_function_arn            = aws_lambda_function.functions["delete-source"].arn
    write_receipt_function_arn            = aws_lambda_function.functions["write-receipt"].arn
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

# ── SPEC-169 FR-003: the timed-out run's only route to a notification ────────
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT. Step Functions catchers
# cover Task, Parallel and Map states but NOT top-level execution failures, so the machine's own
# RecordFailure -> NotifyFailure path is unreachable on this one failure and the actor would be
# told nothing at all — the exact silence SPEC-152 exists to close. Listening for TIMED_OUT on an
# EventBridge bus is the documented remedy, and this is it. Same shape as file-send's and
# table-share's, which is the point: three planes with one failure mode should not have three
# answers to it.
#
# TIMED_OUT ONLY, never FAILED. Every other whole-request failure already reaches NotifyFailure
# through a Catch, so matching FAILED here would send a second notification for every one of them.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  name        = "${local.state_machine_name}-timed-out"
  description = "Notify the actor when an archive execution is stopped by the state machine's own timeout."

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
