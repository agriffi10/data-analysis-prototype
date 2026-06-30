# ── Control-plane IAM roles (SPEC-066 FR-002) ────────────────────────────────
# PER-VERB least-privilege roles — one execution role per Lambda (no shared "god"
# role; lambdas.md §7), plus the Step Function role and the Pipe role. Trust +
# permission policies are .tftpl templates rendered with templatefile() (no inline
# jsonencode IAM, per architecture.md Lambda code/infra split).
#
# Stub shape (SPEC-066): each verb role is created with the SHAPE its verb needs,
# refined as the actions land:
#   - validate-authorize → logs only          (registry read added in SPEC-067)
#   - check-table-absent → Glue read + logs    (SPEC-068)
#   - inspect-source     → S3 list/get + logs  (SPEC-068)
#   - infer-schema       → S3 get + logs       (SPEC-069; + the polars layer via CI)
#   - execute-ddl        → logs only           (Athena/Glue/S3/LF finalized in SPEC-070)

# ── Per-verb Lambda execution roles (uniform lambda trust) ───────────────────
resource "aws_iam_role" "verb" {
  for_each = local.table_builder_functions

  name               = local.table_builder_role_names[each.key]
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

# Each verb's permission policy is its own .tftpl (the per-verb shape above). The vars
# map is a superset; each template references only the keys it needs (templatefile
# tolerates unused keys), and log_group_arn is scoped to that verb's own log group.
resource "aws_iam_role_policy" "verb" {
  for_each = local.table_builder_functions

  name = "permissions"
  role = aws_iam_role.verb[each.key].id

  policy = templatefile("${path.module}/policies/${each.key}.json.tftpl", {
    aws_region              = var.aws_region
    account_id              = var.account_id
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    log_group_arn           = local.table_builder_log_group_arns[each.key]
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
