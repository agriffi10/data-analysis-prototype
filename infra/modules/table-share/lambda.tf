# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.table_share_functions. CI owns the code and both layers
# (cpcommon + tscommon). ../../info/control-plane-shape.md.

# One placeholder per function so each is valid at create time.
data "archive_file" "placeholder" {
  for_each = local.table_share_functions

  type        = "zip"
  output_path = "${path.module}/build/table-share-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('table-share-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.table_share_functions

  name              = local.table_share_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.table_share_functions

  function_name = local.table_share_function_names[each.key]
  role          = aws_iam_role.execution.arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # ⚠ EVERY variable tscommon/config.py requires must be COMMON to all verbs — the layer's
  # config runs on any import chain, so a verb missing one fails at cold start. The per-verb
  # map is for OPTIONAL action env only.
  environment {
    variables = merge(
      {
        ADMIN_BUCKET         = var.admin_bucket_name
        USER_SPACE_BUCKET    = var.user_space_bucket_name
        SHARED_SPACE_BUCKET  = var.shared_space_bucket_name
        COGNITO_USER_POOL_ID = var.user_pool_id
        ATHENA_WORKGROUP     = var.athena_workgroup
        # Optional in tscommon.config — unset ⇒ emits are logged no-ops.
        NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
        # Deliberately NOT mirrored by a config._require — see variables.tf.
        LOGS_QUEUE_URL = var.logs_queue_url
        # Same source of truth as the feature-flag document's `environments` keys.
        ENV_NAME = var.environment
      },
      lookup(local.table_share_verb_env, each.key, {}),
    )
  }

  # Bootstrap with the placeholder; CI replaces the code and attaches the layers.
  filename         = data.archive_file.placeholder[each.key].output_path
  source_code_hash = data.archive_file.placeholder[each.key].output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment — never revert them on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.execution,
    aws_cloudwatch_log_group.functions,
  ]
}
