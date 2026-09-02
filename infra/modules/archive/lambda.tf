# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.archive_functions, each a call to the fleet's one container
# module. CI owns which image they run. ../../info/control-plane-shape.md.

module "functions" {
  source   = "../docker-lambda"
  for_each = local.archive_functions

  function_name        = local.archive_function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  # The handler string the zip-packaged function carried, now the image's command. One image
  # serves the whole fleet and this is the only thing that differs between its functions.
  command = [each.value.handler]

  timeout_seconds = each.value.timeout
  memory_mb       = each.value.memory

  # ⚠ EVERY variable cpcommon/config.py requires must be COMMON to all verbs. A missing one
  # surfaces as a failed REQUEST rather than a failed deploy. The per-verb map is for OPTIONAL
  # action env only.
  #
  # ARCHIVE_BUCKET is this plane's own addition to that shared set — no other plane sets it.
  environment = merge(
    {
      ADMIN_BUCKET        = var.admin_bucket_name
      USER_SPACE_BUCKET   = var.user_space_bucket_name
      SHARED_SPACE_BUCKET = var.shared_space_bucket_name
      ARCHIVE_BUCKET      = var.archive_bucket_name
      # Optional in cpcommon.config — unset means emits are logged no-ops.
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      # Deliberately NOT mirrored by a config._require — see variables.tf.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    },
    lookup(local.archive_verb_env, each.key, {}),
  )

  # The log group is the module's, so it is no longer named here — a function and its log group
  # cannot be declared in two places and disagree.
  depends_on = [aws_iam_role_policy.execution]
}
