# ── EventBridge Pipe: request queue → Step Function ────────
# Batch size 1. FIRE_AND_FORGET, and REQUEST_RESPONSE is IMPOSSIBLE for a Standard machine.
#
# ⚠ SO ORDERED DELIVERY DOES NOT SERIALIZE EXECUTION. The Pipe returns once StartExecution does,
# and the next message in the group starts a second run while the first is still going. This
# plane holds no lock; README.md says what overlap costs, and why two archives survive it only
# when their request ids differ.
#
# At-least-once delivery gives no re-run: a redelivered message returns the original ARN or
# fails with ExecutionAlreadyExists (measured 2026-08-10). RECOVERY IS THE DLQ DRAIN.
# ../../info/control-plane-shape.md.

resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.archive.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
