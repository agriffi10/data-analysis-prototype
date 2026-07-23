locals {
  logs_queue_name = "${var.project_name}-${var.environment}-logs.fifo"
  sweep_name      = "${var.project_name}-${var.environment}-log-sweep"
  sweep_role_name = "${var.project_name}-${var.environment}-log-sweep"
  schedule_name   = "${var.project_name}-${var.environment}-log-sweep-schedule"

  # The prefix the sweep writes under, and the ONLY prefix its role can write to. Kept here so
  # the IAM grant and the Lambda's env can never drift apart.
  logs_prefix = "logs"
}
