# ── The verb Lambdas ─────────────────────────────────────────────────────────
# validate-authorize plus one single-task verb per action, all running under the shared
# ORCHESTRATOR role, each a call to the fleet's one container module. CI owns which image they
# run. ../../info/control-plane-shape.md.

module "functions" {
  source   = "../docker-lambda"
  for_each = local.shared_space_functions

  function_name        = local.shared_space_function_names[each.key]
  role_arn             = aws_iam_role.orchestrator.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = [each.value]

  # A verb touches one space and 60s is generous for that. The one-shot backfill walks EVERY
  # registry record instead, and it has no resume marker — each run restarts from the first
  # key — so a timeout is not a partial pass it can continue from but a run that made no
  # progress. Its ceiling is sized to the whole walk rather than to one space.
  timeout_seconds = lookup(local.shared_space_function_timeouts, each.key, 60)

  # 128 DECLARED rather than inherited. These verbs previously set no memory at all and ran on
  # the provider's default, which is invisible in a plan and shows up only as a production OOM;
  # modules/data-quality sets both explicitly and records this as the precedent it fixes.
  memory_mb = 128

  # Full env on every function. The validate Lambda verifies the caller's token against the
  # pool for member lookups; the verbs trust the validated actor.
  environment = merge({
    COGNITO_USER_POOL_ID   = var.user_pool_id
    ADMIN_BUCKET           = var.athena_admin_bucket_name
    SHARED_SPACE_BUCKET    = var.shared_space_bucket_name
    USER_SPACE_BUCKET      = var.user_space_bucket_name
    PORTAL_ROLE_ARN        = local.portal_role_arn
    MAX_SHARED_MEMBERSHIPS = tostring(var.max_shared_memberships)
    # Deliberately NOT mirrored by a config._require: a verb that loses this must log to
    # stdout and keep working, never crash the plane at cold start.
    NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
    # Deliberately NOT mirrored by a config._require: a verb that loses this must
    # log to stdout and keep working, never crash the plane at cold start.
    LOGS_QUEUE_URL = var.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
    # NOT read by any verb here — set because cpcommon's config requires it, and it LANDED
    # AND APPLIED BEFORE the code that imports cpcommon deployed, so no function could reach
    # that import with an environment it could not satisfy.
    ATHENA_WORKGROUP = var.athena_workgroup
    # The operator boundary's one input: the reader role's unique ID, which is the half of the
    # SQS SenderId before the colon. Read LAZILY by the domain config rather than through
    # `require`, and that is the whole reason it can land in the same push as the code that
    # reads it — Deploy Infrastructure and Deploy Lambdas race, so an import-time requirement
    # would fail EVERY verb on this plane at cold start for the length of that window. Unset
    # refuses an operator message and is invisible to every UI request, which is the safe
    # direction.
    SHARED_SPACE_TRANSFER_READER_ROLE_ID = aws_iam_role.transfer_reader.unique_id
  })

  depends_on = [
    aws_iam_role_policy.orchestrator,
    time_sleep.wait_for_deploy_policy,
  ]
}

# ── The operator's transfer reader ────────────────────────────────────────────
# Deliberately NOT a row in local.shared_space_functions. That map's for_each hard-codes the
# orchestrator role and one shared environment block, and the whole of this plane's operator
# boundary is that a message declaring `origin: operator` is accepted only when the SenderId SQS
# stamped on it names THIS role. A reader running as the orchestrator would make that comparison
# admit every verb on the plane — and it would do so invisibly, because a test supplies the
# SenderId itself and would stay green.
#
# The domain code's config requires PORTAL_ROLE_ARN at IMPORT and this function has no use for it,
# so the reader must not import it. That was a layer choice before the fleet was containerised and
# is now a property of what the module imports — the image carries everything, so the fence is the
# import graph rather than an attachment.

module "transfer_reader" {
  source = "../docker-lambda"

  function_name        = local.transfer_reader_name
  role_arn             = aws_iam_role.transfer_reader.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["transfer_reader.handler"]

  # The row cap in transfer_reader.py is DERIVED from this number, and a test reads THIS LINE and
  # asserts the two agree. Recomputing the cap from the module's own constants would only agree
  # with itself; what can actually drift is the pair, leaving the function budgeting for an
  # invocation it no longer has.
  timeout_seconds = 60

  # Declared rather than inherited, for the reason the verbs above now are.
  memory_mb = 128

  environment = merge({
    ADMIN_BUCKET = var.athena_admin_bucket_name
    # The one queue this function writes, and the only reason it holds a send at all.
    SHARED_SPACE_REQUESTS_QUEUE_URL = aws_sqs_queue.requests.url
    # Deliberately NOT mirrored by a config._require: a function that loses this must log to
    # stdout and keep working, never crash at cold start.
    LOGS_QUEUE_URL = var.logs_queue_url
    ENV_NAME       = var.environment
  })

  depends_on = [
    aws_iam_role_policy.transfer_reader,
    time_sleep.wait_for_deploy_policy,
  ]
}

resource "aws_cloudwatch_event_rule" "transfer_schedule" {
  name                = local.transfer_schedule_name
  description         = "Sweep the admin bucket's ownership-transfer inbox and enqueue one shared-space request per CSV row."
  schedule_expression = "rate(1 hour)"

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_cloudwatch_event_target" "transfer_schedule" {
  rule = aws_cloudwatch_event_rule.transfer_schedule.name
  arn  = module.transfer_reader.function_arn
}

# Resource-based grant, so the schedule needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "transfer_schedule" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.transfer_reader.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.transfer_schedule.arn
}
