# ── Notifications-writer Lambda and its trigger ───────────────────────────
# The single writer of every user's notifications.json, triggered directly by the queue.
# Terraform owns the function INFRASTRUCTURE; CI owns which image it runs. README.md.

module "writer" {
  source = "../docker-lambda"

  function_name        = local.writer_function_name
  role_arn             = aws_iam_role.writer.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["notifications_writer.handler"]
  timeout_seconds      = 30

  # Declared rather than left to the provider's default: an unset tier is invisible in the plan
  # and shows up only as a production OOM.
  memory_mb = 128

  environment = merge({
    USER_SPACE_BUCKET = var.user_space_bucket_name
    NOTIFICATIONS_MAX = tostring(var.notifications_max)
    # The portal role's IAM unique ID — the half of SenderId before the ':'. NEVER the
    # role name or ARN: SenderId carries neither, and a wrong value never matches, which
    # reads exactly like a control that works. Unset, the writer refuses EVERY create.
    NOTIFICATIONS_UNTRUSTED_SENDER_ID = var.portal_role_unique_id
    # Optional BY CONSTRUCTION — observability reads it with os.environ.get, so a writer
    # without it logs to stdout rather than failing at cold start.
    #
    # ADMIN_BUCKET, SHARED_SPACE_BUCKET and ATHENA_WORKGROUP are absent ON PURPOSE, and a
    # probe imports the module without them (test_layer_import_safety.py). README.md.
    LOGS_QUEUE_URL = var.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  })

  depends_on = [aws_iam_role_policy.writer]
}

# Batch size 1 so each FIFO message is its own invocation — this is what preserves the
# per-user one-at-a-time processing the single-writer model relies on.
resource "aws_lambda_event_source_mapping" "writer" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = module.writer.function_arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.writer]
}
