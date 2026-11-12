locals {
  logs_queue_name = "${var.project_name}-${var.environment}-logs.fifo"

  # The deploy grant names this pattern, `${project_name}-*-logs-backlog`; rename both together.
  backlog_alarm_name = "${var.project_name}-${var.environment}-logs-backlog"
}
