# ── EventBridge Pipe: request queue → Step Function ─────────
# Batch size 1, so each message starts its own execution and the per-MessageGroupId ordering is
# preserved. FIRE_AND_FORGET matters more here than anywhere else in the codebase — a
# data-quality execution polls an Athena query that can run for TENS OF MINUTES.
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

  target = aws_sfn_state_machine.data_quality.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [aws_iam_role_policy.pipe]
}
