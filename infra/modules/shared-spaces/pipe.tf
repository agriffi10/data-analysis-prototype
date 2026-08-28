# ── EventBridge Pipe: request queue → Step Function ─────────
# Batch size 1, so the single-MessageGroupId ordering is preserved — STRICTLY SERIAL INTAKE.
# Serial intake plus the registry's conditional put is what makes duplicate names impossible;
# see sqs.tf. FIRE_AND_FORGET, because a Standard machine outruns a synchronous call.
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

  target = aws_sfn_state_machine.orchestrator.arn
  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  depends_on = [
    aws_iam_role_policy.pipe,
    time_sleep.wait_for_deploy_policy,
  ]
}
