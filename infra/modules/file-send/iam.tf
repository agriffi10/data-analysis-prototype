# ── Control-plane IAM roles ─────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role.
#
# ⚠ THE SOURCE GRANTS ARE BUCKET-WIDE, AND THE ISOLATION IS NOT IN THEM. A per-user condition is
# not expressible here — the sender is a runtime value from a verified token, not a principal
# tag on this role. The isolation is fscommon.authz + fscommon.paths, applied before any listing
# AND re-applied to every key it returns.
#
# THE ONLY WRITE INTO A USER'S SPACE IS UNDER shared_files/, scoped in both data buckets, so this
# role can write into an inbox and NOWHERE ELSE in anybody's prefix.
#
# AdminGetUser ALONE, deliberately: ListUsers would let this role enumerate the whole pool, and
# nothing in this repo calls it. README.md.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  # NoDataObjectDelete: a Deny present from the FIRST apply. A send is a COPY — it never
  # deletes and never overwrites — so nothing here will ever need s3:DeleteObject, and writing
  # the Deny early makes that enforced rather than intended. This role is on the user-space
  # bucket's principal allowlist, so a bug in a later verb would delete another user's data.
  #
  # ⚠ IAM REJECTS A "//" COMMENT KEY INSIDE A STATEMENT, so rationale goes HERE, never in the
  # .tftpl.
  #
  # states:DescribeExecution is on THIS role rather than the machine's because it is the
  # notify-failure LAMBDA that calls it, invoked by EventBridge OUTSIDE any execution. Without
  # it the sends most likely to time out are the ones nobody can be told about. README.md.
  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    execution_arn_wildcard  = local.child_execution_arn_wildcard
    log_group_arn           = local.file_send_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    user_pool_arn           = local.user_pool_arn
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

  # ⚠ THE DISTRIBUTED MAP'S PERMISSIONS BELONG HERE, NOT ON THE EXECUTION ROLE. Putting them
  # on the Lambda role renders, applies and unit-tests green, then fails on the first real send
  # with AccessDenied at the ItemReader.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json           = jsonencode(local.file_send_function_arns)
    sfn_log_group_arn            = local.sfn_log_group_arn
    state_machine_arn            = local.state_machine_arn
    child_execution_arn_wildcard = local.child_execution_arn_wildcard
    admin_bucket_arn             = local.admin_bucket_arn
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
