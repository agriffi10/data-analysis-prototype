# ── Control-plane IAM roles ───────────────────────────────────────────────────
# TWO roles, not three — this plane predates the split. The ORCHESTRATOR role is the single
# privileged role the Step Function AND every verb Lambda run under, so its policy is the union
# of every verb's permissions. The PIPE role reads the queue and starts the machine. README.md.

# ── Orchestrator role (Step Function + Lambda) ───────────────────────────────
resource "aws_iam_role" "orchestrator" {
  name               = local.orchestrator_role_name
  assume_role_policy = templatefile("${path.module}/policies/orchestrator-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_iam_role_policy" "orchestrator" {
  name = "orchestrator"
  role = aws_iam_role.orchestrator.id

  policy = templatefile("${path.module}/policies/orchestrator-permissions.json.tftpl", {
    aws_region              = var.aws_region
    account_id              = var.account_id
    shared_space_bucket_arn = local.shared_space_bucket_arn
    admin_bucket_arn        = local.admin_bucket_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    # Invoke every verb/validator Lambda (constructed ARNs, known at plan).
    function_arns_json    = jsonencode(local.shared_space_function_arns)
    lambda_log_groups_arn = local.lambda_log_groups_arn
    sfn_log_group_arn     = local.sfn_log_group_arn
    # Trusted notifications producer — sqs:SendMessage scoped to this ARN only.
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
  })
}

# ── Portal role — shared-space membership policy ────────────
# The portal role's THIRD inline policy, attached BY NAME. FIXED SIZE — ten slots regardless of
# how many spaces exist — so it stays inside the role's inline-policy aggregate.
#
# Each slot is templated on ${aws:PrincipalTag/shared_space_k}; an unset slot stamps no tag, so
# the statement matches nothing. Verified with simulate-custom-policy.
#
# The archive-receipt Deny uses the WILDCARD SPACE SEGMENT rather than a per-slot loop, and
# that is NOT a shortcut: A DENY NEEDS NO TAG TO BE CORRECT, so one statement covers every slot
# including ones the user does not hold — where the per-slot ALLOWS must be tag-scoped or they
# would grant access to spaces the user is not in. README.md.
resource "aws_iam_role_policy" "portal_shared_space" {
  name = "shared-space-membership"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-shared-space.json.tftpl", {
    shared_space_bucket_arn = local.shared_space_bucket_arn
    aws_region              = var.aws_region
    account_id              = var.account_id
    request_queue_arn       = aws_sqs_queue.requests.arn
    max_shared_memberships  = var.max_shared_memberships
  })
}

# ── Pipe role (EventBridge Pipe) ─────────────────────────────────────────────
resource "aws_iam_role" "pipe" {
  name               = local.pipe_role_name
  assume_role_policy = templatefile("${path.module}/policies/pipe-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_iam_role_policy" "pipe" {
  name = "pipe"
  role = aws_iam_role.pipe.id

  policy = templatefile("${path.module}/policies/pipe-permissions.json.tftpl", {
    queue_arn         = aws_sqs_queue.requests.arn
    state_machine_arn = local.state_machine_arn
  })
}
