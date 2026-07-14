# ── Control-plane Lambdas (SPEC-088 skeleton) ────────────────────────────────
# Five single-task verb Lambdas — validate-authorize / inspect-source /
# check-target-absent / copy-objects / create-table — orchestrated by the Step
# Function (stepfunction.tf). All five share ONE execution role (iam.tf; user
# decision, docs/table-share-architecture.md §7) and each gets its task's real
# timeout/memory (locals.tf; a small validator ≠ a long parallel S3 copy,
# lambdas.md §4).
#
# Code-ownership split (architecture.md, SPEC-012): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml builds/ships the Python
# code (lambdas/table-share-<suffix>/) AND publishes + attaches the layers to all
# five: the tscommon domain layer PLUS the shared cpcommon layer (SPEC-107).
# `ignore_changes` keeps `tofu apply` from reverting CI's code OR layers.

# One placeholder package per function so each is valid at create time. CI replaces
# the code (and attaches the tscommon layer); these stubs only ever run pre-deploy.
data "archive_file" "placeholder" {
  for_each = local.table_share_functions

  type        = "zip"
  output_path = "${path.module}/build/table-share-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('table-share-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit log group per function so retention is managed (14 days; matches the
# other control planes). Lambda would otherwise create one with infinite retention
# on first invoke.
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.table_share_functions

  name              = local.table_share_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.table_share_functions

  function_name = local.table_share_function_names[each.key]
  role          = aws_iam_role.execution.arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # EVERY variable tscommon/config.py _require()s at import must be COMMON to all
  # five verbs: the shared layer's fail-fast runs on any `from tscommon import …`
  # chain, so a verb missing ANY required var crashes at cold start (the
  # table-builder production break, PR #196). The per-verb map (locals.tf) is
  # reserved for OPTIONAL action env only.
  environment {
    variables = merge(
      {
        ADMIN_BUCKET          = var.admin_bucket_name
        USER_SPACE_BUCKET     = var.user_space_bucket_name
        SHARED_SPACE_BUCKET   = var.shared_space_bucket_name
        COGNITO_USER_POOL_ID  = var.user_pool_id
        COGNITO_APP_CLIENT_ID = var.app_client_id
        ATHENA_WORKGROUP      = var.athena_workgroup
        # SPEC-094 (optional in tscommon.config — unset ⇒ emits are logged no-ops).
        NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      },
      lookup(local.table_share_verb_env, each.key, {}),
    )
  }

  # Bootstrap with the placeholder; CI replaces code + attaches the tscommon layer.
  filename         = data.archive_file.placeholder[each.key].output_path
  source_code_hash = data.archive_file.placeholder[each.key].output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment — never revert them on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.execution,
    aws_cloudwatch_log_group.functions,
  ]
}
