output "github_actions_role_arn" {
  description = "IAM role ARN assumed by the GitHub Actions deployment workflows."
  value       = module.base.github_actions_role_arn
}

output "aws_region" {
  description = "AWS region where resources are deployed."
  value       = var.aws_region
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID. Set VITE_COGNITO_USER_POOL_ID to this value."
  value       = module.auth.user_pool_id
}

output "cognito_user_pool_client_id" {
  description = "Cognito SPA app client ID. Set VITE_COGNITO_USER_POOL_CLIENT_ID to this value."
  value       = module.auth.user_pool_client_id
}

output "cognito_server_client_id" {
  description = "The portal server's confidential app client ID. The deploy ensures its Managed Login branding beside the SPA client's."
  value       = module.auth.server_client_id
}

output "cognito_domain" {
  description = "Cognito Hosted UI domain. Set VITE_COGNITO_DOMAIN to this value."
  value       = module.auth.user_pool_domain

  # The CSP's connect-src allows local.cognito_hosted_ui_domain, but the app
  # actually fetches the domain THIS output names (via VITE_COGNITO_DOMAIN). If
  # the two ever disagree the authorization-code exchange is blocked and sign-in
  # breaks with no failing test anywhere — that outage happened once already
  # (2026-08-04). A precondition is a hard error at plan time; a `check` block
  # would only warn, which is how this class of bug goes unnoticed.
  precondition {
    condition     = module.auth.user_pool_domain == local.cognito_hosted_ui_domain
    error_message = "CSP/Hosted UI drift: connect-src allows ${local.cognito_hosted_ui_domain} but the user pool domain is ${module.auth.user_pool_domain}. Sign-in would be blocked. Reconcile local.cognito_hosted_ui_domain in main.tf with modules/auth."
  }
}

output "s3_user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Set VITE_S3_USER_SPACE_BUCKET to this value."
  value       = module.data.user_space_bucket_name
}

output "lambda_artifacts_bucket_name" {
  description = "Lambda deployment artifacts bucket. It staged a zip per function while the fleet was zip-packaged; nothing writes to it or reads it now that every function runs a container image."
  value       = module.lambda_artifacts.bucket_name
}

output "pre_signup_function_name" {
  description = "Name of the pre-signup validation Lambda. The deploy-lambdas workflow targets this for update-function-code."
  value       = module.auth.pre_signup_function_name
}

output "athena_workgroup_name" {
  description = "Name of the shared Athena workgroup. Read by the API function and the control planes as ATHENA_WORKGROUP; the browser no longer knows it."
  value       = module.analytics.athena_workgroup_name
}

output "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket. Exported for ops; not consumed by the app."
  value       = module.analytics.athena_admin_bucket_name
}

# ── Shared-space foundation ───────────────────────────────────────
output "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Maps to a VITE_* once shared-space file ops land."
  value       = module.shared_space_storage.shared_space_bucket_name
}

output "shared_space_request_queue_url" {
  description = "URL of the FIFO shared-space request queue. The API enqueues control-plane requests here through its one grant."
  value       = module.shared_spaces.queue_url
}

output "shared_space_orchestrator_role_arn" {
  description = "ARN of the privileged shared-space orchestrator role (Step Function + provisioner Lambda). Added as a Lake Formation admin."
  value       = module.shared_spaces.execution_role_arn
}

output "shared_space_state_machine_arn" {
  description = "ARN of the shared-space orchestrator Step Function. Used by the control-plane bring-up checks (docs/testing/owed.md)."
  value       = module.shared_spaces.state_machine_arn
}

# ── Notifications write pipeline ──────────────────────────────────
output "notifications_queue_url" {
  description = "URL of the FIFO notifications request queue (ends in .fifo). The API enqueues markRead/markAllRead here through its one grant."
  value       = module.notifications.queue_url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO notifications request queue — the `sqs:SendMessage` scope for the API and for every trusted producer."
  value       = module.notifications.queue_arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role — the single writer of every user's notifications.json."
  value       = module.notifications.role_arn

  # The writer refuses a `create` whose SenderId names this value, so a wire to the portal role's
  # ARN or name — both validate clean and neither ever matches — deploys a control that silently
  # does nothing. queue-consumer takes a plain environment map and cannot check one key, so the
  # refusal sits here, at the root that wires it, and fails the plan.
  precondition {
    condition     = can(regex("^AROA[A-Z0-9]+$", local.notifications_writer_environment.NOTIFICATIONS_UNTRUSTED_SENDER_ID))
    error_message = "The notifications writer's NOTIFICATIONS_UNTRUSTED_SENDER_ID must be an IAM role unique ID (AROA…) — not the role's name and not its ARN, neither of which SenderId carries."
  }
}

# ── Verification access ────────────────────────────────────
# The three values a live check needs by name. `trail_name` is here for a reason worth
# stating: a trail that is not logging returns an EMPTY result, which reads exactly like a
# `RestoreObject` that never happened — so the negative assertion has to confirm the trail is
# on before it trusts the absence ("did not run is never clean").
output "verification_role_arn" {
  description = "The read-only role a live check assumes for catalog read-backs and the archive audit record."
  value       = module.verification.verification_role_arn
}

output "verification_trail_bucket" {
  description = "Where the archive vault's object-level CloudTrail events land."
  value       = module.verification.trail_bucket_name
}

output "verification_trail_name" {
  description = "The trail itself, so a check can prove it is logging before reading an absence as evidence."
  value       = module.verification.trail_name
}

# ── The container platform's network ──────────────────────────────────────────
# Exported so the acceptance script can assert the S3 gateway endpoint's association set EQUALS
# the private route tables, and that those tables carry no default route. Both are applied-state
# facts: a gateway endpoint associated with the wrong table applies green and does nothing, and a
# pull that succeeded through a route somebody added would otherwise read as proof of the
# endpoints. Neither is checkable from the plan. All three are null while the web tier is off.
output "vpc_id" {
  description = "The VPC the container platform runs in."
  value       = one(module.network[*].vpc_id)
}

output "private_route_table_ids" {
  description = "The route tables the ECS tasks' subnets use. The S3 gateway endpoint's RouteTableIds must equal this set, and none of them may carry a default route."
  value       = one(module.network[*].private_route_table_ids)
}

output "private_subnet_ids" {
  description = "The subnets the ECS tasks run in. No default route reaches the internet from any of them."
  value       = one(module.network[*].private_subnet_ids)
}

output "api_function_name" {
  description = "The API function, for the deploy matrix and for the live checks that read its deployed configuration back."
  value       = module.api.api_function_name
}

output "spa_origin" {
  description = "Origin serving the container SPA. Consumed by the Cognito callback/logout lists, the API's CORS list and the CSP's connect-src."
  value       = local.spa_origin
}

output "api_origin" {
  description = "Origin serving the HTTP API. Named in the CSP's connect-src and in the API's own CORS list."
  value       = local.api_origin
}

output "spa_host" {
  description = "Hostname of the container SPA, without scheme — the ALB alias record and its certificate."
  value       = local.spa_host
}

output "api_host" {
  description = "Hostname of the HTTP API, without scheme — the API Gateway custom domain and its certificate."
  value       = local.api_host
}

output "spa_certificate_arn" {
  description = "Regional ACM certificate for spa_host, validated. Consumed by the HTTPS listener while the web tier is on; ACM renews it only while it is in use (infra/info/web-tier.md)."
  value       = aws_acm_certificate_validation.spa.certificate_arn
}

output "api_certificate_arn" {
  description = "Regional ACM certificate for api_host, validated. Consumed by the API Gateway custom domain."
  value       = aws_acm_certificate_validation.api.certificate_arn
}

# ── The container platform ────────────────────────────────────────────────────
# All four are read by hand during verification: the registry CI pushes the image to, the
# cluster and service to describe, and the load balancer's own name to prove the alias
# record points at THIS balancer rather than at a stale one. The last three are null while the
# web tier is off; the registry outlives the switch.
output "ecr_repository_url" {
  description = "Registry the SPA image is pushed to."
  value       = module.spa_image.repository_url
}

output "ecs_cluster_name" {
  description = "Cluster the SPA service runs in."
  value       = one(module.spa[*].ecs_cluster_name)
}

output "ecs_service_name" {
  description = "The SPA service — describe-services reads its running count and its event log."
  value       = one(module.spa[*].ecs_service_name)
}

output "alb_dns_name" {
  description = "The SPA load balancer's own DNS name, which the spa_host alias record must resolve to."
  value       = one(module.spa[*].alb_dns_name)
}

output "lambda_image_repository_url" {
  description = "The Lambda image's registry URI. CI pushes a commit-sha tag here and points every function at it."
  value       = module.lambda_image.repository_url
}

# ── The fleet's own declaration of its membership ─────────────────────────────
# WHAT THIS REPLACES. `.github/lambda-functions.json` was a hand-maintained list of every Lambda
# that CI sharded over. Terraform already knew, so the list was a second copy that could only ever
# drift; this is the first copy, read directly. It was retired against this output rather than
# before it: while both existed, a test held them equal in both directions.
#
# SHORT NAMES, NOT DEPLOYED NAMES, and the prefix is stripped here rather than in the shell. Every
# consumer — `point-lambda.sh`, the probe table, the `lambdas/<name>/` source directory — speaks
# the short name, and CI rebuilds the deployed one as `${PROJECT_NAME}-${ENVIRONMENT}-${NAME}`.
#
# THE PRECONDITION IS THE WHOLE REASON THIS IS SAFE. `trimprefix` returns the string UNCHANGED when
# the prefix does not match, silently and with no error — so a function named off-convention would
# emit a full name here, CI would prepend the prefix again, and the deploy would wait five minutes
# for `dat-prod-dat-prod-thing` before failing on something that names neither cause. Refusing at
# plan time names it exactly once.
locals {
  lambda_deployed_names = concat(
    module.api.function_names,
    module.archive.function_names,
    module.auth.function_names,
    module.control_plane_dlq_drain.function_names,
    module.data_quality.function_names,
    module.feedback.function_names,
    module.file_ops.function_names,
    module.file_send.function_names,
    module.results_conversion.function_names,
    module.notifications.function_names,
    module.observability_sweep.function_names,
    module.shared_spaces.function_names,
    module.shared_space_transfer_reader.function_names,
    module.table_builder.function_names,
    module.table_share.function_names,
    module.user_directory.function_names,
  )

  lambda_name_prefix = "${var.project_name}-${var.environment}-"
}

output "lambda_function_names" {
  description = "Every Lambda in the fleet, by short name — the fleet declaring its own membership, derived from the module calls that deploy it. Deploy Lambdas reconciles what it pointed against this."
  value       = sort([for name in local.lambda_deployed_names : trimprefix(name, local.lambda_name_prefix)])

  precondition {
    condition = alltrue([
      for name in local.lambda_deployed_names : startswith(name, local.lambda_name_prefix)
    ])
    error_message = "Every Lambda's deployed name must start with ${var.project_name}-${var.environment}- — CI rebuilds it by prepending exactly that, and trimprefix returns a non-matching name unchanged rather than failing. Off-convention names: ${join(", ", [for name in local.lambda_deployed_names : name if !startswith(name, local.lambda_name_prefix)])}."
  }

  precondition {
    condition     = length(distinct(local.lambda_deployed_names)) == length(local.lambda_deployed_names)
    error_message = "Two modules declare the same Lambda name. A set comparison downstream would collapse the duplicate and agree with a fleet one function short."
  }
}
