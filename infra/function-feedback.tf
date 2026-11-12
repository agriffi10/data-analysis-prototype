# Feedback: a FIFO queue and its single writer, the same shape as notifications. No Pipe and no
# state machine — there is one verb, and it appends one event to one object. Reasoning:
# functions/feedback/README.md.
#
# The queue's ONLY writer is module.api's execution role, and the API takes the username from the
# verified caller, which is what makes a feedback record attributable. The portal role, which the
# API assumes on a caller's behalf, has no statement naming the queue.
#
# FIFO with MessageGroupId = the SUBMISSION'S UTC DATE, set by the API. That, plus batch size 1,
# is what makes single-writer-per-day true without a lock.
#
# Its DLQ is its own, never another plane's, and DELIBERATELY UNDRAINED (dlq_drain.UNDRAINED_QUEUES):
# the drain notifies from the verified identity in the message body, and this body carries none
# by design. Draining it would mean notifying from an untrusted body field.

locals {
  # Every name here has to match a pattern in
  # modules/base/policies/github-actions-deploy-feedback.json.tftpl, and
  # lambdas/test_feedback_module.py reads them to hold the pair together.
  feedback_requests_queue_name   = "${var.project_name}-${var.environment}-feedback-requests.fifo"
  feedback_dlq_name              = "${var.project_name}-${var.environment}-feedback-requests-dlq.fifo"
  feedback_writer_function_name  = "${var.project_name}-${var.environment}-feedback-writer"
  feedback_writer_role_name      = "${var.project_name}-${var.environment}-feedback-writer-role"
  feedback_lambda_log_group_name = "/aws/lambda/${local.feedback_writer_function_name}"
}

module "feedback" {
  source = "./modules/queue-consumer"

  queue_name = local.feedback_requests_queue_name
  dlq_name   = local.feedback_dlq_name

  # OFF on purpose. The API sets an explicit MessageDeduplicationId (the event id) on every send,
  # and with the fallback available a send that stopped setting one would still mostly collapse
  # double-submits — so the guard would be gone with nothing going red. A test pins this value.
  content_based_deduplication = false

  function_name = local.feedback_writer_function_name
  role_name     = local.feedback_writer_role_name

  # Reads and writes objects under the admin bucket's feedback/ prefix and nothing else. NO
  # DeleteObject — the records are somebody's only copy. NO s3:ListBucket, by decision: the writer
  # treats ANY read failure as "no object", which makes the following write create-only.
  role_policy = templatefile("${path.root}/functions/feedback/writer.json.tftpl", {
    admin_bucket_arn     = "arn:aws:s3:::${local.athena_admin_bucket_name}"
    request_queue_arn    = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.feedback_requests_queue_name}"
    lambda_log_group_arn = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${local.feedback_lambda_log_group_name}"
    logs_queue_arn       = module.observability.logs_queue_arn
  })

  handler = "feedback_writer.handler"

  # 512, NOT notifications' 128. That writer's document is capped; this one's grows all day with
  # no cap. The whole object is read back and written out again in full, so peak resident is
  # several times its size. An OOM here SIGKILLs past observability's flush, so the one durable
  # operator signal is absent for exactly this failure — which is why it is sized, not watched.
  memory_mb = 512

  environment_variables = {
    # The one variable the writer requires. The rest of cpcommon.config's required union is
    # deliberately absent: this function imports `cas`, `clients` and `observability`, none of
    # which reads the config module (test_layer_import_safety.py).
    ADMIN_BUCKET = local.athena_admin_bucket_name
    # Optional BY CONSTRUCTION — observability reads it with os.environ.get.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # base grants the deploy role its SQS/Lambda/event-source-mapping/IAM/logs perms for this queue.
  depends_on = [module.base]
}
