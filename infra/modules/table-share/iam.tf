# ── Control-plane IAM roles ──────────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role.
# ../../info/control-plane-shape.md and README.md.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  # The copy plan travels BY POINTER: inspect-source writes the object list to
  # {admin_bucket}/table-share/{requestId}/ and passes a KEY onward. Inline, the Map's
  # ItemSelector copies the whole state into every item and States.DataLimitExceeded fires ON
  # THE MAP, destroying every per-recipient outcome the Map exists to preserve.
  #
  # THE ADMIN BUCKET, not a user space — a user holds s3:DeleteObject in their own space and
  # could delete the plan out from under a running execution.
  #
  # ⚠ IAM REJECTS A "//" COMMENT KEY INSIDE A STATEMENT, so rationale goes HERE, never in the
  # .tftpl. README.md.
  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn = local.table_share_log_group_wildcard_arn
    # The union of every verb's needs. The LF-admin designation itself lives in
    # module.analytics' data_lake_settings; recipient DBs are dynamic, so create is
    # catalog-wide via LF admin.
    admin_bucket_arn        = local.admin_bucket_arn
    user_pool_arn           = local.user_pool_arn
    glue_catalog_arn        = local.glue_catalog_arn
    glue_database_any       = local.glue_database_any
    glue_table_any          = local.glue_table_any
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    athena_workgroup_arn    = local.athena_workgroup_arn
    notifications_queue_arn = var.notifications_queue_arn

    logs_queue_arn = var.logs_queue_arn
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

  # ⚠ THE DISTRIBUTED MAP'S PERMISSIONS ARE THE STATE MACHINE'S, NOT THE LAMBDAS'. The
  # ItemReader read and the ResultWriter write belong HERE, beside states:StartExecution.
  # Putting them in execution.json.tftpl renders green, applies green, passes the policy-render
  # test, and fails on the first real share with AccessDenied at the ItemReader.
  #
  # StopExecution is NOT granted. The ResultWriter bucket is the ADMIN bucket, so the
  # same-account/same-Region requirement holds by construction. README.md.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    # Invoke every verb Lambda (constructed ARNs, known at plan).
    function_arns_json           = jsonencode(local.table_share_function_arns)
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
