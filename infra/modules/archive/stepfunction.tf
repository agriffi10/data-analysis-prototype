# ── Archive Step Function: the transfer and the restore arm ──
# Standard state machine, TWO ARMS off one mode Choice. The archive arm: validate-authorize
# and inspect-source once per request, then the transfer manifest, the top-level
# Distributed-Map copy into the vault, the collector, the COMMIT GATE and, on its one
# committing arm, the record, the source deletion and the receipt. The restore arm:
# inspect-archive rebuilds every destination from the archived keys, check-destination-clear
# refuses the whole restore if any of them is occupied, and RestoreReady is where the retrieval
# picks up — the split is at exactly the point where seconds become hours and a free check
# becomes a billed, uncancellable retrieval. The whole-request failure path (a seed →
# RecordFailure → NotifyFailure → Failed) is complete from day one and now carries `mode`,
# because the two arms' failures are worded differently.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction on
# the verbs + log delivery + the Distributed Map's own grants); the verb Lambdas run under
# the ONE shared execution role. Standard (over Express) keeps per-execution history for
# debugging and allows the long copies and the Glacier retrieval wait
# needs — and Express is doubly rejected here, since a Pipe cannot use
# REQUEST_RESPONSE against a Standard machine and this plane's outcome is a
# notification, not a response.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVES WITH THE THING THAT MADE IT NECESSARY. The front door alone
# recorded that this machine could not wedge because nothing in it WAITED: no Map, no
# manifest, no copy. The transfer adds all three, so it adds the ceiling — and with it the
# EventBridge rule below, notify-failure's second door and the raise from 15s to 60s that
# door needs, because a timeout that cannot notify is a failure path satisfied on paper and
# silent in practice. The deploy-role `events:` grant that manages the rule shipped one PR
# ahead of it (the merge apply went red for exactly that ordering). The arithmetic
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
    #
    inspect_source_function_arn           = aws_lambda_function.functions["inspect-source"].arn
    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    rollback_function_arn                 = aws_lambda_function.functions["rollback"].arn
    write_manifest_function_arn           = aws_lambda_function.functions["write-manifest"].arn
    delete_source_function_arn            = aws_lambda_function.functions["delete-source"].arn
    write_receipt_function_arn            = aws_lambda_function.functions["write-receipt"].arn
    # The restore arm's two verbs. The guard is the LAST state before the retrieval starts
    # spending money it cannot get back, which is why both live on this side of the split.
    inspect_archive_function_arn         = aws_lambda_function.functions["inspect-archive"].arn
    check_destination_clear_function_arn = aws_lambda_function.functions["check-destination-clear"].arn
    # The billed half. update-receipt is fed to THREE states, which is deliberate
    # rather than a saving: the receipt records a restore at three stages (requested, restored,
    # incomplete) and the ASL SEEDS which one, so the verb never infers its own stage from what
    # else happens to be lying on the state. copy-objects and collect-transfer-results are the
    # ARCHIVE arm's verbs, reused: the copy-back asks the identical question in the opposite
    # direction, and what differs is only what the answer authorizes.
    build_restore_manifest_function_arn = aws_lambda_function.functions["build-restore-manifest"].arn
    initiate_restore_function_arn       = aws_lambda_function.functions["initiate-restore"].arn
    poll_restore_function_arn           = aws_lambda_function.functions["poll-restore"].arn
    delete_archived_function_arn        = aws_lambda_function.functions["delete-archived"].arn
    update_receipt_function_arn         = aws_lambda_function.functions["update-receipt"].arn
    # The SUCCESS producer, fed to THREE states for the same reason update-receipt is
    # fed to three: the outcome is a property of WHERE the machine is, not of what is on the
    # state, and the three points carry identical keys. The ASL seeds the outcome; the verb never
    # infers it.
    notify_function_arn = aws_lambda_function.functions["notify"].arn
    # Mirrored from cpcommon/transfer/config.py; a test holds the two together.
    transfer_max_items_per_batch = local.transfer_max_items_per_batch
    transfer_map_max_concurrency = local.transfer_map_max_concurrency
    # Mirrored from arcommon/config.py's RESTORE_POLL_SECONDS. The iteration CAP is
    # deliberately not here — poll-restore computes it, so RESTORE_MAX_POLLS has one home.
    restore_poll_seconds = local.restore_poll_seconds
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

# ── The timed-out run's only route to a notification ────────
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT. Step Functions catchers
# cover Task, Parallel and Map states but NOT top-level execution failures, so the machine's own
# RecordFailure -> NotifyFailure path is unreachable on this one failure and the actor would be
# told nothing at all — the exact silence the failure path exists to close. Listening for TIMED_OUT on an
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
