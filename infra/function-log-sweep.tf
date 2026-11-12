# The structured-logging sweep: lands the logs queue's events as one NDJSON object per service per
# day under s3://{admin}/logs/. The queue and its backlog alarm are module.observability; the
# reasoning for both is modules/observability/README.md.
#
# ORDERED: function timeout (300s) < queue visibility (360s) < schedule interval (600s). Breaking
# either inequality writes messages to S3 twice.

locals {
  log_sweep_function_name = "${var.project_name}-${var.environment}-log-sweep"

  # The prefix the sweep writes under, and the ONLY prefix its role can write to. The handler's
  # LOGS_PREFIX names the same one.
  log_sweep_prefix = "logs"
}

module "observability_sweep" {
  source = "./modules/scheduled-function"

  function_name = local.log_sweep_function_name
  role_name     = "${var.project_name}-${var.environment}-log-sweep"
  # Its own trust document, which carries no Sid; the module's default carries one.
  trust_policy = templatefile("${path.root}/functions/log-sweep/sweep-trust.json.tftpl", {})

  role_policies = {
    # The sweep writes logs and reads BACK ONLY WHAT IT WROTE. Scoped to logs/* — NOT the bucket
    # root, which also holds fallback-results/, shared-spaces/ and table-share/. Widening it lets
    # the sweep overwrite a user's query results with log lines.
    "sweep" = templatefile("${path.root}/functions/log-sweep/sweep.json.tftpl", {
      logs_queue_arn   = module.observability.logs_queue_arn
      admin_bucket_arn = "arn:aws:s3:::${local.athena_admin_bucket_name}"
      logs_prefix      = local.log_sweep_prefix
      log_group_arn    = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.log_sweep_function_name}"
    })
    # The sweep is also a PRODUCER — it instruments itself, which proves the whole path without
    # touching a control plane. The PORTAL role is granted NOTHING on this queue, here or anywhere.
    "logs-producer" = templatefile("${path.root}/functions/log-sweep/logs-producer.json.tftpl", {
      logs_queue_arn = module.observability.logs_queue_arn
    })
  }

  handler         = "log_sweep.handler"
  timeout_seconds = 300
  # 512, not 256 — the sweep reads the day's whole object back before appending.
  memory_mb = 512

  environment_variables = {
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    ENV_NAME       = var.environment

    # ADMIN_BUCKET is genuinely used; the rest are the shared code's required union. Do not remove
    # one because the sweep does not read it.
    ADMIN_BUCKET        = local.athena_admin_bucket_name
    USER_SPACE_BUCKET   = local.user_space_bucket_name
    SHARED_SPACE_BUCKET = local.shared_space_bucket_name
    ATHENA_WORKGROUP    = local.athena_workgroup_name
  }

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # 10 minutes (user decision, 2026-07-23), matching the DLQ drain. Must stay ABOVE the function
  # timeout.
  rule_name               = "${var.project_name}-${var.environment}-log-sweep-schedule"
  rule_description        = "Fires the structured-logging sweep every 10 minutes."
  schedule_expression     = "rate(10 minutes)"
  permission_statement_id = "AllowExecutionFromEventBridge"

  # base writes the deploy role's observability grants before anything here uses them.
  depends_on = [module.base]
}
