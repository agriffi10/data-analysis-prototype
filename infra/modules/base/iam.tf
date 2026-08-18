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

# Shared-space control-plane grants live in a CUSTOMER-MANAGED policy
# attached to the deploy role — NOT a second inline policy. IAM's 10,240-char limit
# is the AGGREGATE of all inline policies on a role (sum, not per-policy), and the
# main deploy-policy alone is already ~8.5k; an inline second policy pushed the
# aggregate over (LimitExceeded). A managed policy has its own separate 6,144-char
# budget and doesn't count toward the inline aggregate, so this also gives the membership slots'
# further shared-space grants room. All actions are resource-scopable by
# {project_name}-*-shared-space-* name patterns (no "*"-only statements).
resource "aws_iam_policy" "deploy_shared_spaces" {
  name        = "${var.project_name}-deploy-shared-spaces"
  description = "Deploy-role grants for the shared-space control plane (SQS/Pipes/Step Functions/Lambda/roles/logs/S3), kept off the role's inline-policy aggregate limit."

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

# Notifications write-pipeline grants — a SEPARATE customer-managed policy,
# same rationale as deploy_shared_spaces above: the inline deploy-policy aggregate is
# already near IAM's 10,240-char limit, so new resource-type grants go in their own
# managed policy (separate 6,144-char budget, off the inline aggregate). Covers the
# notifications module's resource types: the FIFO request queue + DLQ, the
# notifications-writer Lambda + its role (incl. scoped iam:PassRole), and the log
# group — all scoped by {project_name}-*-notifications-* name patterns.
#
# The event-source-mapping actions are still not RESOURCE-scopable (they authorize on
# a yet-unknown mapping UUID ARN), but Create/Get/Update/Delete are CONDITION-scopable
# on `lambda:FunctionArn`, so they are constrained to the writer function rather than
# to every Lambda in the account. `ListEventSourceMappings` is the one that genuinely
# cannot be narrowed — AWS defines no resource types and no condition keys for it, so
# it keeps a bare "*" in its own statement. Conditioning it would deny the call
# outright: the "unknown-ARN-in-list" trap from architecture.md.
resource "aws_iam_policy" "deploy_notifications" {
  name        = "${var.project_name}-deploy-notifications"
  description = "Deploy-role grants for the notifications write pipeline (FIFO SQS queue + DLQ, writer Lambda + role + log group, SQS event-source mapping), kept off the role's inline-policy aggregate limit."

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

# Table-builder control-plane grants — a SEPARATE customer-managed policy,
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
  description = "Deploy-role grants for the table-builder control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + roles, polars layer, log groups), kept off the role's inline-policy aggregate limit."

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

# SPEC-108 data-quality control-plane grants — a SEPARATE customer-managed policy, same
# rationale + shape as deploy_table_builder / deploy_table_share above (off the role's
# inline-policy aggregate, separate 6,144-char budget). Covers the data-quality module's
# resource types: the FIFO request queue + DLQ, the EventBridge Pipe, the Standard Step
# Function (+ its role), the nine single-task verb Lambdas + their ONE shared execution
# role (incl. scoped iam:PassRole), the dqcommon + data-quality-polars Lambda layers, and
# the Lambda + Step-Function log groups — all scoped by {project_name}-*-data-quality-*
# name patterns. The module creates no S3 buckets (reports write to the existing
# user/shared-space buckets), so there is no S3-bucket-manage statement.
# states:ValidateStateMachineDefinition is not resource-scopable, so it is isolated to
# its own "*" statement per the architecture.md "new resource type" traps.
# NOTE: the data-quality verbs run in the SHARED portal Athena workgroup (SPEC-111 fix —
# a dedicated workgroup breaks Lake Formation), so there is no data-quality-specific
# workgroup to grant on. The cpcommon layer that every DQ verb attaches is covered by
# deploy_control_plane_common.
# Granted FIRST (this PR) and applied before the data-quality module's resources land in a
# later PR (the deploy-perms-before-resources rule), so no self-grant race.
resource "aws_iam_policy" "deploy_data_quality" {
  name        = "${var.project_name}-deploy-data-quality"
  description = "Deploy-role grants for the SPEC-108 data-quality control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, nine verb Lambdas + shared execution role, dqcommon + polars layers, log groups), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-data-quality.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_data_quality" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_data_quality.arn
}

# SPEC-126 control-plane DLQ drain grants — a SEPARATE customer-managed policy, same
# rationale + shape as the per-arc policies above (off the role's inline-policy aggregate,
# separate 6,144-char budget). The drain module is deliberately small: ONE Lambda, ONE
# execution role, ONE log group, and four SQS event-source mappings.
#
# NO SQS RESOURCE GRANTS HERE, and that is the point rather than an omission. The drain
# creates no queue — it attaches to the four request DLQs the arc modules already own, and
# their ARNs reach the module through Terraform state, so the deploy role makes no SQS API
# call for them. The drain's own RUNTIME access to those queues is a grant on its EXECUTION
# role (in the drain module), not on the deploy role.
#
# lambda:*EventSourceMapping is not resource-scopable (the mapping has no ARN to name at
# create time), so it is isolated to its own "*" statement — the same trap the notifications
# module hit, per architecture.md → "Deploy-role IAM — adding a new resource type".
#
# The drain attaches the shared cpcommon layer, which deploy_control_plane_common already
# covers; nothing here needs a layer grant.
#
# Granted FIRST (this PR) and applied before the drain module's resources land in the next
# PR (the deploy-perms-before-resources rule), so there is no self-grant race.
resource "aws_iam_policy" "deploy_control_plane_dlq_drain" {
  name        = "${var.project_name}-deploy-control-plane-dlq-drain"
  description = "Deploy-role grants for the SPEC-126 control-plane DLQ drain (one Lambda + execution role + log group + the EventBridge sweep schedule), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-control-plane-dlq-drain.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_control_plane_dlq_drain" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_control_plane_dlq_drain.arn
}

# SPEC-127 observability: the structured-logging pipe — one standard SQS logs queue, one
# scheduled sweep Lambda (+ its execution role and log group), and the EventBridge rule that
# fires it.
#
# No lambda:*EventSourceMapping statement, deliberately: the sweep is pulled by a schedule, not
# by a managed poll loop, so there is no mapping to create. That is the whole point of the
# design (#270/#271 — idle long-polling was the bulk of this account's SQS request volume), and
# the absence of the grant is what keeps a future "just add an event-source mapping" from
# applying cleanly without a deliberate decision.
#
# S3 is NOT granted here: the sweep writes to the Athena admin bucket under logs/, which
# S3AthenaAdminBucketManage in the main deploy policy already covers with s3:* on the bucket and
# its contents. A second grant would be a duplicate, not a tightening.
#
# The SQS statement names BOTH `-logs` and `-logs.fifo` deliberately. SPEC-129 converts the logs
# queue to FIFO, and a FIFO queue's name MUST end in `.fifo` — which makes the rename a
# destroy-and-create, not an update. So the one apply that performs it needs DeleteQueue on the
# old name and CreateQueue on the new one at the same time. The old ARN stays in the list
# afterwards rather than being pruned in a follow-up: removing it would only reclaim permission
# to manage a queue that no longer exists, and re-adding it is exactly the grant a future
# rollback would need.
#
# The sweep attaches the shared cpcommon layer, which deploy_control_plane_common already
# covers; nothing here needs a layer grant.
#
# Granted FIRST (this PR) and applied before the observability module's resources land in the
# next PR (the deploy-perms-before-resources rule), so there is no self-grant race.
resource "aws_iam_policy" "deploy_observability" {
  name        = "${var.project_name}-deploy-observability"
  description = "Deploy-role grants for the SPEC-127 structured-logging foundation (one standard SQS logs queue + one scheduled sweep Lambda, its execution role, log group and EventBridge rule), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-observability.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_observability" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_observability.arn
}

# SPEC-146 user directory: the daily builder — one scheduled Lambda (+ its execution role and
# log group) and the EventBridge rule that fires it. Same shape as the observability grant
# above, and for the same reason: a singleton function pulled by a schedule, not by a managed
# poll loop, so there is no lambda:*EventSourceMapping statement here either.
#
# NO S3 STATEMENT, deliberately. The builder lists the user-space bucket and writes one object
# under _directory/, but the DEPLOY role never touches that object — it only creates the
# function and its role. What the deploy role does need on that bucket (to create it, and to
# manage the bucket policy this spec extends) it already holds via S3UserSpaceBucketManage in
# github-actions-deploy.json.tftpl, which modules/data/s3.tf explicitly relies on. Adding a
# second S3 statement here would be a duplicate, not a tightening.
#
# The builder attaches the shared cpcommon layer, which deploy_control_plane_common already
# covers; nothing here needs a layer grant.
#
# Granted FIRST (this PR) and applied before the user-directory module's resources land in the
# next PR (the deploy-perms-before-resources rule), so there is no self-grant race.
resource "aws_iam_policy" "deploy_user_directory" {
  name        = "${var.project_name}-deploy-user-directory"
  description = "Deploy-role grants for the SPEC-146 username-directory builder (one scheduled Lambda, its execution role, log group and EventBridge rule), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-user-directory.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_user_directory" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_user_directory.arn
}

# SPEC-164 file-send control-plane grants — a SEPARATE customer-managed policy, same
# rationale + shape as deploy_table_share above (off the role's inline-policy aggregate,
# separate 6,144-char budget). Covers the file-send module's resource types: the FIFO
# request queue + DLQ, the EventBridge Pipe, the Standard Step Function (+ its role), the
# verb Lambdas + their ONE shared execution role (incl. scoped iam:PassRole), the
# file-send-common (fscommon) Lambda layer, and the Lambda + Step-Function log groups —
# all scoped by {project_name}-*-file-send-* name patterns. The module creates no S3
# buckets (a send copies between the existing user/shared-space buckets), so there is no
# S3-bucket-manage statement, and the cpcommon layer every verb also attaches is covered
# by deploy_control_plane_common.
# states:ValidateStateMachineDefinition is not resource-scopable, so it is isolated to its
# own "*" statement per the architecture.md "new resource type" traps.
#
# NO events: STATEMENT, deliberately. Table-share's policy carries one for its SPEC-161
# TIMED_OUT rule; this machine validates and stops, so it has no TimeoutSeconds and no rule
# to manage. The long Distributed-Map copy — and therefore the timeout, the rule and the
# events: grant it needs — lands with SPEC-166, which must extend this policy FIRST and
# apply it before those resources land.
#
# Granted FIRST (this PR) and applied before the file-send module's resources land in the
# next PR (the deploy-perms-before-resources rule), so there is no self-grant race.
resource "aws_iam_policy" "deploy_file_send" {
  name        = "${var.project_name}-deploy-file-send"
  description = "Deploy-role grants for the SPEC-164 file-send control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, fscommon layer, log groups), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-file-send.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_file_send" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_file_send.arn
}

# SPEC-168 archive control-plane grants — a SEPARATE customer-managed policy, same
# rationale + shape as deploy_file_send above (off the role's inline-policy aggregate,
# separate 6,144-char budget). Covers the archive module's resource types: the FIFO
# request queue + DLQ, the EventBridge Pipe, the Standard Step Function (+ its role), the
# verb Lambdas + their ONE shared execution role (incl. scoped iam:PassRole), the
# archive-common (arcommon) Lambda layer, and the Lambda + Step-Function log groups — all
# scoped by {project_name}-*-archive-* name patterns.
#
# IT IS THE FIRST PLANE POLICY TO CARRY AN S3-BUCKET STATEMENT, because this is the first
# plane that CREATES a bucket. That statement is scoped by EXACT NAME rather than by the
# name pattern, and the reason is worth stating because it looks like an inconsistency:
# "{project}-prod-archive" has no trailing segment, so it does not match
# "{project}-*-archive-*" at all. A pattern-scoped grant would render, apply and then fail
# the bucket create with an implicit deny.
#
# NO events: STATEMENT, deliberately, and the same note file-send's policy carried at this
# stage applies: this machine validates and stops, so it has no TimeoutSeconds and no
# TIMED_OUT rule to manage. SPEC-169 adds the transfer — and therefore the timeout, the
# rule and the events: grant it needs — and must extend this policy FIRST and apply it
# before those resources land.
#
# Granted FIRST and applied before the archive module's resources land (the
# deploy-perms-before-resources rule), so there is no self-grant race.
resource "aws_iam_policy" "deploy_archive" {
  name        = "${var.project_name}-deploy-archive"
  description = "Deploy-role grants for the SPEC-168 archive control plane (the archive bucket, FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, arcommon layer, log groups), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-archive.json.tftpl", {
    project_name        = var.project_name
    aws_region          = var.aws_region
    archive_bucket_name = var.archive_bucket_name
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_archive" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_archive.arn
}

# ── Propagation guard for the archive grants (SPEC-168 follow-up) ─────────────
# THE APPLY THAT MERGED SPEC-168 WENT RED HERE, and the mechanism is worth recording
# because it is invisible in a plan. The archive module's resources are created in the
# SAME apply that attaches the policy authorizing them. `module.archive` carries
# `depends_on = [module.base]`, so the attachment genuinely happens first — and it is
# still not enough, because IAM is eventually consistent: CreateBucket, CreateRole,
# CreateQueue and CreateLogGroup all came back AccessDenied seconds after the attach,
# and the identical apply succeeded on a re-run minutes later with no change at all.
#
# Every other plane dodged this by SPLITTING the work across two PRs — grants in one,
# resources in the next — which is the deploy-perms-before-resources rule and is what
# their module comments mean by "no time_sleep guard is required here". That rule holds
# only for as long as somebody remembers to split, and SPEC-168 shipped as one PR.
#
# So the guard is structural instead. `module.archive` already depends on `module.base`
# as a whole, so it waits for this too, with no wiring in the child module. It matters
# again the moment SPEC-169 extends the archive policy (events:, and S3 on the space and
# archive buckets) in the same PR as the EventBridge rule and verbs that use them —
# which is the shape that just failed.
#
# 30s, matching wait_for_self_grant above. It is a floor on eventual consistency, not a
# guarantee; a re-run remains the remedy if AWS is slower than usual, and a red FIRST
# apply of a new plane is expected rather than a defect.
resource "time_sleep" "wait_for_archive_grant" {
  depends_on      = [aws_iam_role_policy_attachment.deploy_archive]
  create_duration = "30s"
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

# ── SPEC-186 FR-004: the archive-audit trail + the verification role ──────────
# Its own managed policy on the archive's precedent, kept off the role's inline-policy
# aggregate limit. Two resource kinds are new to the deploy role — a CloudTrail trail and a
# role nothing assumes but a human — and the grants below are the whole of what either needs.
#
# NO iam:PassRole in the role statement, unlike every other plane's: a service assumes those,
# and nothing must be able to hand this one to a service.
#
# `TrailGlobalReads` is the one `Resource: "*"` here. `cloudtrail:DescribeTrails` and
# `ListTrails` are account-wide APIs with no ARN to scope to — the same shape as the two
# permanent rows on the plan-scan accept list — and both are read-only.
#
# THE REASONING LIVES HERE, NOT IN THE JSON. The first version carried `"//"` keys inside the
# policy document, which no other policy in this repo does, and the apply rejected it:
# **an IAM policy document must be printable ASCII**, and the comments contained em dashes.
# The failure is worth keeping in mind for any future template — it is a validation error at
# CreatePolicy, not something `tofu validate` or the plan can see.
#
# Granted FIRST and guarded by the same 30s propagation floor the archive grants needed
# (the apply went red on exactly this and succeeded unchanged on a re-run): IAM is
# eventually consistent, and this PR creates the bucket, trail and role in the SAME apply that
# authorizes them. A red FIRST apply of a new plane is expected rather than a defect.
resource "aws_iam_policy" "deploy_verification" {
  name        = "${var.project_name}-deploy-verification"
  description = "Deploy-role grants for the SPEC-186 FR-004 verification access: the archive-audit trail bucket, the CloudTrail trail over the archive vault's object-level events, and the read-only verification role."

  policy = templatefile("${path.module}/policies/github-actions-deploy-verification.json.tftpl", {
    project_name      = var.project_name
    aws_region        = var.aws_region
    trail_bucket_name = var.verification_trail_bucket_name
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_verification" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_verification.arn
}

resource "time_sleep" "wait_for_verification_grant" {
  depends_on      = [aws_iam_role_policy_attachment.deploy_verification]
  create_duration = "30s"
}
