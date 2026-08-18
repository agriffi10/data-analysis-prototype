# ── Control-plane IAM roles ───────────────────────────────────────
# ONE shared execution role for every verb Lambda (user decision,
# docs/architecture.md (Control Planes -> Table Share) — mirrors the table-builder's consolidated
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

  # CopyPlanReadWrite (2026-07-21): inspect-source WRITES the object list to
  # {admin_bucket}/table-share/{requestId}/ and passes a KEY onward; copy-objects READS it.
  # The list used to ride INLINE on the Step Functions state, and the Map's ItemSelector
  # copies the whole state into every item — at the shipped caps (1000 objects, ordinary
  # Hive keys) that put the Map's output state at 95% of the 256 KB payload limit, where
  # States.DataLimitExceeded fires ON THE MAP and destroys every per-recipient outcome the
  # Map exists to preserve. Same fix and same reason as SPEC-110's data-quality manifest.
  #
  # THE ADMIN BUCKET, not a user space: the SPA never browses it, so the plan needs no
  # hidden-folder convention, and a user cannot delete it out from under a running
  # execution (they DO hold s3:DeleteObject in their own space). No delete is granted here
  # either — analytics/s3.tf's expire-table-share-copy-plans lifecycle rule expires it.
  #
  # NOTE FOR ANYONE ADDING A STATEMENT: IAM rejects a "//" comment key inside a statement
  # ("Policy input list item 1 has invalid content" — verified with simulate_custom_policy),
  # so rationale goes HERE, not in the .tftpl.
  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn = local.table_share_log_group_wildcard_arn
    # Registry read (source authz + recipient-space existence), Cognito
    # recipient-existence checks. SPEC-090: source-bucket ListBucket for the
    # copy-plan listing. SPEC-092: Glue CreateTable + the Athena DDL run/poll +
    # results write + lakeformation:GetDataAccess — the LF-admin designation itself
    # lives in module.analytics' data_lake_settings (root wires the constructed
    # role ARN; recipient DBs are dynamic, so catalog-wide create via LF admin,
    # mirroring the table-builder). SPEC-094: sqs:SendMessage to the notifications
    # queue ONLY (best-effort sender + recipient outcome notifications).
    admin_bucket_arn        = local.admin_bucket_arn
    user_pool_arn           = local.user_pool_arn
    glue_catalog_arn        = local.glue_catalog_arn
    glue_database_any       = local.glue_database_any
    glue_table_any          = local.glue_table_any
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    athena_workgroup_arn    = local.athena_workgroup_arn
    notifications_queue_arn = var.notifications_queue_arn
    # Structured-logging producer; same Sid and shape as the other three planes.
    logs_queue_arn = var.logs_queue_arn
  })
}

# ── Portal role — table-share enqueue policy ────────────────
# The browser's ONLY table-share privilege: sqs:SendMessage to the request queue.
# A small inline policy on the shared portal role, attached BY NAME like
# the table-builder / notifications modules (the role is created in module.data; the
# root module-level depends_on guarantees it exists first). No Lambda invoke, no DLQ,
# no Step Function — just enqueue. The send helper is enqueueTableShare; the UI that
# uses it lands in SPEC-093.
resource "aws_iam_role_policy" "portal_table_share" {
  name = "table-share-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-table-share.json.tftpl", {
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

  # The Distributed Map's permissions are the STATE MACHINE's, not the
  # Lambdas'. AWS is explicit that the state machine role invokes StartExecution for each
  # child workflow and reads/writes the ItemReader + ResultWriter objects — so the manifest
  # read and the results write belong here, beside states:StartExecution, and NOT in
  # execution.json.tftpl. That misplacement renders green, applies green, passes the policy
  # render test, and fails on the first real share with AccessDenied at the ItemReader.
  # StopExecution is NOT granted: nothing here stops a child, and StartExecution +
  # DescribeExecution is the documented least-privilege pair.
  #
  # The ResultWriter bucket is the ADMIN bucket — a module input of this account's stack — so
  # the same-account/same-Region requirement (a cross-account or cross-Region export fails the
  # execution with States.ResultWriterFailed) holds by construction rather than by assertion.
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
