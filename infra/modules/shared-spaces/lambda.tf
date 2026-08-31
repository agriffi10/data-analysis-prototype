# ── The verb Lambdas ─────────────────────────────────────────────────────────
# validate-authorize plus one single-task verb per action, all running under the shared
# ORCHESTRATOR role. CI owns the code and the layer. ../../info/control-plane-shape.md.

# One placeholder per function so each is valid at create time.
data "archive_file" "placeholder" {
  for_each = local.shared_space_functions

  type        = "zip"
  output_path = "${path.module}/build/shared-space-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('shared-space-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value)[0]}.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.shared_space_functions

  name              = "/aws/lambda/${local.shared_space_function_names[each.key]}"
  retention_in_days = 14

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_lambda_function" "functions" {
  for_each = local.shared_space_functions

  function_name = local.shared_space_function_names[each.key]
  role          = aws_iam_role.orchestrator.arn
  runtime       = "python3.12"
  handler       = each.value

  # A verb touches one space and 60s is generous for that. The one-shot backfill walks EVERY
  # registry record instead, and it has no resume marker — each run restarts from the first
  # key — so a timeout is not a partial pass it can continue from but a run that made no
  # progress. Its ceiling is sized to the whole walk rather than to one space.
  timeout = lookup(local.shared_space_function_timeouts, each.key, 60)

  # Full env on every function. The validate Lambda verifies the caller's token against the
  # pool for member lookups; the verbs trust the validated actor.
  #
  # NOTE: these verbs set a timeout and NEVER a memory_size, leaving the AWS default of 128 MB.
  # An unset memory tier is invisible in the plan and only shows up as an OOM in production;
  # modules/data-quality sets both explicitly and records this as the precedent it fixes.
  environment {
    variables = {
      COGNITO_USER_POOL_ID   = var.user_pool_id
      ADMIN_BUCKET           = var.athena_admin_bucket_name
      SHARED_SPACE_BUCKET    = var.shared_space_bucket_name
      USER_SPACE_BUCKET      = var.user_space_bucket_name
      PORTAL_ROLE_ARN        = local.portal_role_arn
      MAX_SHARED_MEMBERSHIPS = tostring(var.max_shared_memberships)
      # Deliberately NOT mirrored by a config._require: a verb that loses this must log to
      # stdout and keep working, never crash the plane at cold start.
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      # Deliberately NOT mirrored by a config._require: a verb that loses this must
      # log to stdout and keep working, never crash the plane at cold start.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
      # NOT read by any verb here — set because the cpcommon layer's config requires it, and
      # it LANDED AND APPLIED BEFORE the code that imports cpcommon deployed, so the layer
      # attach can never reach a function whose env cannot satisfy it.
      ATHENA_WORKGROUP = var.athena_workgroup
    }
  }

  # Bootstrap with the placeholder; CI replaces the code and attaches the layer.
  filename         = data.archive_file.placeholder[each.key].output_path
  source_code_hash = data.archive_file.placeholder[each.key].output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment — never revert them on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.orchestrator,
    aws_cloudwatch_log_group.functions,
    time_sleep.wait_for_deploy_policy,
  ]
}
