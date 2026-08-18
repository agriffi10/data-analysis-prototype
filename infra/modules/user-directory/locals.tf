# ── Constructed names + ARNs ──────────────────────────────────────
# Names derive from {project_name}-{environment} so the deploy policy (modules/base, the
# SPEC-146 PR1 grant) scopes to the same {project}-*-user-directory-build patterns, and so
# ARNs referenced inside IAM policy templates are KNOWN AT PLAN TIME — the architecture.md
# "unknown ARN in list" discipline. This module plans standalone.
#
# The role name carries NO `-role` suffix. The repo is inconsistent about this (log-sweep and
# the DLQ drain have none, pre-signup does), and PR1's grant is scoped to
# `role/${project_name}-*-user-directory-build` with no trailing wildcard — so a `-role`
# suffix here would be denied at CreateRole rather than caught at plan.
#
# The schedule rule is `{function_name}-schedule` for the same reason: PR1 scopes to
# `rule/${project_name}-*-user-directory-build-schedule`, and the DLQ drain's sibling rule is
# named `-sweep`, so the two names are not interchangeable.

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
