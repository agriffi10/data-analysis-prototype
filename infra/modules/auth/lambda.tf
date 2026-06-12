# ── Pre-Signup Validation Lambda (SPEC-012) ──────────────────────────────────
# A Cognito pre-signup trigger that enforces the username rule server-side at
# registration (^[a-zA-Z0-9._@-]{3,64}$). The username becomes the user's S3
# prefix and `username` principal tag, so an unsafe username must never be
# created. Code lives in lambda/pre-signup/index.mjs; rule rationale is there.

locals {
  pre_signup_function_name = "${var.project_name}-${var.environment}-pre-signup"
}

# Package the handler with archive_file — no build step (pure ESM, no deps).
data "archive_file" "pre_signup" {
  type        = "zip"
  source_dir  = "${path.module}/lambda/pre-signup"
  output_path = "${path.module}/lambda/pre-signup.zip"
}

# ── Execution role ────────────────────────────────────────────────────────────
# Logs only — the function makes no AWS API calls.
resource "aws_iam_role" "pre_signup" {
  name = "${local.pre_signup_function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "pre_signup_logs" {
  name = "logs"
  role = aws_iam_role.pre_signup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.pre_signup.arn}:*"
      }
    ]
  })
}

# Explicit log group so retention is managed (Lambda would otherwise create one
# with infinite retention on first invoke). 14-day retention (FR-002).
resource "aws_cloudwatch_log_group" "pre_signup" {
  name              = "/aws/lambda/${local.pre_signup_function_name}"
  retention_in_days = 14
}

# IAM propagation guard: this spec grants the deploy role lambda/iam/logs perms
# (modules/base) in the same apply that then creates these resources. The
# module-level depends_on (auth -> base) orders the calls, but IAM is eventually
# consistent; this fresh time_sleep (created this apply) absorbs the propagation
# window — same rationale as the identity-pool guard.
resource "time_sleep" "wait_for_lambda_perms" {
  create_duration = "30s"
}

resource "aws_lambda_function" "pre_signup" {
  function_name = local.pre_signup_function_name
  role          = aws_iam_role.pre_signup.arn
  runtime       = "nodejs20.x"
  handler       = "index.handler"

  filename         = data.archive_file.pre_signup.output_path
  source_code_hash = data.archive_file.pre_signup.output_base64sha256

  # Ensure the log group exists first so Lambda writes into the retention-managed
  # group rather than auto-creating an unmanaged one.
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
