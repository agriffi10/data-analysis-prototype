# ── Archive Step Function: the archive arm and the restore arm ──
# Standard, TWO ARMS off one mode Choice, sharing a machine because a restore is meaningless
# without the archive that produced it.
#
# THE RESTORE'S SPLIT IS AT EXACTLY THE POINT WHERE SECONDS BECOME HOURS and a free check
# becomes a billed, uncancellable retrieval: inspect-archive and check-destination-clear sit
# BEFORE RestoreReady.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVED WITH THE THING THAT MADE IT NECESSARY, and with it the
# EventBridge rule, notify-failure's second door and its raise to 60s — a timeout that cannot
# notify is a failure path satisfied on paper and silent in practice. The deploy-role `events:`
# grant shipped ONE PR AHEAD; the merge apply went red for exactly that ordering. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "archive" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn = module.functions["validate-authorize"].function_arn
    notify_failure_function_arn     = module.functions["notify-failure"].function_arn
    #
    inspect_source_function_arn           = module.functions["inspect-source"].function_arn
    build_transfer_manifest_function_arn  = module.functions["build-transfer-manifest"].function_arn
    copy_objects_function_arn             = module.functions["copy-objects"].function_arn
    collect_transfer_results_function_arn = module.functions["collect-transfer-results"].function_arn
    rollback_function_arn                 = module.functions["rollback"].function_arn
    write_manifest_function_arn           = module.functions["write-manifest"].function_arn
    delete_source_function_arn            = module.functions["delete-source"].function_arn
    write_receipt_function_arn            = module.functions["write-receipt"].function_arn
    # The guard is the LAST state before the retrieval starts spending money it cannot get
    # back, which is why both live on this side of the split.
    inspect_archive_function_arn         = module.functions["inspect-archive"].function_arn
    check_destination_clear_function_arn = module.functions["check-destination-clear"].function_arn
    # The billed half. update-receipt is fed to THREE states deliberately: the ASL SEEDS which
    # stage, so the verb never infers its own from what else is on the state. copy-objects and
    # collect-transfer-results are the ARCHIVE arm's, reused — the copy-back asks the identical
    # question in the opposite direction.
    build_restore_manifest_function_arn = module.functions["build-restore-manifest"].function_arn
    initiate_restore_function_arn       = module.functions["initiate-restore"].function_arn
    poll_restore_function_arn           = module.functions["poll-restore"].function_arn
    delete_archived_function_arn        = module.functions["delete-archived"].function_arn
    update_receipt_function_arn         = module.functions["update-receipt"].function_arn
    # The SUCCESS producer, fed to THREE states: the outcome is a property of WHERE the machine
    # is, not of what is on the state. The ASL seeds it; the verb never infers it.
    notify_function_arn = module.functions["notify"].function_arn
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
# Catchers do not cover top-level execution failures, so the machine's own NotifyFailure path
# is unreachable on this one failure and the actor would be told nothing at all.
#
# TIMED_OUT ONLY, NEVER FAILED, or every caught failure double-notifies. README.md.
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
  arn  = module.functions["notify-failure"].function_arn
}

# Resource-based grant so the rule (events.amazonaws.com) may invoke the notifier — the same
# reason the DLQ drain's sweep needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = module.functions["notify-failure"].function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
