# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.table_builder_functions. CI owns the code and every layer:
# cpcommon + tbcommon on all of them, plus polars on infer-schema. README.md.

# One placeholder per function so each is valid at create time.
data "archive_file" "placeholder" {
  for_each = local.table_builder_functions

  type        = "zip"
  output_path = "${path.module}/build/table-builder-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('table-builder-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.table_builder_functions

  name              = local.table_builder_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.table_builder_functions

  function_name = local.table_builder_function_names[each.key]
  role          = aws_iam_role.execution.arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # ⚠ EVERY variable tbcommon/config.py requires must be COMMON to all verbs — the layer's
  # config runs on any import chain, so a verb missing one fails. This caused the 2026-07-05
  # production break (check-table-absent: COGNITO_USER_POOL_ID unset at cold start).
  # local.table_builder_verb_env is for OPTIONAL action env only.
  environment {
    variables = merge(
      {
        USER_SPACE_BUCKET       = var.user_space_bucket_name
        SHARED_SPACE_BUCKET     = var.shared_space_bucket_name
        ADMIN_BUCKET            = var.admin_bucket_name
        NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
        # Deliberately NOT mirrored by a config._require — see variables.tf.
        LOGS_QUEUE_URL = var.logs_queue_url
        # Same source of truth as the feature-flag document's `environments` keys.
        ENV_NAME         = var.environment
        ATHENA_WORKGROUP = var.athena_workgroup
      },
      lookup(local.table_builder_verb_env, each.key, {}),
    )
  }

  # Bootstrap with the placeholder; CI replaces the code and attaches the layers.
  filename         = data.archive_file.placeholder[each.key].output_path
  source_code_hash = data.archive_file.placeholder[each.key].output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment — never revert either on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.execution,
    aws_cloudwatch_log_group.functions,
  ]
}
