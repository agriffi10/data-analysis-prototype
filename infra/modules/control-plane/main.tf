# The control-plane machine: FIFO request queue and its DLQ, an EventBridge Pipe, a Standard state
# machine and the verbs it runs. README.md carries the shape and every trap the planes share.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = var.dlq_content_based_deduplication
  message_retention_seconds   = 1209600
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = var.content_based_deduplication
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}

# Batch size 1, so each message starts its own execution and per-group ordering holds;
# FIRE_AND_FORGET, because a Standard machine outruns a synchronous call.
resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.this.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

# The definition reads every verb's ARN as <verb>_function_arn (locals.tf).
resource "aws_sfn_state_machine" "this" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile(var.definition_template, merge(
    var.definition_vars,
    local.definition_function_vars,
    local.ceiling_vars,
  ))

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

# A ceiling expires the execution outright and no Catch covers a top-level failure, so the rule
# is the timed-out run's only route to a notification. TIMED_OUT only: every caught failure
# already reaches the notifier, and FAILED would tell it twice.
resource "aws_cloudwatch_event_rule" "execution_timed_out" {
  count = var.ceiling == null ? 0 : 1

  name        = "${local.state_machine_name}-timed-out"
  description = var.ceiling.rule_description

  event_pattern = jsonencode({
    "source"      = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    "detail" = {
      status          = ["TIMED_OUT"]
      stateMachineArn = [local.state_machine_arn]
    }
  })

  lifecycle {
    precondition {
      condition     = contains(keys(var.functions), var.ceiling.notifier_verb)
      error_message = "The ceiling's notifier verb \"${var.ceiling.notifier_verb}\" is not one of this plane's functions, so a timed-out run would tell nobody."
    }
  }
}

resource "aws_cloudwatch_event_target" "execution_timed_out" {
  count = var.ceiling == null ? 0 : 1

  rule = aws_cloudwatch_event_rule.execution_timed_out[0].name
  arn  = try(local.function_arns[var.ceiling.notifier_verb], "")
}

resource "aws_lambda_permission" "execution_timed_out" {
  count = var.ceiling == null ? 0 : 1

  statement_id  = "AllowEventBridgeExecutionTimedOut"
  action        = "lambda:InvokeFunction"
  function_name = try(local.function_arns[var.ceiling.notifier_verb], "")
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.execution_timed_out[0].arn
}
