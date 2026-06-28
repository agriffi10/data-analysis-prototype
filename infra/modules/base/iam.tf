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
