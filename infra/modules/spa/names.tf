# ── The names everything here is built from ───────────────────────────────────
# One place, because two of them cross a module boundary: the load balancer's ARN pattern in the
# bucket policy, and the deploy role's grants, which are written against these exact names — a
# resource named differently is refused at create and reads as a missing permission.
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  spa_name    = "${local.name_prefix}-spa"
}
