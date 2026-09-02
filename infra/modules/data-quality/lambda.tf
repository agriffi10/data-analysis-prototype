# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.data_quality_functions, each a call to the fleet's one container
# module. CI owns which image they run. ../../info/control-plane-shape.md.

module "functions" {
  source   = "../docker-lambda"
  for_each = local.data_quality_functions

  function_name        = local.data_quality_function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  # The handler string the zip-packaged function carried, now the image's command.
  command = [each.value.handler]

  timeout_seconds = each.value.timeout
  memory_mb       = each.value.memory

  # ⚠ EVERY variable cpcommon/config.py requires must be COMMON to all nine verbs — any of
  # them may reach any of those values. The per-verb map is for OPTIONAL action env only.
  #
  # ATHENA_WORKGROUP is the SHARED portal workgroup. A DEDICATED one fails Lake Formation's
  # Create/Describe checks even for an LF-admin role, because Athena ties LF to the workgroup —
  # measured live. The cost is the portal workgroup's scan cutoff. README.md.
  environment = merge(
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

  # The log group is the module's, so it is no longer named here — a function and its log group
  # cannot be declared in two places and disagree.
  depends_on = [aws_iam_role_policy.execution]
}
