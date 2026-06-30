# ── Control-plane Lambdas (SPEC-066 skeleton) ────────────────────────────────
# Five single-task verb Lambdas — validate-authorize / check-table-absent /
# inspect-source / infer-schema / execute-ddl — orchestrated by the Step Function
# (stepfunction.tf) as a linear pipeline. Each runs under its OWN per-verb role
# (iam.tf) — no shared "god" role (lambdas.md §7) — and gets its task's real
# timeout/memory (locals.tf; a small validator ≠ the polars infer step, lambdas.md §4).
#
# Code-ownership split (architecture.md, SPEC-012): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml builds/ships the Python code
# (lambdas/table-builder-<suffix>/) AND publishes + attaches the polars layer to
# infer-schema. `ignore_changes` keeps `tofu apply` from reverting CI's code OR layer.

# One placeholder package per function so each is valid at create time. CI replaces
# the code (and attaches the polars layer to infer-schema); these stubs only ever run
# pre-deploy.
data "archive_file" "placeholder" {
  for_each = local.table_builder_functions

  type        = "zip"
  output_path = "${path.module}/build/table-builder-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('table-builder-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit log group per function so retention is managed (14 days; matches SPEC-012/
# 033). Lambda would otherwise create one with infinite retention on first invoke.
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.table_builder_functions

  name              = local.table_builder_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.table_builder_functions

  function_name = local.table_builder_function_names[each.key]
  role          = aws_iam_role.verb[each.key].arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # Source-bucket names every reading verb needs (SPEC-068→070 use them); harmless on
  # the verbs that don't. Per-verb action env (USER_POOL_ID, ATHENA_WORKGROUP, …) is
  # added by the owning specs.
  environment {
    variables = {
      USER_SPACE_BUCKET   = var.user_space_bucket_name
      SHARED_SPACE_BUCKET = var.shared_space_bucket_name
      ADMIN_BUCKET        = var.admin_bucket_name
    }
  }

  # Bootstrap with the placeholder; CI replaces code + (infer-schema) attaches the
  # polars layer.
  filename         = data.archive_file.placeholder[each.key].output_path
  source_code_hash = data.archive_file.placeholder[each.key].output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment — never revert them on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.verb,
    aws_cloudwatch_log_group.functions,
  ]
}
