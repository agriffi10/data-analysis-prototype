# ── Control-plane IAM roles ───────────────────────────────────────────────────
# One shared execution role for all nine verbs, plus the Step Function and Pipe roles.
#
# ⚠ THE ZERO-CATALOG-ACCESS PROPERTY IS DELIBERATELY SURRENDERED HERE, and it is the largest
# privilege this plane spends: the design is "let Athena read the 250 GB, not a Lambda", and
# Athena reads through a Glue external table. The temp tables land in DYNAMIC databases, so the
# role is an LF ADMIN rather than a grantee.
#
# TWO BOUNDARIES ARE PERMANENT AND MUST SURVIVE EVERY LATER SPEC:
#   1. s3:DeleteObject is granted NOWHERE. drop-temp-tables touches GLUE ONLY, which is what
#      makes it safe to reach from EVERY failure path — including a validator failure, where
#      the body-supplied location is still untrusted.
#   2. The Deny on s3:PutObject to */user_settings/* and */DO_NOT_DELETE.txt. The user-space
#      policy denies DELETE there but leaves PUT WIDE OPEN, so any role that can write in a
#      user's space could overwrite notifications.json and PERMANENTLY DESTROY the inbox — the
#      user cannot even delete the corrupt file, because that is itself IAM-denied.
#
# ReadWriteReports grants GetObject as well as PutObject: assemble-report READS BACK what it
# wrote, so a write-only grant fails at the very last verb after all the work is done.
#
# The notification grant is scoped to the NOTIFICATIONS queue only — not this plane's request
# queue, because a verb that could re-enqueue its own work is a loop. README.md.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn           = local.data_quality_log_group_wildcard_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    admin_bucket_arn        = local.admin_bucket_arn
    glue_catalog_arn        = local.glue_catalog_arn
    glue_database_any       = local.glue_database_any
    glue_table_any          = local.glue_table_any
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
    # Invoke every verb Lambda (constructed ARNs, known at plan).
    function_arns_json = jsonencode(local.data_quality_function_arns)
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
