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
    account_id                  = var.account_id
    project_name                = var.project_name
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
# policy alone spends most of it. A managed policy has its own separate 6,144-char budget.
# No figure is written here: lambdas/test_deploy_platform_policies.py measures both, and the
# last number written down rotted by a thousand characters before anyone noticed.
#
# Each one is scoped by {project_name}-*-<plane>-* name patterns, and every `Resource: "*"`
# statement is forced one of two ways: no resource type exists for its actions, or a measured
# condition key narrows them. GRANTS LAND IN THEIR OWN PR, BEFORE THE RESOURCES THAT NEED
# THEM. README.md.

# ── The control planes: one template, one map ──────────────────────────────
# Every plane's grant renders from ONE template: the seven statements every plane needs, its
# validate-authorize probe where `probe` is set, and its TIMED_OUT rule where `ceiling` is set.
# Statements no other plane has go in one extras template named by the plane. A grant fix is
# one edit, and A NEW PLANE IS ONE ENTRY HERE, landed in its own PR before the plane. README.md.
#
# A key is the plane's `name` in its root call to ./modules/control-plane, which is also the
# infix every statement scopes by. A test holds the keys to those calls and `ceiling` to the
# calls that set one, so the map cannot drift from the planes in either direction.
#
# ⚠ `name` AND `description` ARE ForceNew, and a replaced deploy-role policy is the refresh
# deadlock in infra/info/deploy-role-iam.md. Both are carried verbatim from the eight resources
# this map replaced; shared spaces' policy is `deploy-shared-spaces` while its plane is
# `shared-space`.
locals {
  control_plane_grants = {
    # The archive bucket is scoped by EXACT NAME in the extras, not by the plane's pattern:
    # "{project}-prod-archive" has no trailing segment, so it does not match
    # "{project}-*-archive-*" at all, and a pattern-scoped grant would fail the bucket create.
    "archive" = {
      name        = "deploy-archive"
      description = "Deploy-role grants for the archive control plane (the archive bucket, FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, arcommon layer, log groups), kept off the role's inline-policy aggregate limit."
      sid         = "Archive"
      probe       = true
      ceiling     = true
      extras      = "github-actions-deploy-control-plane-extras-archive.json.tftpl"
    }
    # No workgroup grant: these verbs run in the SHARED portal Athena workgroup, because a
    # dedicated one breaks Lake Formation, so there is no plane-specific one to grant on.
    "data-quality" = {
      name        = "deploy-data-quality"
      description = "Deploy-role grants for the data-quality control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, nine verb Lambdas + shared execution role, dqcommon + polars layers, log groups), kept off the role's inline-policy aggregate limit."
      sid         = "DataQuality"
      probe       = true
      ceiling     = false
      extras      = null
    }
    "file-ops" = {
      name        = "deploy-file-ops"
      description = "Deploy-role grants for the file-operations control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, focommon layer, log groups, TIMED_OUT rule), kept off the role's inline-policy aggregate limit."
      sid         = "FileOps"
      probe       = true
      ceiling     = true
      extras      = null
    }
    "file-send" = {
      name        = "deploy-file-send"
      description = "Deploy-role grants for the file-send control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, fscommon layer, log groups), kept off the role's inline-policy aggregate limit."
      sid         = "FileSend"
      probe       = true
      ceiling     = true
      extras      = null
    }
    "results-conversion" = {
      name        = "deploy-results-conversion"
      description = "Deploy-role grants for the results-conversion control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, verb Lambdas + shared execution role, log groups, TIMED_OUT rule), kept off the role's inline-policy aggregate limit."
      sid         = "ResultsConversion"
      probe       = true
      ceiling     = true
      extras      = null
    }
    # No validate-authorize probe: the cold-start probe reaches this plane through
    # backfill-ever-active instead, granted in the extras, because it defaults to a read-only mode.
    "shared-space" = {
      name        = "deploy-shared-spaces"
      description = "Deploy-role grants for the shared-space control plane (SQS/Pipes/Step Functions/Lambda/roles/logs/S3), kept off the role's inline-policy aggregate limit."
      sid         = "SharedSpace"
      probe       = false
      ceiling     = false
      extras      = "github-actions-deploy-control-plane-extras-shared-space.json.tftpl"
    }
    "table-builder" = {
      name        = "deploy-table-builder"
      description = "Deploy-role grants for the table-builder control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + roles, polars layer, log groups), kept off the role's inline-policy aggregate limit."
      sid         = "TableBuilder"
      probe       = true
      ceiling     = true
      extras      = null
    }
    "table-share" = {
      name        = "deploy-table-share"
      description = "Deploy-role grants for the table-share control plane (FIFO SQS + DLQ, EventBridge Pipe, Step Function + role, five verb Lambdas + shared execution role, tscommon layer, log groups), kept off the role's inline-policy aggregate limit."
      sid         = "TableShare"
      probe       = true
      ceiling     = true
      extras      = null
    }
  }

  control_plane_grant_vars = {
    account_id              = var.account_id
    project_name            = var.project_name
    aws_region              = var.aws_region
    archive_bucket_name     = var.archive_bucket_name
    shared_space_bucket_arn = var.shared_space_bucket_arn
  }
}

# The extras are chosen as a STRING before they are decoded: a conditional between `[]` and a
# decoded tuple of differently-shaped statements is "Inconsistent conditional result types".
# Statement order is not kept from the eight old documents; the provider compares a policy
# document as a set of statements.
resource "aws_iam_policy" "control_plane" {
  for_each = local.control_plane_grants

  name        = "${var.project_name}-${each.value.name}"
  description = each.value.description

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      jsondecode(templatefile("${path.module}/policies/github-actions-deploy-control-plane.json.tftpl", merge(local.control_plane_grant_vars, {
        plane   = each.key
        sid     = each.value.sid
        probe   = each.value.probe
        ceiling = each.value.ceiling
      }))).Statement,
      jsondecode(each.value.extras == null ? "{\"Statement\": []}" : templatefile("${path.module}/policies/${each.value.extras}", local.control_plane_grant_vars)).Statement,
    )
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "control_plane" {
  for_each = local.control_plane_grants

  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.control_plane[each.key].arn
}

# ── Propagation guard for the planes' grants ───────────────────────────────
# ⚠ THE APPLY THAT FIRST ADDED THE ARCHIVE GRANTS WENT RED, and the mechanism is invisible in a
# plan: a plane's resources are created in the SAME apply that attaches the policy authorizing
# them, and depends_on is not enough because IAM is eventually consistent. The planes wait on
# this through `depends_on = [module.base]`.
#
# `triggers`, keyed to every plane's policy BODY, is what makes it cover every plane rather than
# the one it was created with: a sleep with no trigger runs once, so a plane added later would
# get no pause. A new plane, a changed grant or a removed one replaces the sleep, and the
# replacement waits. `replace_triggered_by` is not enough on its own: before OpenTofu 1.12 it
# fires on an update or a replacement and never on a create, and CI runs 1.8. It stays for a
# re-attachment, which changes no body.
#
# 30s is a floor on eventual consistency, not a guarantee. A RED FIRST APPLY OF A NEW PLANE IS
# EXPECTED RATHER THAN A DEFECT; a re-run is the remedy. README.md.
resource "time_sleep" "wait_for_plane_grants" {
  create_duration = "30s"

  triggers = { for plane, grant in aws_iam_policy.control_plane : plane => grant.policy }

  depends_on = [aws_iam_role_policy_attachment.control_plane]

  lifecycle {
    replace_triggered_by = [aws_iam_role_policy_attachment.control_plane]
  }
}

# Notifications. Get/Update/Delete EventSourceMapping are resource-scopable, to an
# event-source-mapping ARN whose UUID does not exist at write time; Create is not. All four are
# condition-scopable on lambda:FunctionArn, which pins the function and with it the region — the
# whole of what that ARN pattern could add — so the statement narrows by condition instead.
# ListEventSourceMappings genuinely cannot be narrowed either way, having no resource types and
# no condition keys, so it keeps a bare "*"; conditioning it would deny the call outright.
# README.md.
resource "aws_iam_policy" "deploy_notifications" {
  name        = "${var.project_name}-deploy-notifications"
  description = "Deploy-role grants for the notifications write pipeline (FIFO SQS queue + DLQ, writer Lambda + role + log group, SQS event-source mapping), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-notifications.json.tftpl", {
    account_id   = var.account_id
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
    account_id   = var.account_id
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_feedback" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_feedback.arn
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
    account_id   = var.account_id
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
#
# The backlog alarm's six CloudWatch actions all scope to the ALARM resource type — measured
# allowed under a service-wide ARN and read off the Service Reference — so its statement names
# the alarm's name pattern and no wildcard is forced.
#
# The description below is stale (the queue is FIFO) and stays stale: `description` is ForceNew
# on aws_iam_policy, so editing it REPLACES the policy the deploy role is applying with.
resource "aws_iam_policy" "deploy_observability" {
  name        = "${var.project_name}-deploy-observability"
  description = "Deploy-role grants for the structured-logging foundation (one standard SQS logs queue + one scheduled sweep Lambda, its execution role, log group and EventBridge rule), kept off the role's inline-policy aggregate limit."

  policy = templatefile("${path.module}/policies/github-actions-deploy-observability.json.tftpl", {
    account_id   = var.account_id
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
    account_id   = var.account_id
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_user_directory" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_user_directory.arn
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
    account_id        = var.account_id
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
# ⚠ EVERY `Resource: "*"` STATEMENT IS FORCED, one of two ways: no resource type exists for its
# actions, or a MEASURED condition key narrows them — and the exemption is per action, never per
# statement, or any condition buys a bare wildcard. Each action was checked with
# simulate-custom-policy, reading implicitDeny under a scoped ARN AND allowed under "*". SCOPE
# THAT DENY LEG TO A SERVICE-WIDE arn:aws:<svc>:<region>:<acct>:* — implicitDeny reads identically
# to a WRONG ARN, the wrong resource type of the right service included, and a service-wide ARN
# cannot be the wrong type. No count is written here; the suite walks the set.
# test_deploy_platform_policies.py PINS THAT MEASUREMENT rather than re-deriving it over the
# network, which would fail on a runner with no egress and pass by finding nothing.
#
# THE EC2 MUTATORS ARE SCOPED BY RESOURCE TYPE, NOT BY NAME — an EC2 ARN carries a generated
# id. ec2:CreateTags/DeleteTags sit in that same statement rather than a second one naming the
# same ten types: the duplicate list had to be hand-synced, and it had already drifted from the
# sentence describing it. They carry NO condition, and could not usefully: ec2:CreateAction does
# not exist on DeleteTags, and on CreateTags it would forbid tagging anything that already
# exists — which is exactly what aws_default_security_group is. Merging is what forecloses
# conditioning them separately, and that is the trade: a condition nothing wants, for one list.
#
# PREFIX-LIST IS PINNED TO `aws`, NOT TO THIS ACCOUNT. Every managed prefix list here is
# AWS-owned (arn:aws:ec2:<region>:aws:prefix-list/…), and the SPA task's egress rule names the
# S3 one because a CIDR rule does not match gateway-endpoint traffic. Of the security-group
# MUTATORS only ec2:ModifySecurityGroupRules accepts a prefix-list resource type —
# Authorize/RevokeSecurityGroupEgress do not — so that is the action the pin is load-bearing
# for. CreateTags/DeleteTags accept one too, and are inert on a list this account cannot tag.
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
    account_id   = var.account_id
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
    account_id      = var.account_id
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

# The portal server's session: the NAT gateway and its Elastic IP the web tier reaches Cognito
# and the API through, the session table, the customer-managed key it is encrypted with, and the
# portal's SSM parameters. Its own document because the platform policy has no room left under
# the managed limit.
#
# The key's statements name key/* because a key's id is random and not known until it exists. A tag
# condition could narrow the update and delete actions, since the provider tags inside CreateKey, and
# is not used: the role can grant itself anything through its own self-manage grant, so a tag scope
# would bound a misdirected apply rather than anyone with the role. An alias condition would bound
# nothing, because this policy may point its own alias at any key. The table's KMS use is
# conditioned on kms:ViaService, which DynamoDB always populates.
# infra/info/deploy-role-iam.md.
resource "aws_iam_policy" "deploy_session" {
  name        = "${var.project_name}-deploy-session"
  description = "Deploy-role grants for the portal server's session: the web tier's NAT gateway and Elastic IP, the session table, its customer-managed key and alias, and the portal's SSM parameters."

  policy = templatefile("${path.module}/policies/github-actions-deploy-session.json.tftpl", {
    account_id   = var.account_id
    project_name = var.project_name
    aws_region   = var.aws_region
  })

  depends_on = [time_sleep.wait_for_self_grant]
}

resource "aws_iam_role_policy_attachment" "deploy_session" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.deploy_session.arn
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
    session   = aws_iam_policy.deploy_session.policy
  }

  depends_on = [
    aws_iam_role_policy_attachment.deploy_platform,
    aws_iam_role_policy_attachment.deploy_platform_frontdoor,
    aws_iam_role_policy_attachment.deploy_session,
  ]
}

