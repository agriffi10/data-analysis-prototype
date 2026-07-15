# ── Control-plane IAM roles (SPEC-108) ───────────────────────────────────────
# ONE shared execution role for all nine verb Lambdas (matching table-builder and
# table-share), plus the Step Function role and the Pipe role. Trust + permission
# policies are .tftpl templates rendered with templatefile() (no inline jsonencode IAM,
# per architecture.md Lambda code/infra split).
#
# AT SPEC-108 THE EXECUTION POLICY IS LOGS ONLY. This is deliberate and staged:
#   - S3 (source read; report read+write) + the protected-object Deny → SPEC-109
#   - Glue / Athena / Lake Formation admin                            → SPEC-111
# Each grant lands in the spec that first needs it, so the blast radius grows only with
# a reviewed reason. Two boundaries are permanent and must survive every later spec:
#   1. s3:DeleteObject is granted NOWHERE in this arc. drop-temp-tables touches GLUE
#      ONLY, which is what makes it safe to reach from EVERY failure path — including a
#      validator failure, where the body-supplied location is still untrusted. (The
#      sibling file-converter arc had to REMOVE a delete grant for exactly this reason:
#      its cleanup was an authenticated cross-user file-delete primitive.)
#   2. An explicit Deny on s3:PutObject to */user_settings/* and */DO_NOT_DELETE.txt
#      (SPEC-109). The user-space policy denies DELETE there but leaves PUT wide open, so
#      any space-scoped writer could overwrite notifications.json and destroy the inbox
#      UNRECOVERABLY — the user cannot delete the corrupt file either.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn = local.data_quality_log_group_wildcard_arn
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
