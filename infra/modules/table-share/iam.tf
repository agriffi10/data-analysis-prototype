# ── Control-plane IAM roles (SPEC-088) ───────────────────────────────────────
# ONE shared execution role for all five verb Lambdas (user decision,
# docs/table-share-architecture.md §7 — mirrors the table-builder's consolidated
# model; per-verb roles are NOT used), plus the Step Function role and the Pipe
# role. Trust + permission policies are .tftpl templates rendered with
# templatefile() (no inline jsonencode IAM, per architecture.md).
#
# At this stage the execution policy (execution.json.tftpl) is LOGS ONLY — the
# placeholder path needs nothing else. The LF-admin / Glue / Athena / S3 / Cognito /
# registry / notifications grants are added by the spec that first needs each
# (SPEC-089/090/092/094), keeping this foundation behavior-free.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn = local.table_share_log_group_wildcard_arn
  })
}

# ── Step Function role (orchestrates the verbs) ──────────────────────────────
resource "aws_iam_role" "sfn" {
  name               = local.sfn_role_name
  assume_role_policy = templatefile("${path.module}/policies/sfn-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "sfn" {
  name = "permissions"
  role = aws_iam_role.sfn.id

  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    # Invoke every verb Lambda (constructed ARNs, known at plan).
    function_arns_json = jsonencode(local.table_share_function_arns)
    sfn_log_group_arn  = local.sfn_log_group_arn
  })
}

# ── Pipe role (EventBridge Pipe) ─────────────────────────────────────────────
resource "aws_iam_role" "pipe" {
  name               = local.pipe_role_name
  assume_role_policy = templatefile("${path.module}/policies/pipe-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "pipe" {
  name = "pipe"
  role = aws_iam_role.pipe.id

  policy = templatefile("${path.module}/policies/pipe-permissions.json.tftpl", {
    queue_arn         = aws_sqs_queue.requests.arn
    state_machine_arn = local.state_machine_arn
  })
}
