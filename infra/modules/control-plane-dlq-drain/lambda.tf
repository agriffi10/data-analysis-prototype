# ── The drain Lambda + its four triggers (SPEC-126 FR-001/FR-005) ────────────
# ONE function on FOUR queues. The per-domain differences (the user-facing noun, the field
# the actor's token lives in) are a table inside the handler keyed off the record's
# eventSourceARN, so a fifth control plane is one map entry and one mapping — not a fifth
# copy of this file.
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
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      # The drain itself needs only the Cognito pair + the queue URL. The buckets and the
      # workgroup are here because the cpcommon layer's config._require runs AT IMPORT for
      # every function that attaches it — a function missing one crashes at COLD START,
      # never at the line that would have used it (the table-builder break, PR #196).
      COGNITO_USER_POOL_ID    = var.user_pool_id
      COGNITO_APP_CLIENT_ID   = var.app_client_id
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
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

# One event-source mapping per drained DLQ. Batch size 5 (not 1): each record is handled
# independently and a partial failure is impossible by construction — the handler is total —
# so batching only reduces invocations. These queues are, by design, almost always empty.
#
# NO `function_response_types = ["ReportBatchItemFailures"]`, and that is the point rather
# than an omission: reporting a failure would ask SQS to REDELIVER, and a message that
# always fails would then be redelivered until retention expires, burning invocations on a
# failure nobody is watching — the exact invisibility this module exists to end (FR-005).
#
# NO DLQ ON THE DRAIN. A handler that cannot fail does not need one, and a second-order DLQ
# would be exactly as unwatched as the first-order ones this module drains.
resource "aws_lambda_event_source_mapping" "drain" {
  for_each = local.dlq_by_name

  event_source_arn = each.value
  function_name    = aws_lambda_function.drain.arn
  batch_size       = 5
  enabled          = true

  depends_on = [aws_iam_role_policy.drain]
}
