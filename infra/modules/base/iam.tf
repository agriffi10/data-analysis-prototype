# ── GitHub Actions OIDC Identity Provider ────────────────────────────────────
# Enables GitHub Actions workflows to assume an IAM role without storing long-lived credentials.
# The thumbprint is fetched dynamically from GitHub's OIDC discovery endpoint.

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = data.tls_certificate.github_actions.certificates[*].sha1_fingerprint
}

# ── GitHub Actions Deployment Role ───────────────────────────────────────────
# Trust allows:
#   - push to main (deploy + apply)
#   - pull_request events (tofu plan on PRs — read-only, no deploy permissions used)

resource "aws_iam_role" "github_actions_deploy" {
  name = "${var.project_name}-deploy-role"

  assume_role_policy = templatefile("${path.module}/policies/github-actions-trust.json.tftpl", {
    oidc_provider_arn = aws_iam_openid_connect_provider.github_actions.arn
    github_repo       = var.github_repo
  })
}

# Permission policy for the deploy role. Statement-level detail and rationale
# (e.g. the self-management privilege-escalation note) live in the template file.
resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "deploy-policy"
  role = aws_iam_role.github_actions_deploy.id

  policy = templatefile("${path.module}/policies/github-actions-deploy.json.tftpl", {
    project_name                = var.project_name
    static_bucket_arn           = var.static_bucket_arn
    user_space_bucket_arn       = var.user_space_bucket_arn
    portal_role_arn             = var.portal_role_arn
    lambda_artifacts_bucket_arn = var.lambda_artifacts_bucket_arn
    athena_admin_bucket_arn     = var.athena_admin_bucket_arn
    deploy_role_arn             = aws_iam_role.github_actions_deploy.arn
    oidc_provider_arn           = aws_iam_openid_connect_provider.github_actions.arn
    state_bucket                = var.state_bucket
    state_lock_table            = var.state_lock_table
    aws_region                  = var.aws_region
  })
}

# SPEC-050 shared-space control-plane grants live in a CUSTOMER-MANAGED policy
# attached to the deploy role — NOT a second inline policy. IAM's 10,240-char limit
# is the AGGREGATE of all inline policies on a role (sum, not per-policy), and the
# main deploy-policy alone is already ~8.5k; an inline second policy pushed the
# aggregate over (LimitExceeded). A managed policy has its own separate 6,144-char
# budget and doesn't count toward the inline aggregate, so this also gives SPEC-056's
# further shared-space grants room. All actions are resource-scopable by
# {project_name}-*-shared-space-* name patterns (no "*"-only statements).
resource "aws_iam_policy" "deploy_shared_spaces" {
  name        = "${var.project_name}-deploy-shared-spaces"
  description = "Deploy-role grants for the SPEC-050 shared-space control plane (SQS/Pipes/Step Functions/Lambda/roles/logs/S3), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-shared-spaces.json.tftpl", {
    project_name            = var.project_name
    aws_region              = var.aws_region
    shared_space_bucket_arn = var.shared_space_bucket_arn
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_shared_spaces" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_shared_spaces.arn
}

# SPEC-058 notifications write-pipeline grants — a SEPARATE customer-managed policy,
# same rationale as deploy_shared_spaces above: the inline deploy-policy aggregate is
# already near IAM's 10,240-char limit, so new resource-type grants go in their own
# managed policy (separate 6,144-char budget, off the inline aggregate). Covers the
# notifications module's resource types: the FIFO request queue + DLQ, the
# notifications-writer Lambda + its role (incl. scoped iam:PassRole), and the log
# group — all scoped by {project_name}-*-notifications-* name patterns. The SQS
# event-source-mapping actions are NOT resource-scopable (they authorize on a
# yet-unknown mapping UUID ARN), so they are isolated to their own "*" statement per
# the architecture.md "adding a new resource type" trap list.
resource "aws_iam_policy" "deploy_notifications" {
  name        = "${var.project_name}-deploy-notifications"
  description = "Deploy-role grants for the SPEC-058 notifications write pipeline (FIFO SQS queue + DLQ, writer Lambda + role + log group, SQS event-source mapping), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-notifications.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_notifications" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_notifications.arn
}

# SPEC-066 table-builder control-plane grants — a SEPARATE customer-managed policy,
# same rationale as deploy_shared_spaces / deploy_notifications above (off the role's
# inline-policy aggregate, separate 6,144-char budget). Covers the table-builder
# module's resource types: the FIFO request queue + DLQ, the EventBridge Pipe, the
# Standard Step Function (+ its execution role), the five single-task verb Lambdas +
# their per-verb roles (incl. scoped iam:PassRole), the polars Lambda layer, and the
# Lambda + Step-Function log groups — all scoped by {project_name}-*-table-builder-*
# name patterns. The table-builder module creates no S3 buckets (it only consumes the
# existing user/shared/admin bucket ARNs), so there is no S3-bucket-manage statement
# here. states:ValidateStateMachineDefinition is not resource-scopable, so it is
# isolated to its own "*" statement per the architecture.md "new resource type" traps.
# Granted FIRST (this PR) and applied before the table-builder module's resources land
# in a later PR (the deploy-perms-before-resources rule), so no self-grant race.
resource "aws_iam_policy" "deploy_table_builder" {
  name        = "${var.project_name}-deploy-table-builder"
  description = "Deploy-role grants for the SPEC-066 table-builder control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + roles, polars layer, log groups), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-table-builder.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_table_builder" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_table_builder.arn
}

# SPEC-088 table-share control-plane grants — a SEPARATE customer-managed policy,
# same rationale + shape as deploy_table_builder above (off the role's inline-policy
# aggregate, separate 6,144-char budget). Covers the table-share module's resource
# types: the FIFO request queue + DLQ, the EventBridge Pipe, the Standard Step
# Function (+ its role), the five single-task verb Lambdas + their ONE shared
# execution role (incl. scoped iam:PassRole), the table-share-common (tscommon)
# Lambda layer, and the Lambda + Step-Function log groups — all scoped by
# {project_name}-*-table-share-* name patterns. The table-share module creates no S3
# buckets (recipients reuse the existing user/shared-space buckets; the registry is
# read-only here), so there is no S3-bucket-manage statement.
# states:ValidateStateMachineDefinition is not resource-scopable, so it is isolated
# to its own "*" statement per the architecture.md "new resource type" traps.
# Granted FIRST (this PR) and applied before the table-share module's resources land
# in a later PR (the deploy-perms-before-resources rule), so no self-grant race.
resource "aws_iam_policy" "deploy_table_share" {
  name        = "${var.project_name}-deploy-table-share"
  description = "Deploy-role grants for the SPEC-088 table-share control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + shared execution role, tscommon layer, log groups), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-table-share.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_table_share" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_table_share.arn
}

# SPEC-107 control-plane-common layer grant — a SEPARATE customer-managed policy,
# same rationale + shape as deploy_table_builder / deploy_table_share above (off the
# role's inline-policy aggregate, separate 6,144-char budget). This grant is
# deliberately NARROW: publish/delete/get/list versions of the shared `cpcommon`
# Lambda LAYER only (no functions, roles, or other resources — those already have
# their per-arc function-manage grants). It is scoped to the layer ARN, not to any
# function, so every control-plane verb that later attaches cpcommon
# (table-builder-*, table-share-*, and the future data-quality / file-converter
# verbs) is covered by its OWN policy's function-manage grant + this one layer grant.
# Granted FIRST (this PR) and applied before the layer is published + attached in a
# later PR — every existing layer grant is name-scoped to -table-builder-* /
# -table-share-* and none matches control-plane-common, so CI cannot publish the
# layer until this applies (the deploy-perms-before-resources rule).
resource "aws_iam_policy" "deploy_control_plane_common" {
  name        = "${var.project_name}-deploy-control-plane-common"
  description = "Deploy-role grant to publish/attach the shared SPEC-107 control-plane-common (cpcommon) Lambda layer, kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-control-plane-common.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_control_plane_common" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_control_plane_common.arn
}

# Self-grant propagation guard. The main deploy-policy update above grants the deploy
# role iam:CreatePolicy / iam:AttachRolePolicy on itself, then this SAME apply uses
# those grants to create+attach the managed policy. IAM is eventually consistent, so
# pause after the inline-policy write so CreatePolicy doesn't race the grant (the same
# rationale as the other modules' time_sleep guards; module.base had none before
# because nothing here previously used its own freshly-granted permission).
resource "time_sleep" "wait_for_self_grant" {
  create_duration = "60s"

  depends_on = [aws_iam_role_policy.github_actions_deploy]
}
