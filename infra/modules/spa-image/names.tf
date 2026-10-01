# ── The name the registry is built from ───────────────────────────────────────
# The deploy role's registry grant is written against this EXACT name, and deploy-spa-image.yml
# constructs the same string — a repository named differently is refused at create, and is one
# the image pipeline cannot find.
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  image_name  = "${local.name_prefix}-spa"
}
