# The shared-spaces control plane: one call to the control-plane module, and the two things only
# this plane has — Bucket 2 with its catalog registration, and the operator's request reader.
# Its definition, policies and reasoning are in planes/shared-spaces/.
#
# FIFO with a SINGLE CONSTANT MessageGroupId, so requests are STARTED one at a time, in order.
# ⚠ THAT IS NOT SERIAL EXECUTION: the Pipe starts the machine FIRE_AND_FORGET, so runs overlap.
#
# DUPLICATE-NAME SAFETY DOES NOT DEPEND ON THE QUEUE — content dedup only collapses
# byte-identical bodies inside a 5-minute window, and the group orders only the starts. THE
# REGISTRY'S CONDITIONAL PUT (If-None-Match) IS THE WHOLE GUARD. README.md.
#
# Standard, routing by action: Validate → Choice(action) → exactly one verb. A Choice-routed
# fan-out rather than a pipeline. It runs under the shared ORCHESTRATOR role, which is also the
# exec role for every Lambda it invokes. README.md.

locals {
  # A verb touches one space, and 60s is generous for that. The one-shot backfill walks EVERY
  # registry record instead and has no resume marker, so a timeout is a run that made no progress
  # rather than a partial pass: its ceiling is Lambda's own, sized to the whole walk (one
  # GetObject per record, ~18,000 records at a conservative 50ms each).
  #
  # 128 MB is DECLARED rather than inherited: the provider's default is invisible in a plan and
  # shows up only as a production OOM.
  shared_space_functions = {
    "validate"               = { handler = "validate.handler", timeout = 60, memory = 128 }
    "create"                 = { handler = "create_space.handler", timeout = 60, memory = 128 }
    "add-members"            = { handler = "add_members.handler", timeout = 60, memory = 128 }
    "remove-members"         = { handler = "remove_members.handler", timeout = 60, memory = 128 }
    "leave"                  = { handler = "leave.handler", timeout = 60, memory = 128 }
    "delete"                 = { handler = "delete_space.handler", timeout = 60, memory = 128 }
    "forget"                 = { handler = "forget_space.handler", timeout = 60, memory = 128 }
    "acknowledge-membership" = { handler = "acknowledge_membership.handler", timeout = 60, memory = 128 }
    "transfer-ownership"     = { handler = "transfer_ownership.handler", timeout = 60, memory = 128 }
    "notify-failure"         = { handler = "ss_notify_failure.handler", timeout = 60, memory = 128 }
    "backfill-ever-active"   = { handler = "backfill_ever_active.handler", timeout = 900, memory = 128 }
  }

  shared_space_queue_arn = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-${var.environment}-shared-space-requests.fifo"
}

module "shared_spaces" {
  source = "./modules/control-plane"

  name         = "shared-space"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.shared_space_functions

  # Every function gets the full environment. The validate verb checks the caller against the
  # pool for member lookups; the verbs trust the validated actor.
  environment_variables = {
    COGNITO_USER_POOL_ID   = module.auth.user_pool_id
    ADMIN_BUCKET           = local.athena_admin_bucket_name
    SHARED_SPACE_BUCKET    = local.shared_space_bucket_name
    USER_SPACE_BUCKET      = local.user_space_bucket_name
    PORTAL_ROLE_ARN        = local.portal_role_arn
    MAX_SHARED_MEMBERSHIPS = tostring(var.max_shared_memberships)
    # Deliberately NOT mirrored by a config._require: a verb that loses either queue must log to
    # stdout and keep working, never crash the plane at cold start.
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    LOGS_QUEUE_URL          = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
    # Read by no verb here; set because cpcommon's config requires it.
    ATHENA_WORKGROUP = local.athena_workgroup_name
    # The operator boundary's one input: the reader role's unique ID, the half of the SQS
    # SenderId before the colon. Read LAZILY by the domain config, so an unset one refuses an
    # operator message and is invisible to every UI request, which is the safe direction.
    SHARED_SPACE_TRANSFER_READER_ROLE_ID = module.shared_space_transfer_reader.role_unique_id
  }

  content_based_deduplication     = true
  dlq_content_based_deduplication = true
  dlq_max_receive_count           = 3

  definition_template = "${path.root}/planes/shared-spaces/state-machine.asl.json.tftpl"

  # The orchestrator role stays the verbs' role BY NAME: the Lake Formation admin list and the
  # user-space bucket's allowlist name it, and so does its inline policy's name.
  execution_role_name   = "${var.project_name}-${var.environment}-shared-space-orchestrator-role"
  execution_policy_name = "orchestrator"
  execution_policy = templatefile("${path.root}/planes/shared-spaces/execution.json.tftpl", {
    aws_region              = var.aws_region
    account_id              = data.aws_caller_identity.current.account_id
    shared_space_bucket_arn = local.shared_space_bucket_arn
    admin_bucket_arn        = local.athena_admin_bucket_arn
    user_space_bucket_arn   = "arn:aws:s3:::${local.user_space_bucket_name}"
    lambda_log_groups_arn   = "${local.control_plane_arn_prefix.lambda_logs}-shared-space-*:*"
    notifications_queue_arn = local.notifications_queue_arn
    logs_queue_arn          = module.observability.logs_queue_arn
  })
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base, module.data, module.shared_space_storage]
}

# Bucket 2, its Lake Formation registration, and the portal role's grant on it.
module "shared_space_storage" {
  source = "./modules/shared-space-storage"

  project_name             = var.project_name
  environment              = var.environment
  aws_region               = var.aws_region
  account_id               = data.aws_caller_identity.current.account_id
  shared_space_bucket_name = local.shared_space_bucket_name
  spa_origin               = local.spa_origin
  max_shared_memberships   = var.max_shared_memberships
  portal_role_name         = local.portal_role_name

  control_plane_execution_role_arns = [
    local.table_builder_execution_role_arn,
    local.table_share_execution_role_arn,
    local.data_quality_execution_role_arn,
  ]

  depends_on = [module.base, module.data]
}

# The operator's request reader, a second producer of the plane's queue, admitted by its role's
# SenderId. Deliberately NOT one of the plane's functions: a reader running as the orchestrator
# would make that comparison admit every verb on the plane, invisibly, because a test supplies
# the SenderId itself. And the domain config requires PORTAL_ROLE_ARN at import, so the reader
# must not import it — the fence is the import graph.
module "shared_space_transfer_reader" {
  source = "./modules/scheduled-function"

  function_name = "${var.project_name}-${var.environment}-shared-space-transfer-reader"
  role_name     = "${var.project_name}-${var.environment}-shared-space-transfer-reader-role"
  role_policies = {
    "transfer-reader" = templatefile("${path.root}/planes/shared-spaces/transfer-reader.json.tftpl", {
      admin_bucket_arn   = local.athena_admin_bucket_arn
      requests_queue_arn = local.shared_space_queue_arn
      logs_queue_arn     = module.observability.logs_queue_arn
      log_group_arn      = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-shared-space-transfer-reader:*"
    })
  }

  handler         = "transfer_reader.handler"
  timeout_seconds = 60
  memory_mb       = 128
  environment_variables = {
    ADMIN_BUCKET                    = local.athena_admin_bucket_name
    SHARED_SPACE_REQUESTS_QUEUE_URL = module.shared_spaces.queue_url
    LOGS_QUEUE_URL                  = module.observability.logs_queue_url
    ENV_NAME                        = var.environment
  }

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  rule_name               = "${var.project_name}-${var.environment}-shared-space-transfer-reader-schedule"
  rule_description        = "Sweep the admin bucket's operator-request inbox and enqueue one shared-space request per coalesced (space, action) group."
  schedule_expression     = "rate(1 hour)"
  permission_statement_id = "AllowEventBridgeSchedule"

  depends_on = [module.base, module.shared_space_storage]
}
