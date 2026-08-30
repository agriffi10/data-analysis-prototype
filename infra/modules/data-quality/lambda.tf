# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.data_quality_functions. CI owns the code and the layers:
# cpcommon + dqcommon on all nine, plus polars on inspect-source.
# ../../info/control-plane-shape.md.

# One placeholder per function so each is valid at create time.
data "archive_file" "placeholder" {
  for_each = local.data_quality_functions

  type        = "zip"
  output_path = "${path.module}/build/data-quality-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('data-quality-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.data_quality_functions

  name              = local.data_quality_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.data_quality_functions

  function_name = local.data_quality_function_names[each.key]
  role          = aws_iam_role.execution.arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # ⚠ EVERY variable cpcommon/config.py requires must be COMMON to all nine verbs — any of
  # them may reach any of those values. The per-verb map is for OPTIONAL action env only.
  #
  # ATHENA_WORKGROUP is the SHARED portal workgroup. A DEDICATED one fails Lake Formation's
  # Create/Describe checks even for an LF-admin role, because Athena ties LF to the workgroup —
  # measured live. The cost is the portal workgroup's scan cutoff. README.md.
  environment {
    variables = merge(
      {
        USER_SPACE_BUCKET       = var.user_space_bucket_name
        SHARED_SPACE_BUCKET     = var.shared_space_bucket_name
        ADMIN_BUCKET            = var.admin_bucket_name
        ATHENA_WORKGROUP        = var.athena_workgroup
        NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
        # Optional by construction: a function missing it logs to stdout rather than
        # failing at cold start.
        LOGS_QUEUE_URL = var.logs_queue_url
        ENV_NAME       = var.environment
      },
      lookup(local.data_quality_verb_env, each.key, {}),
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
