# ── Control-plane IAM roles (SPEC-108) ───────────────────────────────────────
# ONE shared execution role for all nine verb Lambdas (matching table-builder and
# table-share), plus the Step Function role and the Pipe role. Trust + permission
# policies are .tftpl templates rendered with templatefile() (no inline jsonencode IAM,
# per architecture.md Lambda code/infra split).
#
# The execution policy is STAGED — each grant lands in the spec that first needs it, so
# the blast radius grows only with a reviewed reason:
#   - logs                                                → SPEC-108
#   - S3 (source read; registry read; report read+write)
#     + the protected-object Deny                         → SPEC-109 (here)
#   - Glue / Athena / Lake Formation admin                → SPEC-111
# It carries NO glue:/athena:/lakeformation: action yet (SPEC-109 FR-006).
#
# Two boundaries are permanent and must survive every later spec:
#   1. s3:DeleteObject is granted NOWHERE in this arc. drop-temp-tables touches GLUE
#      ONLY, which is what makes it safe to reach from EVERY failure path — including a
#      validator failure, where the body-supplied location is still untrusted. (The
#      sibling file-converter arc had to REMOVE a delete grant for exactly this reason:
#      its cleanup was an authenticated cross-user file-delete primitive.)
#   2. The explicit Deny on s3:PutObject to */user_settings/* and */DO_NOT_DELETE.txt.
#
# WHY THAT DENY IS NOT OPTIONAL (SPEC-109 FR-006): the user-space policy denies
# s3:DeleteObject on user_settings/* (analytics/policies/portal-role-analytics.json.tftpl)
# but leaves s3:PutObject WIDE OPEN. So any role that can write in a user's space can
# overwrite user_settings/notifications.json and PERMANENTLY DESTROY the notification
# inbox — the user cannot even delete the corrupt file to recover, because deleting it is
# itself IAM-denied. The Deny is what makes the guarantee; validate-authorize's
# destination validation is defence in depth. Shape copied from
# table-share/policies/execution.json.tftpl's cross-bucket deny.
#
# Note ReadWriteReports grants GetObject as well as PutObject: assemble-report (SPEC-112)
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
  })
}

# ── Portal role — data-quality enqueue policy (SPEC-109 FR-003) ──────────────
# The browser's ONLY data-quality privilege: sqs:SendMessage to the request queue. A small
# inline policy on the shared portal role (SPEC-011), attached BY NAME like the other
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
