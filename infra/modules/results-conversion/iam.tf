# ── Control-plane IAM roles ───────────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role.
#
# THE EXECUTION ROLE'S ONLY WRITE is s3:PutObject + s3:AbortMultipartUpload on the two space
# buckets, added with the converter and bounded by the Deny below. The abort rides with the put
# because an incomplete multipart holds storage indefinitely and is invisible in a listing.
# Still absent, and that absence is the point: no athena:StartQueryExecution — the input is the
# execution's own result object, never a second query, so a grant to start one would be a grant
# nothing here may use.
#
# THE DENY ON THE APP-MANAGED PREFIXES SHIPS BEFORE THE ALLOW IT BOUNDS, mirroring the portal
# role's, so a validator defect can never write into a results, receipt or settings folder
# even once the write grant exists. In the personal bucket the prefix IS the principal tag; in
# the shared bucket an IAM wildcard matches "/" and the Deny reaches the folder at any depth.
#
# NO COGNITO GRANT: this plane authorizes the actor against a SPACE, never against a user
# directory. There is no recipient.
#
# NO states:DescribeExecution. The TIMED_OUT door reads the request from the event input; SQS
# refuses a message over 256 KB at the send and EventBridge carries an event of that size, so
# no request that reaches the machine can be dropped by the rule.
#
# ⚠ IAM REJECTS A "//" COMMENT KEY INSIDE A STATEMENT, so rationale goes HERE.

resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn           = local.results_conversion_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    athena_workgroup_arn    = local.athena_workgroup_arn
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
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
    function_arns_json = jsonencode(local.results_conversion_function_arns)
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
