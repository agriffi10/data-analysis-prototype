# ── The API function ──────────────────────────────────────────────────────────
# One function serves every route.
#
# NOT IN THE VPC, deliberately — after the provider swap the token-verification host is a
# third party with no AWS endpoint at all, so a function in those subnets would stop
# verifying with no code change to blame. README.md.

locals {
  function_name = "${var.project_name}-${var.environment}-api"
}

resource "aws_iam_role" "api" {
  name               = "${local.function_name}-role"
  assume_role_policy = file("${path.module}/policies/api-trust-policy.json")
}

# INLINE, not managed-plus-attachment: the deploy role holds PutRolePolicy and neither
# AttachRolePolicy nor a usable CreatePolicy, so the managed shape is refused at apply.
resource "aws_iam_role_policy" "api" {
  name = "${local.function_name}-policy"
  role = aws_iam_role.api.id

  policy = templatefile("${path.module}/policies/api-execution-policy.json.tftpl", {
    log_group_arn   = module.api.log_group_arn
    logs_queue_arn  = var.logs_queue_arn
    portal_role_arn = var.portal_role_arn

    # The membership index the identity layer reads before a caller's credentials exist. Built
    # here from the bucket name the environment already carries, so there is no second wiring
    # site and no root change.
    admin_bucket_arn = "arn:aws:s3:::${var.admin_bucket}"

    # Exactly the eight request queues. The browser's grants come off in the same change, so at
    # no point are there two writers with nothing asserting it.
    request_queue_arns_json = jsonencode(var.request_queue_arns)
  })
}

module "api" {
  source = "../docker-lambda"

  function_name        = local.function_name
  role_arn             = aws_iam_role.api.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["handler.handler"]

  # One second UNDER the integration's 30s, so the function gives up first and the caller
  # gets its error rather than a 504 over a still-billing invocation.
  timeout_seconds = 29
  memory_mb       = 256

  environment = merge({
    ADMIN_BUCKET        = var.admin_bucket
    USER_SPACE_BUCKET   = var.user_space_bucket
    SHARED_SPACE_BUCKET = var.shared_space_bucket
    ATHENA_WORKGROUP    = var.athena_workgroup
    LOGS_QUEUE_URL      = var.logs_queue_url
    ENV_NAME            = var.environment

    # The eight FIFO request queues. Required with no default and read at first use, so a
    # missing one is a fault this function reports rather than a send that goes nowhere — the
    # browser's own version fell back to an empty string and silently digested the wrong group.
    SHARED_SPACE_QUEUE_URL  = var.shared_space_queue_url
    NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
    TABLE_BUILD_QUEUE_URL   = var.table_build_queue_url
    TABLE_SHARE_QUEUE_URL   = var.table_share_queue_url
    DATA_QUALITY_QUEUE_URL  = var.data_quality_queue_url
    FILE_SEND_QUEUE_URL     = var.file_send_queue_url
    ARCHIVE_QUEUE_URL       = var.archive_queue_url
    FILE_OPS_QUEUE_URL      = var.file_ops_queue_url
    FEEDBACK_QUEUE_URL      = var.feedback_queue_url

    # The identity layer. Same role the Identity Pool vends for, and the same variables that
    # size its tag map — so the two key sets cannot drift by transcription.
    PORTAL_ROLE_ARN        = var.portal_role_arn
    PRINCIPAL_TAG_KEY      = var.principal_tag_key
    MAX_SHARED_MEMBERSHIPS = tostring(var.max_shared_memberships)

    # The provider block: five fields, and the verifier reads nothing else about who issues
    # its tokens. Computed at root, so there is exactly one wiring site. README.md.
    OIDC_ISSUER          = var.oidc_issuer
    OIDC_AUDIENCE        = var.oidc_audience
    OIDC_JWKS_URI        = var.oidc_jwks_uri
    OIDC_USERNAME_CLAIM  = var.oidc_username_claim
    OIDC_REQUIRED_CLAIMS = var.oidc_required_claims
  })

  # The execution policy is NOT in this list, and cannot be: it renders this module's own
  # log-group ARN, so depending on it here is a cycle. See README.md.
}
