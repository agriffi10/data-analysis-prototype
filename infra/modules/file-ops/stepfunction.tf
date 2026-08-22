# ── File-ops Step Function ────────────────────────────────────────────────
# Standard state machine — validate-authorize, the lock's waiting loop, a branch per
# operation and the whole-request failure path. Standard over Express keeps per-execution
# history for debugging and allows the long waits this machine takes by design; Express is
# doubly rejected, since a Pipe cannot use REQUEST_RESPONSE against a Standard machine and
# this plane's outcome is a notification rather than a response.
#
# The state machine runs under its OWN role (iam.tf: InvokeFunction on the verbs + log
# delivery); the verb Lambdas run under the ONE shared execution role.
#
# THE TOP-LEVEL TimeoutSeconds SHIPS FROM THE FIRST VERSION, unlike the planes whose
# ceiling arrived with their transfer. This machine can wedge before it does any data work
# at all, because the waiting loop is in it from day one: a request whose lock is held by
# something that never finishes would otherwise sit in a Wait/re-acquire cycle for a YEAR,
# which is Step Functions' own default. The arithmetic behind the number is in locals.tf,
# where a test computes the give-up bound against it.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "file_ops" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn = aws_lambda_function.functions["validate-authorize"].arn
    acquire_lock_function_arn       = aws_lambda_function.functions["acquire-lock"].arn
    release_lock_function_arn       = aws_lambda_function.functions["release-lock"].arn
    inspect_source_function_arn     = aws_lambda_function.functions["inspect-source"].arn
    check_destinations_function_arn = aws_lambda_function.functions["check-destinations"].arn
    notify_failure_function_arn     = aws_lambda_function.functions["notify-failure"].arn

    build_transfer_manifest_function_arn  = aws_lambda_function.functions["build-transfer-manifest"].arn
    copy_objects_function_arn             = aws_lambda_function.functions["copy-objects"].arn
    collect_transfer_results_function_arn = aws_lambda_function.functions["collect-transfer-results"].arn
    delete_source_function_arn            = aws_lambda_function.functions["delete-source"].arn
    finalise_outcomes_function_arn        = aws_lambda_function.functions["finalise-outcomes"].arn

    # The Map's shape. Mirrored from cpcommon/transfer/config.py — ASL cannot import
    # Python, and a test asserts the rendered numbers still equal the constants the batch
    # verb's own bounds are computed against.
    transfer_max_items_per_batch = local.transfer_max_items_per_batch
    transfer_map_max_concurrency = local.transfer_map_max_concurrency
    # The ASL Wait between re-acquire attempts. Mirrored from focommon/config.py because
    # ASL cannot import Python; a test holds the two equal.
    lock_wait_seconds = local.lock_wait_seconds
    # A TOP-LEVEL ASL field. See the local for the arithmetic and for why it is
    # provisional.
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
# A top-level TimeoutSeconds expiry terminates the execution OUTRIGHT. Step Functions
# catchers cover Task, Parallel and Map states but NOT top-level execution failures, so the
# machine's own RecordFailure -> NotifyFailure path is unreachable on this one failure and
# the actor would be told nothing at all — the exact silence the failure path exists to
# close. Listening for TIMED_OUT on an EventBridge bus is the documented remedy, and this
# is it. Same shape as the neighbouring planes', which is the point: three planes with one
# failure mode should not have three answers to it.
#
# TIMED_OUT ONLY, never FAILED. Every other whole-request failure already reaches
# NotifyFailure through a Catch, so matching FAILED here would send a second notification
# for every one of them.
#
# THIS DOOR DELIBERATELY DOES NOT RELEASE THE LOCK. By the time it fires the execution is
# already gone and the lock may have been stolen by a later arrival — releasing here would
# overwrite that new holder's claim and reintroduce exactly the concurrency the lock
# exists to prevent, from its own cleanup. The stale-lock steal is the recovery.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  name        = "${local.state_machine_name}-timed-out"
  description = "Notify the actor when a file-operations execution is stopped by the state machine's own timeout."

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

# Resource-based grant so the rule (events.amazonaws.com) may invoke the notifier — the
# same reason the DLQ drain's sweep needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "execution_timed_out" {
  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.functions["notify-failure"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out.arn
}
