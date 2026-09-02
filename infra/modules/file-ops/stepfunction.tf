# ── File-ops Step Function ────────────────────────────────────────────────────
# Standard, which Express doubly cannot be: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds SHIPS FROM THE FIRST VERSION, unlike the planes whose ceiling
# arrived with their transfer — this machine can wedge before it does any data work at all,
# because the waiting loop is in it from day one. The arithmetic is in locals.tf. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "file_ops" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn = module.functions["validate-authorize"].function_arn
    acquire_lock_function_arn       = module.functions["acquire-lock"].function_arn
    release_lock_function_arn       = module.functions["release-lock"].function_arn
    inspect_source_function_arn     = module.functions["inspect-source"].function_arn
    check_destinations_function_arn = module.functions["check-destinations"].function_arn
    notify_failure_function_arn     = module.functions["notify-failure"].function_arn

    build_transfer_manifest_function_arn  = module.functions["build-transfer-manifest"].function_arn
    copy_objects_function_arn             = module.functions["copy-objects"].function_arn
    collect_transfer_results_function_arn = module.functions["collect-transfer-results"].function_arn
    delete_source_function_arn            = module.functions["delete-source"].function_arn
    finalise_outcomes_function_arn        = module.functions["finalise-outcomes"].function_arn
    notify_function_arn                   = module.functions["notify"].function_arn

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
# Catchers do not cover top-level execution failures, so the machine's own NotifyFailure path
# is unreachable on this one failure and the actor would be told nothing at all. Same shape as
# the neighbouring planes': three planes with one failure mode should not have three answers.
#
# TIMED_OUT ONLY, NEVER FAILED, or every caught failure double-notifies.
#
# ⚠ THIS DOOR DELIBERATELY DOES NOT RELEASE THE LOCK. By the time it fires the execution is
# gone and the lock may have been STOLEN by a later arrival — releasing here would overwrite
# that new holder's claim and reintroduce the very concurrency the lock exists to prevent,
# from its own cleanup. The stale-lock steal is the recovery. README.md.
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
