# ── The names everything here is built from ───────────────────────────────────
# The deploy role's grants are written against these EXACT names — a resource named differently
# is refused at create and reads as a missing permission.
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  spa_name    = "${local.name_prefix}-spa"

  # BUILT, not read from the log group: on a plan that creates the group its ARN is unknown, and
  # the plan-time IAM scan cannot read a policy that names it.
  log_group_name = "/ecs/${local.spa_name}"
  log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.log_group_name}"
}
