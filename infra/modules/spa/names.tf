# ── The names everything here is built from ───────────────────────────────────
# The deploy role's grants are written against these EXACT names — a resource named differently
# is refused at create and reads as a missing permission.
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  spa_name    = "${local.name_prefix}-spa"
}
