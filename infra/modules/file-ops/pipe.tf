# ── EventBridge Pipe: request queue → Step Function ────────
# Batch size 1. FIRE_AND_FORGET, and REQUEST_RESPONSE is IMPOSSIBLE for a Standard machine.
#
# ⚠ THIS IS THE RESOURCE THAT MAKES THE LOCK NECESSARY. Because the Pipe returns without
# waiting, ORDERED DELIVERY DOES NOT SERIALIZE EXECUTION and two operations in one space can
# run at once. Reading this as "FIFO handles it" is the mistake the per-space lock corrects.
#
# At-least-once delivery gives no re-run: a redelivered message returns the original ARN or
# fails with ExecutionAlreadyExists. RECOVERY IS THE DLQ DRAIN. README.md.

resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.file_ops.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
