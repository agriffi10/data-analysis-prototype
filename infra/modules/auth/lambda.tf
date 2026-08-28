# ── Pre-Signup Validation Lambda ──────────────────────────────────
# Enforces ^[a-z][a-z0-9_]{2,62}$ server-side. The username becomes an S3 prefix, a principal
# tag and a Glue database name, so an unsafe one must never be created.
#
# Terraform owns the INFRASTRUCTURE + a placeholder zip; CI owns the code. README.md.

locals {
  pre_signup_function_name = "${var.project_name}-${var.environment}-pre-signup"
}

# Placeholder so the function is valid at create time; CI deploys the real code.
data "archive_file" "pre_signup_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/pre-signup-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('pre-signup Lambda code not yet deployed by CI')\n"
    filename = "pre_signup.py"
  }
}

# IAM propagation guard. EVERY resource needing a freshly-granted permission must depend on
# it — the exec role for iam:CreateRole, the log group for logs:CreateLogGroup — NOT JUST THE
# FUNCTION, or those calls race the propagation and hit AccessDenied.
resource "time_sleep" "wait_for_lambda_perms" {
  create_duration = "60s"
}

# ── Execution role ────────────────────────────────────────────────────────────
# Logs only — the function makes no AWS API call.
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

# Explicit so retention is managed (Lambda would otherwise default to infinite).
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

  # NONE of cpcommon.config's six required variables is set here, DELIBERATELY: this
  # function imports only `observability`, which never reaches `config`. The guard is a
  # source scan plus an import probe (test_layer_import_safety.py), not a crash. README.md.
  environment {
    variables = {
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    }
  }

  lifecycle {
    # CI owns the code AND the layer attachment. `layers` was once missing here while the
    # code already imported cpcommon — an apply after a deploy stripped it off and re-broke
    # signup.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.pre_signup_logs,
    aws_cloudwatch_log_group.pre_signup,
    time_sleep.wait_for_lambda_perms,
  ]
}

# Cognito invokes through a resource-based permission, not a passed role.
resource "aws_lambda_permission" "cognito_invoke" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.portal.arn
}

# ── Post-Confirmation Provisioning Lambda ─────────────────────────
# Creates the user's Glue database (named exactly as the username) and LF-grants the portal
# role on it. Unlike pre-signup, this one calls Glue and Lake Formation.

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

# Trust is identical to pre-signup; the permissions add Glue and Lake Formation.
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

  # The portal role the LF grant targets, plus the logs queue. No cpcommon.config variable
  # joins them — see pre-signup.
  environment {
    variables = {
      PORTAL_ROLE_ARN = var.portal_role_arn
      LOGS_QUEUE_URL  = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    }
  }

  lifecycle {
    # CI owns the code AND the layer attachment — see pre-signup.
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
