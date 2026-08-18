# ── Control-plane IAM roles ───────────────────────────────────────
# ONE shared execution role for all nine verb Lambdas (matching table-builder and
# table-share), plus the Step Function role and the Pipe role. Trust + permission
# policies are .tftpl templates rendered with templatefile() (no inline jsonencode IAM,
# per architecture.md Lambda code/infra split).
#
# The execution policy is STAGED — each grant lands in the spec that first needs it, so
# the blast radius grows only with a reviewed reason:
#   - logs
#   - S3 (source read; registry read; report read+write)
#     + the protected-object Deny
#   - Glue / Athena / Lake Formation admin
#   - sqs:SendMessage on the NOTIFICATIONS queue only
#
# The notification grant is one action on one queue ARN — the outcome notification is the
# arc's only write outside its own report prefix. Scoped to the notifications queue and
# nothing else: not the data-quality request queue (the browser enqueues there, and a verb
# that could re-enqueue its own work is a loop), and not the DLQ.
#
# THE ZERO-CATALOG-ACCESS PROPERTY IS DELIBERATELY SURRENDERED HERE (
# architecture.md, Control Planes -> Data Quality) — this is a decision, not drift, and it is the
# largest privilege this plane spends. Without it the role could not touch the Glue
# catalog at all. It now can, because the pipeline's whole design is "let Athena read the
# 250 GB, not a Lambda", and Athena reads through a Glue external table. The temp tables
# are created in the ACTOR'S OWN database (personal) or the shared space's (shared) —
# both DYNAMIC, one per user and one per space — so they cannot be statically LF-granted
# in Terraform, which is why the role is an LF ADMIN rather than a grantee. Identical
# reasoning to the table-builder execute-ddl role and the table-share role.
#
# What still bounds it: glue is CreateTable/GetTable/DeleteTable/GetDatabase only — no
# DeleteDatabase, no catalog-wide data grant beyond lakeformation:GetDataAccess (which is
# not scopable to a resource); athena is scoped to THIS module's dedicated workgroup; and
# the two permanent boundaries below are untouched.
#
# Two boundaries are permanent and must survive every later spec:
#   1. s3:DeleteObject is granted NOWHERE in this arc. drop-temp-tables touches GLUE
#      ONLY, which is what makes it safe to reach from EVERY failure path — including a
#      validator failure, where the body-supplied location is still untrusted. (The
#      sibling file-converter arc had to REMOVE a delete grant for exactly this reason:
#      its cleanup was an authenticated cross-user file-delete primitive.)
#   2. The explicit Deny on s3:PutObject to */user_settings/* and */DO_NOT_DELETE.txt.
#
# WHY THAT DENY IS NOT OPTIONAL: the user-space policy denies
# s3:DeleteObject on user_settings/* (analytics/policies/portal-role-analytics.json.tftpl)
# but leaves s3:PutObject WIDE OPEN. So any role that can write in a user's space can
# overwrite user_settings/notifications.json and PERMANENTLY DESTROY the notification
# inbox — the user cannot even delete the corrupt file to recover, because deleting it is
# itself IAM-denied. The Deny is what makes the guarantee; validate-authorize's
# destination validation is defence in depth. Shape copied from
# table-share/policies/execution.json.tftpl's cross-bucket deny.
#
# Note ReadWriteReports grants GetObject as well as PutObject: assemble-report
# READS BACK the intermediate results it wrote, so a write-only grant would fail at the
# very last verb, after all the work was done.

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

# ── Portal role — data-quality enqueue policy ──────────────
# The browser's ONLY data-quality privilege: sqs:SendMessage to the request queue. A small
# inline policy on the shared portal role, attached BY NAME like the other
# control planes do (the role is created in module.data; the root module-level depends_on
# guarantees it exists first). No Lambda invoke, no DLQ, no Step Function — just enqueue.
resource "aws_iam_role_policy" "portal_data_quality" {
  name = "data-quality-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-data-quality.json.tftpl", {
    request_queue_arn = aws_sqs_queue.requests.arn
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
