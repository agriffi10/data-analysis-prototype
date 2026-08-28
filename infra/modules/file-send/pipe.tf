# ── EventBridge Pipe: request queue → Step Function ────────
# Batch size 1, so each message starts its own execution and the per-MessageGroupId ordering is
# preserved. FIRE_AND_FORGET, and REQUEST_RESPONSE is not merely unused — it is IMPOSSIBLE for
# a Standard machine.
#
# AT-LEAST-ONCE DELIVERY DOES NOT GIVE THIS PLANE A RE-RUN: the Pipe cannot name the executions
# it starts, and a redelivered message either returns the original ARN or fails with
# ExecutionAlreadyExists (measured 2026-08-10). RECOVERY IS THE DLQ DRAIN. README.md.

resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.file_send.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
