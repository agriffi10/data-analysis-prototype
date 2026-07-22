# ── The drain Lambda + its scheduled sweep (SPEC-126 FR-001/FR-005) ──────────
# ONE function over FOUR queues. The per-domain differences (the user-facing noun, the field
# the actor's token lives in) are a table inside the handler keyed off the queue's ARN, so a
# fifth control plane is one map entry and one more ARN in DLQ_ARNS — not a fifth copy of
# this file.
#
# Code-ownership split (architecture.md, SPEC-012): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml owns the Python code and attaches
# the cpcommon layer. `ignore_changes` keeps `tofu apply` from reverting CI's deployed code.

data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/control-plane-dlq-drain-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('control-plane-dlq-drain Lambda code not yet deployed by CI')\n"
    filename = "dlq_drain.py"
  }
}

# Explicit log group so retention is managed (Lambda would otherwise create one with
# infinite retention on first invoke). 14 days, matching every other function here.
#
# THIS LOG GROUP IS NOW THE ONLY COPY OF A DEAD-LETTERED BODY. Consuming a DLQ message
# deletes it, so the 14-day queue retention the arcs kept "for inspection" is traded for
# this group's 14-day retention (SPEC-126 FR-004) — a deliberate cost, paid so the user
# hears about the failure at all. Shortening this retention shortens the forensic window.
resource "aws_cloudwatch_log_group" "drain" {
  name              = local.log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "drain" {
  function_name = local.function_name
  role          = aws_iam_role.drain.arn
  runtime       = "python3.12"
  handler       = "dlq_drain.handler"
  # Headroom for a full-burst sweep. The handler's per-queue round cap already bounds a sweep
  # well under this; the extra ceiling only covers a pathological backlog on all four queues.
  timeout     = 60
  memory_size = 256

  environment {
    variables = {
      # The drain needs the Cognito pair, the notifications queue URL to send to, and DLQ_ARNS —
      # the queues it now sweeps itself (the four request DLQs, as a JSON list). The buckets and
      # the workgroup are here because the cpcommon layer's config._require runs AT IMPORT for
      # every function that attaches it — a function missing one crashes at COLD START, never at
      # the line that would have used it (the table-builder break, PR #196).
      COGNITO_USER_POOL_ID    = var.user_pool_id
      COGNITO_APP_CLIENT_ID   = var.app_client_id
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      DLQ_ARNS                = jsonencode(var.dlq_arns)
      USER_SPACE_BUCKET       = var.user_space_bucket_name
      SHARED_SPACE_BUCKET     = var.shared_space_bucket_name
      ADMIN_BUCKET            = var.admin_bucket_name
      ATHENA_WORKGROUP        = var.athena_workgroup
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  lifecycle {
    # CI owns the code AND the cpcommon layer attachment — never revert either on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.drain,
    aws_cloudwatch_log_group.drain,
  ]
}

# ── The scheduled sweep trigger (SQS event-source mappings → EventBridge) ─────
# ONE EventBridge rule invokes the drain every 10 minutes; the handler polls all four DLQs
# itself (receive → notify → delete, until empty). This replaced four always-on SQS
# event-source mappings — four managed poll loops on queues that are, by design, almost always
# empty — whose idle long-polling was the bulk of the account's SQS request volume.
#
# NOTHING re-drives a message here (there is still no DLQ on the drain, and the sweep deletes
# every message it reads whether or not it could notify about it): a redelivery would only
# re-run a decision already made about a terminal message — the invisibility this module ends
# (FR-005). Trade-off vs the mappings: a dead-lettered request now surfaces within one interval
# (~10 min) instead of seconds. Nothing watches these queues in real time, so that is immaterial.
resource "aws_cloudwatch_event_rule" "sweep" {
  name                = "${local.function_name}-sweep"
  description         = "Sweep the control-plane request DLQs into user notifications every 10 minutes."
  schedule_expression = "rate(10 minutes)"
}

resource "aws_cloudwatch_event_target" "sweep" {
  rule = aws_cloudwatch_event_rule.sweep.name
  arn  = aws_lambda_function.drain.arn
}

# Resource-based grant so the rule (events.amazonaws.com) may invoke the function — this is why
# the sweep needs no separate invoke role, unlike EventBridge Scheduler. Scoped to this rule's ARN.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowEventBridgeSweep"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.drain.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
