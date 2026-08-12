# ── Control-plane IAM roles (SPEC-168) ───────────────────────────────────────
# ONE shared execution role for every verb Lambda (the consolidated model every plane has
# used since SPEC-062), plus the Step Function role and the Pipe role. Trust + permission
# policies are .tftpl templates rendered with templatefile() (no inline jsonencode IAM,
# per architecture.md).
#
# The execution policy grants exactly what the SHIPPED verbs need and nothing this arc
# does not yet provision: the registry read that authorizes a shared source, the
# notifications queue, the logs queue and its own log group. THERE IS NO S3 GRANT ON ANY
# DATA BUCKET YET — not the two space buckets, and not the archive bucket this module
# creates. The source listing and read land with SPEC-169's expansion, the Glacier write
# and the source DELETION with its transfer, and the restore reads with SPEC-170/171.
#
# THE SOURCE DELETION IS WHY THAT RESTRAINT MATTERS MORE HERE THAN ON ANY OTHER PLANE.
# Archiving is the only operation in this repo that deletes a user's data as a side effect
# of a copy. Every other plane's execution role can carry a blanket `Deny s3:DeleteObject`
# from its first apply and have that be an enforced property forever (file-send and
# table-share both do). THIS ROLE CANNOT — SPEC-169 has to grant DeleteObject on the
# source buckets — so the property that replaces it is a narrower one and belongs in the
# spec that grants it: the delete must be scoped to the space prefixes and must never
# reach `athenaresults/`, `user_settings/` or any `DO_NOT_DELETE.txt`, and the commit gate
# in front of it (every object confirmed copied, or the archive rolls back) is what keeps
# "copied 900 of 1000, deleted 1000" out of reach. Granting nothing today keeps that a
# decision SPEC-169 has to make explicitly rather than one it inherits.
#
# NOTE FOR ANYONE ADDING A STATEMENT: IAM rejects a "//" comment key inside a statement
# ("Policy input list item 1 has invalid content" — verified with simulate_custom_policy),
# so rationale goes HERE, not in the .tftpl.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn           = local.archive_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
  })
}

# ── Portal role — archive enqueue policy (SPEC-168 FR-007) ───────────────────
# THE BROWSER'S ONLY POSITIVE ARCHIVE PRIVILEGE: sqs:SendMessage to the request queue.
# It is granted NOTHING on the archive bucket — not GetObject, not ListBucket, nothing —
# and a rendered-policy test asserts the portal role has no statement of any kind naming
# that ARN. The browser's only relationship with that bucket is that it has none, and the
# only route to archived bytes is a restore request through this plane.
#
# A small inline policy on the shared portal role (SPEC-011), attached BY NAME like the
# file-send / table-builder / table-share / notifications modules (the role is created in
# module.data; the root module-level depends_on guarantees it exists first). The two
# `archive/` write DENIES that go with this live in the space buckets' own portal
# templates (modules/data, modules/shared-spaces) — beside the Allows they narrow, which
# is the honest home for them.
resource "aws_iam_role_policy" "portal_archive" {
  name = "archive-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-archive.json.tftpl", {
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

  # InvokeFunction on the verbs + log delivery. No Distributed Map grants yet: this
  # machine has no Map. When SPEC-169 adds one, its states:/S3 permissions belong HERE and
  # not on the execution role — the state machine is what calls StartExecution for each
  # child and what reads the ItemReader object. Putting them on the Lambda role renders,
  # applies and unit-tests green, then fails on the first real run with AccessDenied at
  # the ItemReader (SPEC-160 FR-006's finding).
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json = jsonencode(local.archive_function_arns)
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
