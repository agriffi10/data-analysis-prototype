# ── Pre-Signup Validation Lambda ──────────────────────────────────
# Enforces ^[a-z][a-z0-9_]{2,62}$ server-side. The username becomes an S3 prefix, a principal
# tag and a Glue database name, so an unsafe one must never be created.
#
# Terraform owns the INFRASTRUCTURE; CI owns which image it runs. README.md.

locals {
  pre_signup_function_name = "${var.project_name}-${var.environment}-pre-signup"
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
    log_group_arn  = module.pre_signup.log_group_arn
    logs_queue_arn = var.logs_queue_arn
  })
}

module "pre_signup" {
  source = "../docker-lambda"

  function_name        = local.pre_signup_function_name
  role_arn             = aws_iam_role.pre_signup.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["pre_signup.handler"]

  # 3s and 128 MB, DECLARED rather than inherited: this function has always run on the
  # provider's defaults, and an attribute the configuration does not set is invisible in a
  # plan. The numbers are the ones it has, not new ones — a regex match on a username needs
  # neither more.
  timeout_seconds = 3
  memory_mb       = 128

  # NONE of cpcommon.config's six required variables is set here, DELIBERATELY: this
  # function imports only `observability`, which never reaches `config`. The guard is a
  # source scan plus an import probe (test_layer_import_safety.py), not a crash. README.md.
  environment = merge({
    LOGS_QUEUE_URL = var.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  })

  # The logs policy is NOT in this list, and cannot be: it renders this module's own log-group
  # ARN, so depending on it here is a cycle. ../docker-lambda/README.md.
  depends_on = [time_sleep.wait_for_lambda_perms]
}

# Cognito invokes through a resource-based permission, not a passed role.
resource "aws_lambda_permission" "cognito_invoke" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.pre_signup.function_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.portal.arn
}

# ── Post-Confirmation Provisioning Lambda ─────────────────────────
# Creates the user's Glue database (named exactly as the username) and LF-grants the portal
# role on it. Unlike pre-signup, this one calls Glue and Lake Formation.

locals {
  post_confirmation_function_name = "${var.project_name}-${var.environment}-post-confirmation"
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
    log_group_arn  = module.post_confirmation.log_group_arn
    logs_queue_arn = var.logs_queue_arn
  })
}

module "post_confirmation" {
  source = "../docker-lambda"

  function_name        = local.post_confirmation_function_name
  role_arn             = aws_iam_role.post_confirmation.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["post_confirmation.handler"]

  # Declared rather than inherited, for the reason pre-signup's are. Same numbers it has run
  # on since it was written.
  timeout_seconds = 3
  memory_mb       = 128

  # The portal role the LF grant targets, plus the logs queue. No cpcommon.config variable
  # joins them — see pre-signup.
  environment = merge({
    PORTAL_ROLE_ARN = var.portal_role_arn
    LOGS_QUEUE_URL  = var.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  })

  # The provisioning policy is NOT in this list, and cannot be: it renders this module's own
  # log-group ARN, so depending on it here is a cycle. ../docker-lambda/README.md.
  depends_on = [time_sleep.wait_for_lambda_perms]
}

resource "aws_lambda_permission" "cognito_invoke_post_confirmation" {
  statement_id  = "AllowCognitoInvokePostConfirmation"
  action        = "lambda:InvokeFunction"
  function_name = module.post_confirmation.function_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.portal.arn
}
