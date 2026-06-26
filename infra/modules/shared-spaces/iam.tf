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
    provisioner_function_arn = local.provisioner_function_arn
    lambda_log_group_arn     = local.lambda_log_group_arn
    sfn_log_group_arn        = local.sfn_log_group_arn
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
