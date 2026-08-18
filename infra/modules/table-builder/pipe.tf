# ── EventBridge Pipe: request queue → Step Function ─────────
# Drains the FIFO request queue into the orchestrator. Batch size 1 so each message
# starts its own execution and the FIFO per-MessageGroupId (= target database)
# ordering (sqs.tf) is preserved.
#
# FIRE_AND_FORGET: the Pipe calls StartExecution on the Standard state machine and
# returns immediately (Standard machines can run longer than a synchronous call
# allows; the create flow polls Athena downstream).
#
# Role boundary: this PIPE role only needs states:StartExecution (+ SQS consume) — it
# starts the execution but does NOT run it. The state machine runs under the SFN role
# (stepfunction.tf role_arn), and each verb Lambda runs under its OWN per-verb role.

resource "aws_pipes_pipe" "requests" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe.arn

  source = aws_sqs_queue.requests.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target = aws_sfn_state_machine.table_builder.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
