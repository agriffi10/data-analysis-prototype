# The control-plane DLQ drain: the one function that turns a dead-lettered request into a sentence
# in the actor's inbox. Before it, a request the pipeline refused simply vanished: no verb ran, so
# no failure notification fired. ONE function over every plane's DLQ, on one 10-minute schedule;
# the per-domain difference is a table in the handler. Reasoning:
# functions/control-plane-dlq-drain/README.md.
#
# The DLQ ARNs are CONSTRUCTED STRINGS (local.drained_dlq_names in main.tf), not the planes'
# outputs, so the drain's policy plans cleanly and no module-to-module edge is created.

locals {
  control_plane_dlq_drain_function_name = "${var.project_name}-${var.environment}-control-plane-dlq-drain"
  drained_dlq_arns                      = [for name in local.drained_dlq_names : "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${name}"]
}

module "control_plane_dlq_drain" {
  source = "./modules/scheduled-function"

  function_name = local.control_plane_dlq_drain_function_name
  role_name     = "${var.project_name}-${var.environment}-control-plane-dlq-drain"

  # Receive and delete on each drained DLQ, one send, logs. NO access to any REQUEST queue — a
  # drain that could enqueue into a control plane would be a way to inject work.
  role_policies = {
    "drain" = templatefile("${path.root}/functions/control-plane-dlq-drain/drain.json.tftpl", {
      dlq_arns                = local.drained_dlq_arns
      notifications_queue_arn = local.notifications_queue_arn
      logs_queue_arn          = module.observability.logs_queue_arn
      lambda_log_group_arn    = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.control_plane_dlq_drain_function_name}"
    })
  }

  handler = "dlq_drain.handler"
  # The handler's per-queue round cap already bounds a sweep well under this.
  timeout_seconds = 60
  memory_mb       = 256

  environment_variables = {
    # The notifications URL and DLQ_ARNS are genuinely used; the buckets and workgroup are the
    # shared code's union. Do not prune one.
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    DLQ_ARNS                = jsonencode(local.drained_dlq_arns)
    USER_SPACE_BUCKET       = local.user_space_bucket_name
    SHARED_SPACE_BUCKET     = local.shared_space_bucket_name
    ADMIN_BUCKET            = local.athena_admin_bucket_name
    ATHENA_WORKGROUP        = local.athena_workgroup_name
    # Deliberately NOT mirrored by a config._require: observability reads it with
    # os.environ.get, so losing it logs to stdout rather than crashing at cold start.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # ONE rule every 10 minutes; the handler polls every DLQ in DLQ_ARNS itself. NOTHING re-drives a
  # message: the sweep deletes every message it reads, notified or not. THE LOG GROUP IS THE ONLY
  # COPY OF A DEAD-LETTERED BODY, so its retention bounds the forensic window.
  rule_name               = "${local.control_plane_dlq_drain_function_name}-sweep"
  rule_description        = "Sweep the control-plane request DLQs into user notifications every 10 minutes."
  schedule_expression     = "rate(10 minutes)"
  permission_statement_id = "AllowEventBridgeSweep"

  # base grants the deploy role its drain perms.
  depends_on = [module.base]
}
