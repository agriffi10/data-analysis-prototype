# ── Pre-Signup Validation Lambda ──────────────────────────────────
# A Cognito pre-signup trigger that enforces the username rule server-side at
# registration (^[a-z][a-z0-9_]{2,62}$ — catalog-safe per SPEC-033). The username
# becomes the user's S3 prefix, `username` principal tag, and Glue database name, so
# an unsafe username must never be created.
#
# Code ownership split: Terraform owns the function INFRASTRUCTURE (role, runtime
# config, log group, pool trigger) and bootstraps it with a placeholder zip.
# GitHub Actions (.github/workflows/deploy-lambdas.yml) owns the actual CODE —
# it builds the Python package from /lambdas/pre-signup, uploads it to the lambda
# artifacts bucket, and calls update-function-code. `ignore_changes` on the code
# attributes keeps `tofu apply` from reverting CI's deployed code.

locals {
  pre_signup_function_name = "${var.project_name}-${var.environment}-pre-signup"
}

# Placeholder package so the function is valid at create time. The real code is
# deployed by CI; this stub only ever runs if a deploy has not happened yet.
data "archive_file" "pre_signup_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/pre-signup-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('pre-signup Lambda code not yet deployed by CI')\n"
    filename = "pre_signup.py"
  }
}

# IAM propagation guard: this spec grants the deploy role lambda/iam/logs perms
# (modules/base) in the same apply that then creates these resources. The
# module-level depends_on (auth -> base) orders the calls so the deploy policy is
# written first, but IAM is eventually consistent; this fresh time_sleep (created
# this apply) absorbs the propagation window — same rationale as the identity-pool
# guard. EVERY resource that needs a freshly-granted permission must depend on it
# (the exec role -> iam:CreateRole, the log group -> logs:CreateLogGroup) — not
# just the function — or those calls race the propagation and hit AccessDenied.
resource "time_sleep" "wait_for_lambda_perms" {
  create_duration = "60s"
}

# ── Execution role ────────────────────────────────────────────────────────────
# Logs only — the function makes no AWS API calls. Trust + permissions are JSON
# template files under policies/, rendered with templatefile() (same convention
# as the base and data modules).
resource "aws_iam_role" "pre_signup" {
  name               = "${local.pre_signup_function_name}-role"
  assume_role_policy = templatefile("${path.module}/policies/pre-signup-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_lambda_perms]
}

resource "aws_iam_role_policy" "pre_signup_logs" {
  name = "logs"
  role = aws_iam_role.pre_signup.id

  policy = templatefile("${path.module}/policies/pre-signup-permissions.json.tftpl", {
    log_group_arn  = aws_cloudwatch_log_group.pre_signup.arn
    logs_queue_arn = var.logs_queue_arn
  })
}

# Explicit log group so retention is managed (Lambda would otherwise create one
# with infinite retention on first invoke). 14-day retention (FR-002).
resource "aws_cloudwatch_log_group" "pre_signup" {
  name              = "/aws/lambda/${local.pre_signup_function_name}"
  retention_in_days = 14

  depends_on = [time_sleep.wait_for_lambda_perms]
}

resource "aws_lambda_function" "pre_signup" {
  function_name = local.pre_signup_function_name
  role          = aws_iam_role.pre_signup.arn
  runtime       = "python3.12"
  handler       = "pre_signup.handler"

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.pre_signup_placeholder.output_path
  source_code_hash = data.archive_file.pre_signup_placeholder.output_base64sha256

  # SPEC-137 FR-005. Optional BY CONSTRUCTION on the Lambda side — cpcommon.observability
  # reads it with os.environ.get and never config._require — so a trigger deployed without
  # it logs to stdout instead of failing at cold start. Set here so it is set in practice,
  # and the trigger's narrative lands in logs/service=auth/ with post-confirmation's.
  #
  # NONE of the six variables cpcommon/config.py requires is set here, deliberately: this
  # function imports only `observability`, which never reaches `config`. Since SPEC-156 that
  # config resolves on first ACCESS rather than at import, so the guard is no longer "does the
  # import crash" but "does any branch read one" — test_layer_import_safety.py scans
  # this function's whole source for a cpcommon import as well as running it.
  environment {
    variables = {
      LOGS_QUEUE_URL = var.logs_queue_url
      # `env` shipped empty on every record. Same source of truth as the
      # feature-flag document's `environments` keys (`var.environment`, default "prod").
      ENV_NAME = var.environment
    }
  }

  lifecycle {
    # CI owns the code AND the cpcommon layer attachment — never revert either on apply.
    # `layers` was missing here while the code already imported cpcommon, so an apply
    # landing after a deploy would have stripped the layer straight back off and
    # re-broken signup.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.pre_signup_logs,
    aws_cloudwatch_log_group.pre_signup,
    time_sleep.wait_for_lambda_perms,
  ]
}

# Allow the User Pool to invoke the trigger. Cognito uses a resource-based
# permission (not a passed role), scoped to this pool's ARN.
resource "aws_lambda_permission" "cognito_invoke" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.portal.arn
}

# ── Post-Confirmation Provisioning Lambda ─────────────────────────
# A Cognito post-confirmation trigger that, on sign-up confirmation, creates the
# user's Glue database (named exactly as the username) and Lake Formation-grants the
# shared portal role on it. Same code-ownership split as pre-signup: Terraform owns
# the infrastructure + a placeholder; deploy-lambdas.yml owns the Python code.
#
# Unlike pre-signup (logs only), this function calls Glue + Lake Formation, so its
# exec role carries those permissions (policies/post-confirmation-permissions.tftpl).
# It also targets the shared portal role in the LF grant — passed in via env var.

locals {
  post_confirmation_function_name = "${var.project_name}-${var.environment}-post-confirmation"
}

data "archive_file" "post_confirmation_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/post-confirmation-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('post-confirmation Lambda code not yet deployed by CI')\n"
    filename = "post_confirmation.py"
  }
}

# Execution role. Trust is identical to pre-signup; the permission policy adds Glue
# (create the user's database) + Lake Formation (grant the portal role) on top of
# logs. Gated on the same propagation guard as everything else this apply creates.
resource "aws_iam_role" "post_confirmation" {
  name               = "${local.post_confirmation_function_name}-role"
  assume_role_policy = templatefile("${path.module}/policies/post-confirmation-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_lambda_perms]
}

resource "aws_iam_role_policy" "post_confirmation" {
  name = "provisioning"
  role = aws_iam_role.post_confirmation.id

  policy = templatefile("${path.module}/policies/post-confirmation-permissions.json.tftpl", {
    aws_region     = var.aws_region
    account_id     = var.account_id
    log_group_arn  = aws_cloudwatch_log_group.post_confirmation.arn
    logs_queue_arn = var.logs_queue_arn
  })
}

resource "aws_cloudwatch_log_group" "post_confirmation" {
  name              = "/aws/lambda/${local.post_confirmation_function_name}"
  retention_in_days = 14

  depends_on = [time_sleep.wait_for_lambda_perms]
}

resource "aws_lambda_function" "post_confirmation" {
  function_name = local.post_confirmation_function_name
  role          = aws_iam_role.post_confirmation.arn
  runtime       = "python3.12"
  handler       = "post_confirmation.handler"

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.post_confirmation_placeholder.output_path
  source_code_hash = data.archive_file.post_confirmation_placeholder.output_base64sha256

  # The shared portal role the LF grant targets (SPEC-033 FR-002/FR-003), plus the logs
  # queue (SPEC-137 FR-005 — see the pre-signup function for why no config variable
  # joins them).
  environment {
    variables = {
      PORTAL_ROLE_ARN = var.portal_role_arn
      LOGS_QUEUE_URL  = var.logs_queue_url
      # `env` shipped empty on every record. Same source of truth as the
      # feature-flag document's `environments` keys (`var.environment`, default "prod").
      ENV_NAME = var.environment
    }
  }

  lifecycle {
    # CI owns the code AND the cpcommon layer attachment — never revert either on apply
    # (see pre-signup).
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.post_confirmation,
    aws_cloudwatch_log_group.post_confirmation,
    time_sleep.wait_for_lambda_perms,
  ]
}

resource "aws_lambda_permission" "cognito_invoke_post_confirmation" {
  statement_id  = "AllowCognitoInvokePostConfirmation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.post_confirmation.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.portal.arn
}
