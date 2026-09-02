# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.table_share_functions, each a call to the fleet's one container
# module. CI owns which image they run. ../../info/control-plane-shape.md.

module "functions" {
  source   = "../docker-lambda"
  for_each = local.table_share_functions

  function_name        = local.table_share_function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  # The handler string the zip-packaged function carried, now the image's command.
  command = [each.value.handler]

  timeout_seconds = each.value.timeout
  memory_mb       = each.value.memory

  # ⚠ EVERY variable tscommon/config.py requires must be COMMON to all verbs — the shared
  # config runs on any import chain, so a verb missing one fails at cold start. The per-verb
  # map is for OPTIONAL action env only.
  environment = merge(
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

  # The log group is the module's, so it is no longer named here — a function and its log group
  # cannot be declared in two places and disagree.
  depends_on = [aws_iam_role_policy.execution]
}
