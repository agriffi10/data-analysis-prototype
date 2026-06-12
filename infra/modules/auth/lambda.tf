# ── Pre-Signup Validation Lambda (SPEC-012) ──────────────────────────────────
# A Cognito pre-signup trigger that enforces the username rule server-side at
# registration (^[a-zA-Z0-9._@-]{3,64}$). The username becomes the user's S3
# prefix and `username` principal tag, so an unsafe username must never be
# created.
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
    log_group_arn = aws_cloudwatch_log_group.pre_signup.arn
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

  lifecycle {
    # CI owns the code — never revert it on apply.
    ignore_changes = [filename, source_code_hash]
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
