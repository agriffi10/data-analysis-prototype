# ── EventBridge Pipe: request queue → Step Function ────────
# Drains the FIFO request queue into the orchestrator. Batch size 1 so each message
# starts its own execution and the FIFO per-MessageGroupId ordering is preserved.
#
# FIRE_AND_FORGET, and REQUEST_RESPONSE is not merely unused — it is IMPOSSIBLE for a
# Standard state machine. The Pipe calls StartExecution and returns immediately; the
# outcome reaches the user as a notification, never as a response.
#
# THIS IS THE RESOURCE THAT MAKES THE LOCK NECESSARY. Because the Pipe returns without
# waiting, ordered delivery does not serialize execution, and two operations in one space
# can run at once. Reading this file as "FIFO handles it" is the mistake the per-space
# lock exists to correct.
#
# Role boundary: this PIPE role only needs states:StartExecution (+ SQS consume) — it
# starts the execution but does NOT run it. The state machine runs under the SFN role
# (stepfunction.tf role_arn); the verb Lambdas run under the ONE shared execution role.
#
# At-least-once delivery does NOT give this plane a re-run: the Pipe cannot name the
# executions it starts, and a redelivered message either returns the original ARN or
# fails with ExecutionAlreadyExists. Recovery is the DLQ drain, never redelivery.

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
