# ── Control-plane IAM roles ──────────────────────────────────────────────────
# ONE shared execution role for every verb Lambda (user decision — reverses the
# SPEC-066 per-verb roles, mirroring the shared-spaces single-orchestrator model in
# SPEC-062), plus the Step Function role and the Pipe role. Trust + permission policies
# are .tftpl templates rendered with templatefile() (no inline jsonencode IAM, per
# architecture.md Lambda code/infra split).
#
# The execution policy (execution.json.tftpl) is the UNION of every verb's needs:
#   - registry read (validate-authorize) + source S3 read/list (inspect/infer/execute)
#   - Glue Describe + CREATE + UPDATE on the account catalog (check-table-absent +
#     execute-ddl; GetTable for load-table-definition, which only READS; and UpdateTable
# for apply-refresh, the in-place rebuild — scoped to the SAME catalog +
#     database/* + table/*/* as the other Glue actions, not wider)
#
# `glue:DeleteTable` WAS HERE AND IS DELETED (SPEC-149, replacing SPEC-144). The refresh no
# longer drops and recreates the table; it replaces the definition in place, so NO verb on
# this plane deletes a table any more. The old comment argued a drop was SAFE because these
# tables are EXTERNAL — true, and now beside the point: the stronger statement is that the
# refresh path does not delete anything at all, and a permission the code cannot use is one
# a future bug can still reach. A test greps the table-builder modules to keep it that way.
#
# The explicit `Deny s3:DeleteObject` (Sid NoDataObjectDelete) is UNTOUCHED. It never
# depended on the drop: it is what makes "this plane cannot destroy a user's data"
# enforceable rather than merely intended, and it outlives the mechanism that prompted it.
#
# Lake Formation needs NO change for the update, and the absence is recorded so the next
# reader does not go looking for a missing grant: the `portal-managed` tag-policy grants
# already give every control-plane execution role ALTER — the LF permission UpdateTable
# requires — at TABLE level, alongside DROP at both levels
# (infra/modules/analytics/lakeformation.tf, `control_plane_tag_table`).
#   - Athena run + LF data-access + Athena-results write (execute-ddl), delete denied
#   - logs to every table-builder function log group (wildcard)
# The role is ALSO the table-builder Lake Formation admin (analytics data_lake_settings,
# wired from root), so check-table-absent's GetTable + execute-ddl's CREATE resolve in
# the DYNAMIC per-user + per-shared-space target databases that can't be statically
# LF-granted.

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
    # Every verb emits an outcome notification (SendMessage, this queue only).
    notifications_queue_arn = var.notifications_queue_arn
    # Structured-logging producer, same Sid and shape as data-quality's, the drain's
    # and shared-space's, so all four read as one pattern.
    logs_queue_arn = var.logs_queue_arn
  })
}

# ── Portal role — table-build enqueue policy ────────────────
# The browser's ONLY table-builder privilege: sqs:SendMessage to the request queue.
# A small inline policy on the shared portal role, attached BY NAME like
# the notifications / shared-spaces modules do (the role is created in module.data;
# the root module-level depends_on guarantees it exists first). No Lambda invoke, no
# DLQ, no Step Function — just enqueue. The send helper that uses it lands in SPEC-071.
resource "aws_iam_role_policy" "portal_table_builder" {
  name = "table-build-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-table-builder.json.tftpl", {
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
