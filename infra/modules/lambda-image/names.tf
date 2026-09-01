# ── The names everything here is built from ───────────────────────────────────
# The deploy role's grants are written against these EXACT names — a resource named differently
# is refused at create and reads as a missing permission. The grant's pattern ends `-lambda*`,
# so the suffix here is what the whole registry statement hangs on.
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  image_name  = "${local.name_prefix}-lambda"
}
