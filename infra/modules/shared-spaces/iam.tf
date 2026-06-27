# ── Control-plane IAM roles (SPEC-050 FR-003) ────────────────────────────────
# Two roles:
#   - orchestrator role: the single privileged role BOTH the Step Function and the
#     provisioner Lambda run under (trust = states + lambda). It carries the full
#     permission policy the pipeline will need (Glue, Lake Formation, S3 on the
#     shared bucket + admin registry prefix, Cognito admin, states/logs). SPEC-050
#     creates the role + policy; the RESOURCES/GRANTS it acts on (membership tags,
#     LF grants, per-space DBs) arrive in SPEC-056 + the action specs. (FR-003 calls
#     for one privileged role both run under; a separate SFN exec role is folded in.)
#   - pipe role: assumed by the EventBridge Pipe to read the queue and start the SFN.
#
# Trust + permission policies are .tftpl templates rendered with templatefile()
# (no inline jsonencode IAM, per architecture.md Lambda code/infra split).

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
    aws_region               = var.aws_region
    account_id               = var.account_id
    shared_space_bucket_arn  = local.shared_space_bucket_arn
    admin_bucket_arn         = local.admin_bucket_arn
    user_space_bucket_arn    = local.user_space_bucket_arn
    provisioner_function_arn = local.provisioner_function_arn
    lambda_log_group_arn     = local.lambda_log_group_arn
    sfn_log_group_arn        = local.sfn_log_group_arn
  })
}

# ── Portal role — shared-space membership policy (SPEC-056 FR-002) ────────────
# A THIRD inline policy on the shared portal role (after data's "user-space-access"
# and analytics' "analytics-access"), attached BY NAME like the analytics module does
# (the role is created in module.data; module-level depends_on = [module.data]
# guarantees it exists first). Fixed size — ten slots regardless of how many shared
# spaces exist — so it stays well inside the portal role's inline-policy aggregate.
#
# Each slot is templated on ${aws:PrincipalTag/shared_space_k}: S3 object CRUD +
# multipart and Glue DB/table scoped to the slot's space, a ListBucket conditioned on
# the slot prefix, plus the shared delete-denies (athenaresults/ + DO_NOT_DELETE.txt)
# and the SINGLE privileged grant the browser receives — sqs:SendMessage to the
# request queue only. An unset slot stamps no tag → the statement matches nothing
# (implicit deny); verified with aws iam simulate-custom-policy.
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
