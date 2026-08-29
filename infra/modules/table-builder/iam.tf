# ── Control-plane IAM roles ──────────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role. The execution policy is
# the UNION of every verb's needs. See ../../info/control-plane-shape.md and README.md.
#
# `glue:DeleteTable` WAS HERE AND IS DELETED — no verb on this plane deletes a table any more,
# and a permission the code cannot use is one a future bug can still reach. A test greps these
# modules to keep it that way.
#
# The explicit `Deny s3:DeleteObject` (Sid NoDataObjectDelete) is UNTOUCHED: it never depended
# on the drop, and it outlives the mechanism that prompted it.
#
# The role is ALSO this plane's Lake Formation admin, which is what makes CREATE resolve in the
# DYNAMIC target databases. LF, not the IAM resource scope, gates which database a table
# lands in.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    admin_bucket_arn        = local.admin_bucket_arn
    log_group_arn           = local.table_builder_log_group_wildcard_arn
    athena_workgroup_arn    = local.athena_workgroup_arn
    glue_catalog_arn        = local.glue_catalog_arn
    glue_database_any       = local.glue_database_any
    glue_table_any          = local.glue_table_any
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
    # Invoke every verb Lambda (constructed ARNs, known at plan).
    function_arns_json = jsonencode(local.table_builder_function_arns)
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
