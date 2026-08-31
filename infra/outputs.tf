output "s3_static_assets_bucket_name" {
  description = "Name of the S3 bucket hosting the built SPA. Used by the deploy-app workflow."
  value       = module.app.static_assets_bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by the deployment workflow to create cache invalidations."
  value       = module.app.cloudfront_distribution_id
}

output "cloudfront_domain" {
  description = "CloudFront domain for the portal. Set VITE_APP_URL to this value after the first deploy."
  value       = "https://${module.app.cloudfront_domain_name}"
}

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
  description = "Lambda deployment artifacts bucket. The deploy-lambdas workflow uploads packages here before update-function-code."
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
  value       = module.shared_spaces.shared_space_bucket_name
}

output "shared_space_request_queue_url" {
  description = "URL of the FIFO shared-space request queue. The API enqueues control-plane requests here through its one grant."
  value       = module.shared_spaces.request_queue_url
}

output "shared_space_orchestrator_role_arn" {
  description = "ARN of the privileged shared-space orchestrator role (Step Function + provisioner Lambda). Added as a Lake Formation admin."
  value       = module.shared_spaces.orchestrator_role_arn
}

output "shared_space_state_machine_arn" {
  description = "ARN of the shared-space orchestrator Step Function. Used by the control-plane bring-up checks (docs/testing/owed.md)."
  value       = module.shared_spaces.state_machine_arn
}

# ── Notifications write pipeline ──────────────────────────────────
output "notifications_queue_url" {
  description = "URL of the FIFO notifications request queue (ends in .fifo). The API enqueues markRead/markAllRead here through its one grant."
  value       = module.notifications.notifications_queue_url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO notifications request queue — the `sqs:SendMessage` scope for the API and for every trusted producer."
  value       = module.notifications.notifications_queue_arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role — the single writer of every user's notifications.json."
  value       = module.notifications.notifications_writer_role_arn
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
# endpoints. Neither is checkable from the plan.
output "vpc_id" {
  description = "The VPC the container platform runs in."
  value       = module.network.vpc_id
}

output "private_route_table_ids" {
  description = "The route tables the ECS tasks' subnets use. The S3 gateway endpoint's RouteTableIds must equal this set, and none of them may carry a default route."
  value       = module.network.private_route_table_ids
}

output "private_subnet_ids" {
  description = "The subnets the ECS tasks run in. No default route reaches the internet from any of them."
  value       = module.network.private_subnet_ids
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
  description = "Regional ACM certificate for spa_host, validated. Consumed by the SPA's HTTPS listener."
  value       = aws_acm_certificate_validation.spa.certificate_arn
}

output "api_certificate_arn" {
  description = "Regional ACM certificate for api_host, validated. Consumed by the API Gateway custom domain."
  value       = aws_acm_certificate_validation.api.certificate_arn
}

# ── The container platform ────────────────────────────────────────────────────
# All four are read by hand during verification: the registry CI pushes the image to, the
# cluster and service to describe, and the load balancer's own name to prove the alias
# record points at THIS balancer rather than at a stale one.
output "ecr_repository_url" {
  description = "Registry the SPA image is pushed to."
  value       = module.spa.ecr_repository_url
}

output "ecs_cluster_name" {
  description = "Cluster the SPA service runs in."
  value       = module.spa.ecs_cluster_name
}

output "ecs_service_name" {
  description = "The SPA service — describe-services reads its running count and its event log."
  value       = module.spa.ecs_service_name
}

output "alb_dns_name" {
  description = "The SPA load balancer's own DNS name, which the spa_host alias record must resolve to."
  value       = module.spa.alb_dns_name
}
