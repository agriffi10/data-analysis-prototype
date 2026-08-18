# ── Control-plane Lambdas (skeleton) ────────────────────────────────
# Nine single-task verb Lambdas — validate-authorize / inspect-source /
# create-temp-tables / start-profile-query / check-query / byte-scan / assemble-report /
# drop-temp-tables / notify-failure — orchestrated by the Step Function
# (stepfunction.tf). All nine share ONE execution role (iam.tf; matching table-builder
# and table-share) and each gets its task's real timeout AND memory (locals.tf — see the
# shared-spaces implicit-128 MB precedent recorded there).
#
# notify-failure is a PLACEHOLDER here: the notification producer wires its real handler and the
# NotifyFailure state. Provisioning it in the foundation (function + log group +
# deploy-lambdas matrix entry) is the notify-failure-Lambda pattern — the foundation
# spec provisions the placeholder, the producer spec wires it.
#
# Code-ownership split (architecture.md): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml builds/ships the Python code
# (lambdas/data-quality-<suffix>/) AND publishes + attaches the layers: cpcommon +
# dqcommon on all nine, plus the polars layer on inspect-source. `ignore_changes` keeps
# `tofu apply` from reverting CI's code OR layers.

# One placeholder package per function so each is valid at create time. CI replaces the
# code (and attaches the layers); these stubs only ever run pre-deploy.
data "archive_file" "placeholder" {
  for_each = local.data_quality_functions

  type        = "zip"
  output_path = "${path.module}/build/data-quality-${each.key}-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('data-quality-${each.key} Lambda code not yet deployed by CI')\n"
    filename = "${split(".", each.value.handler)[0]}.py"
  }
}

# Explicit log group per function so retention is managed (14 days; matches the other
# control planes). Lambda would otherwise create one with infinite retention on first
# invoke.
resource "aws_cloudwatch_log_group" "functions" {
  for_each = local.data_quality_functions

  name              = local.data_quality_log_group_names[each.key]
  retention_in_days = 14
}

resource "aws_lambda_function" "functions" {
  for_each = local.data_quality_functions

  function_name = local.data_quality_function_names[each.key]
  role          = aws_iam_role.execution.arn
  runtime       = "python3.12"
  handler       = each.value.handler
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # EVERY variable cpcommon/config.py requires must be COMMON to all nine verbs: every verb
  # attaches the cpcommon layer, and any of them may reach any of those values. The config
  # the rule moved the fail-fast from import to FIRST READ, so a verb missing
  # one no longer crashes at COLD START
  # (check-table-absent, RuntimeError COGNITO_USER_POOL_ID unset) — it fails on whichever
  # branch reads it, which is narrower and no less broken. The per-verb map
  # (local.data_quality_verb_env) is reserved for OPTIONAL action env only.
  # NOTIFICATIONS_QUEUE_URL stays optional by design (emit is a no-op when unset).
  #
  # ATHENA_WORKGROUP is the SHARED portal workgroup (var.athena_workgroup) — the same one
  # table-builder/table-share use. This plane originally had its own workgroup to
  # escape the portal workgroup's 10 GiB scan cutoff, but Athena ties Lake Formation to the
  # workgroup: a dedicated one fails LF's Create/Describe checks even for an LF-admin role
  # (measured live). The cutoff tradeoff is documented in the architecture doc — a
  # data-quality check over a source larger than the cutoff fails until it is raised.
  environment {
    variables = merge(
      {
        USER_SPACE_BUCKET       = var.user_space_bucket_name
        SHARED_SPACE_BUCKET     = var.shared_space_bucket_name
        ADMIN_BUCKET            = var.admin_bucket_name
        COGNITO_USER_POOL_ID    = var.user_pool_id
        COGNITO_APP_CLIENT_ID   = var.app_client_id
        ATHENA_WORKGROUP        = var.athena_workgroup
        NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
        # Optional by construction — that is what makes a
        # partial rollout safe: a function that somehow misses it logs to stdout instead
        # of failing at import, which for a shared layer means at COLD START.
        LOGS_QUEUE_URL = var.logs_queue_url
        ENV_NAME       = var.environment
      },
      lookup(local.data_quality_verb_env, each.key, {}),
    )
  }

  # Bootstrap with the placeholder; CI replaces code + attaches the layers.
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
