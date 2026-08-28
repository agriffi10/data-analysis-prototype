# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# Every name here is load-bearing: the deploy policy scopes to these exact patterns, so the role
# name carries NO `-role` suffix and the rule is `-schedule`, not `-sweep`. Getting one wrong is
# denied at CreateRole rather than caught at plan. Reasoning: README.md.
locals {
  function_name  = "${var.project_name}-${var.environment}-user-directory-build"
  role_name      = "${var.project_name}-${var.environment}-user-directory-build"
  log_group_name = "/aws/lambda/${local.function_name}"
  log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.log_group_name}"

  # The reserved root prefix the document lives under. Kept in step with
  # build_directory.DIRECTORY_PREFIX — the builder writes here and the portal role reads here,
  # and the two grants are rendered from this one value.
  directory_prefix = "_directory"
}
