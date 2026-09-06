# ── The verb Lambdas ─────────────────────────────────────────────────────────
# Entirely for_each over local.results_conversion_functions, each a call to the fleet's one
# container module. CI owns which image they run; what a verb can import is a property of that
# image rather than of a layer attachment.

module "functions" {
  source   = "../docker-lambda"
  for_each = local.results_conversion_functions

  function_name        = local.results_conversion_function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  command = [each.value.handler]

  timeout_seconds = each.value.timeout
  memory_mb       = each.value.memory

  # Declared for every verb, not only the one that raises it: the module's own rule is that a
  # plan-visible attribute is always set, because one the configuration omits comes back UNKNOWN
  # in a replacement plan. 512 is Lambda's own default, so the four small verbs plan no diff.
  ephemeral_storage_mb = try(each.value.ephemeral, 512)

  # ⚠ EVERY variable the shared code requires must be COMMON to all verbs — a verb missing one
  # fails at COLD START, where no test and no deploy can see it. The per-verb map is for
  # OPTIONAL action env only.
  environment = merge(
    {
      ADMIN_BUCKET        = var.admin_bucket_name
      USER_SPACE_BUCKET   = var.user_space_bucket_name
      SHARED_SPACE_BUCKET = var.shared_space_bucket_name
      ATHENA_WORKGROUP    = var.athena_workgroup
      # Optional — unset means every emit is a logged no-op.
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      # Deliberately NOT mirrored by a required-config read, so a verb missing it logs
      # to stdout rather than crashing the plane at cold start.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    },
    lookup(local.results_conversion_verb_env, each.key, {}),
  )

  depends_on = [aws_iam_role_policy.execution]
}
