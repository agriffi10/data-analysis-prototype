# ── EventBridge Pipe: request queue → Step Function ─────────
# Drains the FIFO request queue into the orchestrator. Batch size 1 so each message
# starts its own execution and the FIFO single-MessageGroupId ordering (sqs.tf) is
# preserved — strictly serial intake.
#
# FIRE_AND_FORGET: the Pipe calls StartExecution on the Standard state machine and
# returns immediately (Standard machines can run longer than a synchronous call
# allows). Serial *intake* + the registry conditional-put is what makes
# duplicate names impossible; see the sqs.tf header.
#
# Role boundary: this PIPE role only needs states:StartExecution (+ SQS consume) —
# it starts the execution but does NOT run it. The state machine then runs under the
# ORCHESTRATOR role (stepfunction.tf role_arn), which is what holds lambda:InvokeFunction
# and the Glue/LF/S3/Cognito grants used once SPEC-051+ fill in the action bodies.

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
