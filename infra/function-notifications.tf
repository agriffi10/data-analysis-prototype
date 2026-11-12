# Notifications: a FIFO queue that triggers its single writer directly (an event-source mapping —
# no Pipe, no Step Function). The writer is the only writer of each user's notifications.json in
# the user-space bucket. Reasoning: functions/notifications/README.md.
#
# FIFO with MessageGroupId = the TARGET USERNAME. That, plus batch size 1, is what makes
# single-writer-per-user true without a lock.
#
# Its DLQ is DELIBERATELY UNDRAINED, and it is the one hole the drain cannot close: the drain's
# only delivery channel IS this queue, so draining it is circular. A message there is visible only
# to someone who looks, and the 14-day retention is what buys them the time.
#
# The queue's name, ARN and URL are the constructed locals in main.tf that every producer scopes to.

locals {
  notifications_writer_function_name = "${var.project_name}-${var.environment}-notifications-writer"

  notifications_writer_environment = {
    USER_SPACE_BUCKET = local.user_space_bucket_name
    NOTIFICATIONS_MAX = "200"
    # The portal role's IAM unique ID — the half of SenderId before the ':'. NEVER the role name
    # or ARN: SenderId carries neither, and a wrong value never matches, which reads exactly like a
    # control that works. Unset, the writer refuses EVERY create. The output
    # notifications_writer_role_arn carries the precondition that refuses a wrong wire at plan.
    NOTIFICATIONS_UNTRUSTED_SENDER_ID = module.data.portal_role_unique_id
    # Optional BY CONSTRUCTION — observability reads it with os.environ.get, so a writer without
    # it logs to stdout rather than failing at cold start.
    #
    # ADMIN_BUCKET, SHARED_SPACE_BUCKET and ATHENA_WORKGROUP are absent ON PURPOSE, and a probe
    # imports the module without them (test_layer_import_safety.py).
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }
}

module "notifications" {
  source = "./modules/queue-consumer"

  queue_name = local.notifications_queue_name
  dlq_name   = "${var.project_name}-${var.environment}-notifications-requests-dlq.fifo"

  # DEDUPLICATION IS PER RECIPIENT. Most producers key a notice on a request id, and a request id
  # is chosen by whoever sent the request. Deduplicated across the whole queue, a request carrying
  # somebody else's id dropped that person's notice if it landed within five minutes. Scoped to
  # the message group — the recipient's username — two notices collapse only when they go to the
  # same person, which is every duplicate a producer means to collapse.
  content_based_deduplication = true
  deduplication_scope         = "messageGroup"

  function_name = local.notifications_writer_function_name
  role_name     = "${var.project_name}-${var.environment}-notifications-writer-role"

  # May read and write ANY user's notifications.json and nothing else app-relevant. NO
  # DeleteObject anywhere. The s3:ListBucket is NOT dead weight: without it a GetObject on a key
  # that does not yet exist returns 403, not NoSuchKey, so a new user's first notification could
  # never bootstrap.
  role_policy = templatefile("${path.root}/functions/notifications/writer.json.tftpl", {
    user_space_bucket_arn = "arn:aws:s3:::${local.user_space_bucket_name}"
    request_queue_arn     = local.notifications_queue_arn
    lambda_log_group_arn  = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.notifications_writer_function_name}"
    logs_queue_arn        = module.observability.logs_queue_arn
  })

  handler = "notifications_writer.handler"
  # Declared rather than left to the provider's default: an unset tier is invisible in the plan
  # and shows up only as a production OOM.
  memory_mb             = 128
  environment_variables = local.notifications_writer_environment

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # base grants the deploy role its SQS/Lambda/event-source-mapping/IAM/logs perms; data creates
  # the portal role whose unique ID the writer refuses a `create` from. Both settle first.
  depends_on = [module.base, module.data]
}
