# ── Control-plane Lambdas (SPEC-050 skeleton; SPEC-062 decomposition) ─────────
# The single 711-line provisioner monolith is decomposed into a validate-authorize
# Lambda + five single-task verb Lambdas (create / add-members / remove-members /
# leave / delete), orchestrated by the Step Function (stepfunction.tf): validate ->
# Choice(action) -> verb. All six run under the shared ORCHESTRATOR role (iam.tf) —
# one role for the Step Function AND every Lambda (user decision
# note) — so each already holds every privileged permission its verb needs.
#
# Code-ownership split (architecture.md): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml builds/ships the Python code
# (lambdas/shared-space-<suffix>/) AND publishes + attaches the shared-code Lambda
# layer. `ignore_changes` keeps `tofu apply` from reverting CI's code OR layer.

# One placeholder package per function so each is valid at create time. CI replaces
# the code (and attaches the common layer); these stubs only ever run pre-deploy.
data "archive_file" "placeholder" {
  for_each = local.shared_space_functions

  type        = "zip"
  output_path = "${path.module}/build/shared-space-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('shared-space-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value)[0]}.py"
  }
}

# Explicit log group per function so retention is managed (14 days; matches SPEC-012/
# 033). Lambda would otherwise create one with infinite retention on first invoke.
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
  timeout       = 60

  # Full env on every function (each reads only what it needs; unused vars are empty).
  # SPEC-056 trusted-actor binding: the validate Lambda verifies the caller's Cognito
  # ID token against the pool JWKS (COGNITO_*); the verbs trust the validated actor.
  environment {
    variables = {
      COGNITO_USER_POOL_ID   = var.user_pool_id
      COGNITO_APP_CLIENT_ID  = var.app_client_id
      ADMIN_BUCKET           = var.athena_admin_bucket_name
      SHARED_SPACE_BUCKET    = var.shared_space_bucket_name
      USER_SPACE_BUCKET      = var.user_space_bucket_name
      PORTAL_ROLE_ARN        = local.portal_role_arn
      MAX_SHARED_MEMBERSHIPS = tostring(var.max_shared_memberships)
      # Target for `create` notifications emitted at each lifecycle terminal
      # outcome (notify.emit_notification). Empty until notifications is wired -> no-op.
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      # Deliberately NOT mirrored by a config._require: a verb that loses this must
      # log to stdout and keep working, never crash the plane at cold start.
      LOGS_QUEUE_URL = var.logs_queue_url
      # `env` shipped empty on every record. Same source of truth as the
      # feature-flag document's `environments` keys (`var.environment`, default "prod").
      ENV_NAME = var.environment
      # NOT used by any shared-space verb — set because the cpcommon layer's
      # config requires it, and any code path may read it. (SPEC-156 FR-004 moved that from
      # import to first read, so this is no longer a cold-start crash — but it is
      # still a failure, and this variable must still be set.) Landed and applied BEFORE the
      # code that imports cpcommon deploys, so the layer attach can never arrive at a
      # function whose env can't satisfy it.
      ATHENA_WORKGROUP = var.athena_workgroup
    }
  }

  # Bootstrap with the placeholder; CI replaces code + attaches the common layer.
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
