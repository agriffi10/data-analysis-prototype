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

# ⚠ EVERY GRANT BELOW IS A CUSTOMER-MANAGED POLICY, NOT A SECOND INLINE ONE. IAM's
# 10,240-character limit is the AGGREGATE of a role's inline policies, and the main deploy
# policy alone renders to 9,289. A managed policy has its own separate 6,144-char budget.
#
# Each one is scoped by {project_name}-*-<plane>-* name patterns, and every `Resource: "*"`
# statement holds only actions IAM defines no resource type for. GRANTS LAND IN THEIR OWN PR,
# BEFORE THE RESOURCES THAT NEED THEM. README.md.
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

# Notifications. lambda:*EventSourceMapping is not RESOURCE-scopable but Create/Get/Update/
# Delete ARE condition-scopable on lambda:FunctionArn. ListEventSourceMappings is the one that
# genuinely cannot be narrowed — AWS defines no resource types and no condition keys — so it
# keeps a bare "*"; conditioning it would deny the call outright. README.md.
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

# Feedback. The same shape as the notifications block above, and for the same reason: a FIFO
# queue with its own DLQ, one writer Lambda, its role and its log group. No S3-bucket-manage
# statement — the writer appends under a prefix of the admin bucket the analytics module already
# owns, so nothing here creates a bucket.
resource "aws_iam_policy" "deploy_feedback" {
  name        = "${var.project_name}-deploy-feedback"
  description = "Deploy-role grants for the feedback write pipeline (FIFO SQS queue + DLQ, writer Lambda + role + log group, SQS event-source mapping), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-feedback.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_feedback" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_feedback.arn
}

# Table-builder. No S3-bucket-manage statement: the module creates no bucket.
# states:ValidateStateMachineDefinition is not resource-scopable, so it sits alone.
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

# Table-share. Same shape as table-builder's, and no S3-bucket-manage statement.
resource "aws_iam_policy" "deploy_table_share" {
  name        = "${var.project_name}-deploy-table-share"
  description = "Deploy-role grants for the table-share control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + shared execution role, tscommon layer, log groups), kept off the role's inline-policy aggregate limit."

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

# The shared cpcommon layer, and DELIBERATELY NOTHING ELSE — scoped to the LAYER ARN, not to
# any function, so every verb that attaches it is covered by its own policy's function-manage
# grant plus this one. Every other layer grant is name-scoped to a plane and matches nothing
# here, so CI cannot publish the layer until this applies.
resource "aws_iam_policy" "deploy_control_plane_common" {
  name        = "${var.project_name}-deploy-control-plane-common"
  description = "Deploy-role grant to publish/attach the shared control-plane-common (cpcommon) Lambda layer, kept off the role's inline-policy aggregate limit."

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

# Data-quality. NO workgroup grant: these verbs run in the SHARED portal Athena workgroup,
# because a dedicated one breaks Lake Formation, so there is no plane-specific one to grant on.
resource "aws_iam_policy" "deploy_data_quality" {
  name        = "${var.project_name}-deploy-data-quality"
  description = "Deploy-role grants for the data-quality control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, nine verb Lambdas + shared execution role, dqcommon + polars layers, log groups), kept off the role's inline-policy aggregate limit."

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

# The DLQ drain: ONE Lambda, ONE role, ONE log group.
#
# NO SQS RESOURCE GRANTS, and that is the point rather than an omission — the drain CREATES NO
# QUEUE. It reads the four DLQs the plane modules already own, whose ARNs reach it through
# Terraform state, so the deploy role makes no SQS API call for them. The drain's RUNTIME
# access is a grant on its EXECUTION role. README.md.
resource "aws_iam_policy" "deploy_control_plane_dlq_drain" {
  name        = "${var.project_name}-deploy-control-plane-dlq-drain"
  description = "Deploy-role grants for the control-plane DLQ drain (one Lambda + execution role + log group + the EventBridge sweep schedule), kept off the role's inline-policy aggregate limit."

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

# Observability: the structured-logging pipe.
#
# NO lambda:*EventSourceMapping STATEMENT, deliberately — the sweep is pulled by a SCHEDULE,
# not a managed poll loop, and idle long-polling was the bulk of this account's SQS request
# volume. The absence is what keeps a future "just add an event-source mapping" from applying
# cleanly without a deliberate decision.
#
# The SQS statement names BOTH `-logs` and `-logs.fifo`: a FIFO queue's name MUST end in
# `.fifo`, so that rename was a DESTROY-AND-CREATE and one apply needed both. The old ARN stays
# — re-adding it is exactly the grant a rollback would need. README.md.
resource "aws_iam_policy" "deploy_observability" {
  name        = "${var.project_name}-deploy-observability"
  description = "Deploy-role grants for the structured-logging foundation (one standard SQS logs queue + one scheduled sweep Lambda, its execution role, log group and EventBridge rule), kept off the role's inline-policy aggregate limit."

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

# The user-directory daily builder. Same shape as observability's, and for the same reason: a
# singleton pulled by a schedule, so no event-source-mapping statement.
#
# NO S3 STATEMENT, deliberately — the DEPLOY role never touches the object the builder writes,
# and what it does need on that bucket it already holds via S3UserSpaceBucketManage. A second
# statement would be a duplicate, not a tightening.
resource "aws_iam_policy" "deploy_user_directory" {
  name        = "${var.project_name}-deploy-user-directory"
  description = "Deploy-role grants for the username-directory builder (one scheduled Lambda, its execution role, log group and EventBridge rule), kept off the role's inline-policy aggregate limit."

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

# File-send. No S3-bucket-manage statement: a send copies between existing buckets.
#
# NO events: STATEMENT at this stage, deliberately — this machine validates and stops, so it
# has no TimeoutSeconds and no TIMED_OUT rule to manage. The transfer brings the timeout, the
# rule and the grant, which must extend this policy FIRST. README.md.
resource "aws_iam_policy" "deploy_file_send" {
  name        = "${var.project_name}-deploy-file-send"
  description = "Deploy-role grants for the file-send control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, fscommon layer, log groups), kept off the role's inline-policy aggregate limit."

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

# File-operations.
#
# IT CARRIES THE events: STATEMENT FROM ITS FIRST VERSION, which the neighbouring planes gained
# later — not copied habit: this machine has a top-level TimeoutSeconds from day one, because
# the per-space lock's WAITING loop is in it before any data work is. The grant has to be here
# or the first apply fails on the rule rather than on the plane's actual purpose. README.md.
resource "aws_iam_policy" "deploy_file_ops" {
  name        = "${var.project_name}-deploy-file-ops"
  description = "Deploy-role grants for the file-operations control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, focommon layer, log groups, TIMED_OUT rule), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-file-ops.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_file_ops" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_file_ops.arn
}

# Archive.
#
# ⚠ THE FIRST PLANE POLICY TO CARRY AN S3-BUCKET STATEMENT, and it is scoped by EXACT NAME
# rather than the name pattern: "{project}-prod-archive" has no trailing segment, so it does
# not match "{project}-*-archive-*" AT ALL. A pattern-scoped grant would render, apply, and
# then fail the bucket create with an implicit deny.
#
# NO events: STATEMENT at this stage — see file-send's note. README.md.
resource "aws_iam_policy" "deploy_archive" {
  name        = "${var.project_name}-deploy-archive"
  description = "Deploy-role grants for the archive control plane (the archive bucket, FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, arcommon layer, log groups), kept off the role's inline-policy aggregate limit."

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

# ── Propagation guard for the archive grants ───────────────────────────────
# ⚠ THE APPLY THAT FIRST ADDED THESE GRANTS WENT RED HERE, and the mechanism is invisible in a
# plan: the resources are created in the SAME apply that attaches the policy authorizing them,
# and depends_on is not enough because IAM is eventually consistent.
#
# Every other plane dodged this by SPLITTING the work across two PRs — WHICH HOLDS ONLY FOR AS
# LONG AS SOMEBODY REMEMBERS TO SPLIT. This guard is structural instead.
#
# 30s is a floor on eventual consistency, not a guarantee. A RED FIRST APPLY OF A NEW PLANE IS
# EXPECTED RATHER THAN A DEFECT; a re-run is the remedy. README.md.
resource "time_sleep" "wait_for_archive_grant" {
  depends_on      = [aws_iam_role_policy_attachment.deploy_archive]
  create_duration = "30s"
}

# Self-grant guard: the main deploy policy grants this role iam:CreatePolicy /
# iam:AttachRolePolicy ON ITSELF, and the SAME apply then uses those grants.
resource "time_sleep" "wait_for_self_grant" {
  create_duration = "60s"

  depends_on = [aws_iam_role_policy.github_actions_deploy]
}

# ── The archive-audit trail and the verification role ──────────
# Two resource kinds new to the deploy role: a CloudTrail trail, and a role nothing assumes but
# a human.
#
# NO iam:PassRole HERE, unlike every plane's — a service assumes those, and nothing must be
# able to hand this one to a service.
#
# ⚠ THE REASONING LIVES HERE, NOT IN THE JSON. The first version carried "//" keys inside the
# policy document and the apply REJECTED IT: an IAM policy document must be PRINTABLE ASCII,
# and the comments contained em dashes. That is a validation error at CreatePolicy, invisible
# to `tofu validate` and to the plan. README.md.
resource "aws_iam_policy" "deploy_verification" {
  name        = "${var.project_name}-deploy-verification"
  description = "Deploy-role grants for the verification access: the archive-audit trail bucket, the CloudTrail trail over the archive vault's object-level events, and the read-only verification role."

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

# ── The container platform: network, compute, and the front door ──────────
# TWO policies, not one: ONE DOCUMENT WOULD NOT HAVE FITTED the 6,144-char per-policy budget,
# and the larger half is still the one under pressure. The sizes are not repeated here because a
# number in a comment rots — `lambdas/test_deploy_platform_policies.py` measures every managed
# policy against the ceiling on every run, and names the measurement when it fails. `deploy_platform` keeps its name
# because the scanner accept list names it.
#
# ⚠ EVERY `Resource: "*"` STATEMENT HOLDS ONLY ACTIONS IAM DEFINES NO RESOURCE TYPE FOR, each
# checked with simulate-custom-policy: 37 actions, each reading implicitDeny under a scoped ARN
# AND allowed under "*". THE implicitDeny ALONE PROVES NOTHING — it reads identically to a
# wrong ARN — so the `allowed` control is what makes the pair evidence.
# test_deploy_platform_policies.py PINS THAT MEASUREMENT rather than re-deriving it over the
# network, which would fail on a runner with no egress and pass by finding nothing.
#
# THE EC2 MUTATORS ARE SCOPED BY RESOURCE TYPE, NOT BY NAME — an EC2 ARN carries a generated
# id. The tagging statement names the SAME nine types and carries NO condition:
# ec2:CreateAction does not exist on DeleteTags, and on CreateTags it would forbid tagging
# anything that already exists — which is exactly what aws_default_security_group is.
#
# THE PUSH GRANTS ARE HERE because the image pipeline runs as this role, and a registry token
# with no layer-upload actions beside it would authorize nothing at all.
#
# NO iam:AttachRolePolicy EITHER, AND THAT ABSENCE IS LOAD-BEARING. Every role carries INLINE
# policies. The one that invites a managed attachment is the ECS task execution role, and that
# grant is deliberately narrower and written out, so the wildcard it would otherwise hide stays
# VISIBLE TO THE SCANNER. Reaching for the managed policy fails at the attach, which is where
# that decision should be re-made. README.md.
resource "aws_iam_policy" "deploy_platform" {
  name        = "${var.project_name}-deploy-platform"
  description = "Deploy-role grants for the container platform's network and compute (VPC, subnets, route tables, gateway, security groups, VPC endpoints, ALB, target groups, listeners, ECS cluster/service/task definitions, ECR), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-platform.json.tftpl", {
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_platform" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_platform.arn
}

# The other half: the front door, every log group the platform creates (including the flow
# log's and the ECS task's, without which the task cannot start) and every role it passes.
#
# iam:PassRole is split into THREE statements, because a statement carries ONE condition block
# and the four roles go to three services — a single iam:PassedToService listing all three
# WOULD LET THE FLOW-LOGS ROLE BE HANDED TO ECS. The fourth role is the flow-logs delivery
# role: flow logs to CloudWatch are delivered AS a role, so one exists even though no resource
# in the platform's own list names it, AND A GRANT WRITTEN FROM THAT LIST ALONE IS SHORT BY
# ONE. README.md.
resource "aws_iam_policy" "deploy_platform_frontdoor" {
  name        = "${var.project_name}-deploy-platform-frontdoor"
  description = "Deploy-role grants for the API's front door (HTTP API, regional custom domain, ACM certificates, Route 53 records, access-log delivery, the placeholder API function) plus the log groups and the four IAM roles the whole platform needs, kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-platform-frontdoor.json.tftpl", {
    project_name    = var.project_name
    aws_region      = var.aws_region
    route53_zone_id = var.route53_zone_id
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_platform_frontdoor" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_platform_frontdoor.arn
}

# A SECOND sleep, not a wider dependency on the first: wait_for_self_grant has long finished
# by the time these are written and gates nothing. Every module using a platform grant depends
# on module.base as a whole, so placing the pause AFTER the attachments is what puts it between
# the grant and its first use.
#
# `triggers` is the half that makes it durable. MEASURED: a grant written at 14:56:08.95 and
# the call it authorises refused at 14:56:10.67 — 1.7 seconds, on an apply where a sleep
# created months earlier had nothing left to do. Keyed to the policy BODIES, it returns exactly
# when a grant is new. README.md.
resource "time_sleep" "wait_for_platform_grant" {
  create_duration = "60s"

  triggers = {
    platform  = aws_iam_policy.deploy_platform.policy
    frontdoor = aws_iam_policy.deploy_platform_frontdoor.policy
  }

  depends_on = [
    aws_iam_role_policy_attachment.deploy_platform,
    aws_iam_role_policy_attachment.deploy_platform_frontdoor,
  ]
}

