# ── EventBridge Pipe: request queue → Step Function ────────
# Batch size 1. FIRE_AND_FORGET, and REQUEST_RESPONSE is IMPOSSIBLE for a Standard machine.
#
# Because the Pipe returns without waiting, ORDERED DELIVERY DOES NOT SERIALIZE EXECUTION: two
# conversions by one user can run at once. This plane needs no lock for that — the only write
# it will ever make is one object, made conditional at the write itself.
#
# At-least-once delivery gives no re-run: a redelivered message returns the original ARN or
# fails with ExecutionAlreadyExists. RECOVERY IS THE DLQ DRAIN.

resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.results_conversion.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
