# ── Provisioner Lambda (SPEC-050 FR-003) ─────────────────────────────────────
# The single function the Step Function invokes. SPEC-050 ships a dispatch/echo
# SKELETON — it provisions nothing; per-action logic (create/add/remove/leave/
# delete, switched on the request `action`) lands in SPEC-051→055.
#
# Code-ownership split (architecture.md, established SPEC-012): Terraform owns the
# function INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml owns the Python
# code (builds lambdas/shared-space-provisioner, uploads it, update-function-code).
# `ignore_changes` keeps `tofu apply` from reverting CI's deployed code.
#
# The function runs under the shared ORCHESTRATOR role (iam.tf) — the same role the
# Step Function uses — so it already holds every privileged permission the action
# specs will need; no separate exec role.

# Placeholder package so the function is valid at create time. The real code is
# deployed by CI; this stub only ever runs if a deploy has not happened yet.
data "archive_file" "provisioner_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/shared-space-provisioner-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('shared-space-provisioner Lambda code not yet deployed by CI')\n"
    filename = "shared_space_provisioner.py"
  }
}

# Explicit log group so retention is managed (Lambda would otherwise create one with
# infinite retention on first invoke). 14-day retention (matches SPEC-012/033).
resource "aws_cloudwatch_log_group" "provisioner" {
  name              = local.lambda_log_group_name
  retention_in_days = 14

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_lambda_function" "provisioner" {
  function_name = local.provisioner_function_name
  role          = aws_iam_role.orchestrator.arn
  runtime       = "python3.12"
  handler       = "shared_space_provisioner.handler"
  timeout       = 60

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.provisioner_placeholder.output_path
  source_code_hash = data.archive_file.provisioner_placeholder.output_base64sha256

  lifecycle {
    # CI owns the code — never revert it on apply.
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [
    aws_iam_role_policy.orchestrator,
    aws_cloudwatch_log_group.provisioner,
    time_sleep.wait_for_deploy_policy,
  ]
}
