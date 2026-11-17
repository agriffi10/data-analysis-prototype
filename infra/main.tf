# ── Module composition ────────────────────────────────────────────────────────
# Infrastructure is grouped into bounded-context modules:
#   base — foundation: GitHub Actions OIDC provider and deployment role
# auth — Cognito: User Pool, SPA app client, Hosted UI domain
# data — user-space S3 bucket (Bucket 1) + CORS/encryption
# Future contexts get their own modules rather than growing resource-type files.

# The user-space bucket name is computed once here and shared two ways: the data
# module creates the bucket with it, and the base module's deploy policy is scoped
# to its ARN — passed as a constructed string to avoid a data→base dependency
# cycle (the deploy role must be able to manage a bucket the data module creates).
data "aws_caller_identity" "current" {}

# The load-balancing service's own account in this region — one of the two principals the SPA's
# access-log bucket policy grants. Read here rather than in the module, for the same reason as the
# availability zones below: a data source inside a module carrying depends_on is deferred to apply.
data "aws_elb_service_account" "main" {}

# Read HERE, not inside modules/network, and the reason is the module's own depends_on.
# A module-level depends_on defers every data source in that module whenever anything it
# depends on has a pending change — and the subnets are a for_each over a local derived
# from these names, where a deferred read is not "(known after apply)" but a hard
# "Invalid for_each argument". So any change to module.base, however small, broke the
# whole network's plan. At root there is no depends_on to defer it.
#
# The filter is load-bearing and its absence is not: opt-in AZs (Local Zones among them)
# sort BEFORE ordinary ones — us-east-1-atl-2a < us-east-1a — so an unfiltered list
# silently rehomes both subnet pairs. Do NOT add `state = "available"`: that makes
# membership depend on AZ health, which recreates the network during an AZ event.
data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  user_space_bucket_name = var.user_space_bucket_name != "" ? var.user_space_bucket_name : "${var.project_name}-prod-user-space"

  # Portal role name computed once and shared like the bucket name: the data
  # module creates the role, and base's deploy policy is scoped to its ARN
  # (constructed string -> no data->base cycle).
  portal_role_name = var.portal_role_name != "" ? var.portal_role_name : "${var.project_name}-portal-user-role"
  portal_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.portal_role_name}"

  # Deploy role ARN, constructed the same cycle-free way (base creates the role as
  # "${project_name}-deploy-role"). Passed to the data module so the user-space
  # bucket policy can EXCLUDE the deploy role from its data-access Deny — without
  # this the deploy role can't HeadBucket (s3:ListBucket), tofu refresh sees the
  # bucket as "deleted", and every infra plan proposes a destructive recreate.
  deploy_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-deploy-role"

  # Lambda artifacts bucket name computed once and shared the same cycle-free way:
  # the lambda-artifacts module creates the bucket, and base's deploy policy is
  # scoped to its ARN (constructed string -> no lambda-artifacts->base cycle).
  lambda_artifacts_bucket_name = "${var.project_name}-lambda-artifacts-${data.aws_caller_identity.current.account_id}"
  lambda_artifacts_bucket_arn  = "arn:aws:s3:::${local.lambda_artifacts_bucket_name}"

  # Analytics names computed once: the analytics module creates the
  # workgroup + admin bucket, and base's deploy policy is scoped to the admin
  # bucket ARN (constructed string -> no analytics->base cycle). Overridable via
  # the root workgroup_name / athena_admin_bucket_name variables (S3 names are
  # globally unique).
  athena_workgroup_name    = var.workgroup_name != "" ? var.workgroup_name : "${var.project_name}-prod-portal-wg"
  athena_admin_bucket_name = var.athena_admin_bucket_name != "" ? var.athena_admin_bucket_name : "${var.project_name}-prod-athena-admin"
  athena_admin_bucket_arn  = "arn:aws:s3:::${local.athena_admin_bucket_name}"

  # Shared-space bucket (Bucket 2) computed once the same cycle-free way:
  # the shared-spaces module creates the bucket, base's deploy policy is scoped to
  # its ARN (constructed string -> no shared-spaces->base cycle). Overridable via the
  # root shared_space_bucket_name variable (S3 names are globally unique).
  shared_space_bucket_name = var.shared_space_bucket_name != "" ? var.shared_space_bucket_name : "${var.project_name}-prod-shared-space"
  shared_space_bucket_arn  = "arn:aws:s3:::${local.shared_space_bucket_name}"

  # Hosted UI domain, computed cycle-free like the names above (the auth module
  # creates the domain; mirroring its default here avoids an app->auth reference).
  # The portal server sends sign-in and sign-out here and exchanges codes here; the
  # browser only navigates to it, so it never belongs in connect-src.
  cognito_domain_prefix    = var.cognito_domain_prefix != "" ? var.cognito_domain_prefix : "${var.project_name}-${var.environment}-portal"
  cognito_hosted_ui_domain = "${local.cognito_domain_prefix}.auth.${var.aws_region}.amazoncognito.com"

  # Shared-space orchestrator role ARN, constructed cycle-free like the
  # other role ARNs (shared-spaces creates it as
  # "${project}-${env}-shared-space-orchestrator-role"). It sits on the
  # analytics Lake Formation admins list as a CONSTRUCTED STRING — known at plan time
  # so it doesn't break the compact() in data_lake_settings (infra/info/deploy-role-iam.md);
  # apply ordering (module.analytics depends_on module.shared_spaces) guarantees the
  # role exists first.
  shared_space_orchestrator_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-shared-space-orchestrator-role"

  # Table-builder SHARED execution role ARN — one role for every verb, not one per verb —
  # constructed cycle-free like the other role ARNs
  # (module.table_builder creates it as "${project}-${env}-table-builder-execution-role").
  # Added to the analytics Lake Formation admins list as a CONSTRUCTED STRING so the
  # verbs' GetTable (check-table-absent) + CREATE (execute-ddl) resolve in the DYNAMIC
  # (per-user + per-shared-space) target databases — the model's fit for a catalog-wide
  # creator, since target DBs can't be enumerated in static Terraform. Known at plan
  # time → doesn't break the compact() admins list. module.analytics depends_on
  # module.table_builder, so the role is created BEFORE data_lake_settings references
  # it (LF rejects an unknown admin principal) — no from-scratch re-run needed.
  table_builder_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-table-builder-execution-role"

  # Table-share SHARED execution role ARN — one role for all five verbs, mirroring the
  # table-builder. Added to the analytics Lake Formation admins
  # list as a CONSTRUCTED STRING — known at plan time so it's compact()-safe — because
  # the recipient databases are DYNAMIC (per-user + per-shared-space): check-target-absent
  # Describes and create-table CREATEs in DBs static Terraform can't enumerate.
  # module.analytics depends_on module.table_share, so the role exists BEFORE
  # data_lake_settings references it (LF rejects an unknown admin principal).
  table_share_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-table-share-execution-role"

  # Data-quality SHARED execution role ARN — one role for all nine verbs, mirroring the
  # table-builder and table-share planes. Added to the analytics Lake
  # Formation admins list as a CONSTRUCTED STRING — known at plan time so it's
  # compact()-safe — because the temp-table target database is DYNAMIC: the actor's own
  # database for a personal check, the shared space's for a shared one, neither
  # enumerable in static Terraform. create-temp-tables CREATEs the throwaway dq_tmp_*
  # external tables there and drop-temp-tables DELETEs them on every path.
  # module.analytics depends_on module.data_quality, so the role exists BEFORE
  # data_lake_settings references it (LF rejects an unknown admin principal).
  data_quality_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-data-quality-execution-role"

  # File-send SHARED execution role ARN — one role for every verb, like every other
  # plane — constructed cycle-free like the role ARNs above
  # (module.file_send creates it as "${project}-${env}-file-send-execution-role").
  #
  # NOT ON THE LAKE FORMATION ADMINS LIST, and that is the difference between this plane
  # and its three siblings: a send moves FILES. It creates no table, describes no database
  # and runs no DDL, so it needs no catalog-wide creator designation.
  #
  # It IS passed to module.data, for the user-space bucket policy's principal allowlist
  # An explicit resource-policy Deny beats an identity-policy Allow, so
  # a plane whose role is missing from that list is denied by the bucket however correct
  # its own grants are — and the failure is asymmetric enough to read as a code bug: every
  # `space` recipient works (the shared-space bucket has no bucket policy) and every `user`
  # recipient fails AccessDenied. A constructed string rather than a module output for the
  # usual reason, which the allowlist is precisely the shape of: an unknown-at-plan ARN
  # inside a LIST silently drops the change.
  file_send_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-file-send-execution-role"

  # File-operations SHARED execution role ARN — one role for every verb, like every other
  # plane — constructed cycle-free like the role ARNs above (module.file_ops creates it as
  # "${project}-${env}-file-ops-execution-role").
  #
  # NOT ON THE LAKE FORMATION ADMINS LIST, for file-send's reason: a file operation moves
  # FILES. It creates no table, describes no database and runs no DDL.
  #
  # It IS passed to module.data for the user-space bucket policy's principal allowlist, and
  # that happens NOW rather than when the plane first touches S3 — the allowlist is
  # hand-maintained, an explicit resource-policy Deny beats an identity Allow, and a plane
  # missing from the list is denied by the bucket however correct its own grants are. The
  # failure is asymmetric enough to read as a code bug: every SHARED-space operation works
  # (the shared-space bucket has no bucket policy) and every PERSONAL one fails
  # AccessDenied. A constructed string rather than a module output for the usual reason,
  # which the allowlist is precisely the shape of: an unknown-at-plan ARN inside a LIST
  # silently drops the change.
  file_ops_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-file-ops-execution-role"

  # Results-conversion SHARED execution role ARN, constructed cycle-free like the ones above
  # (module.results_conversion creates it as "${project}-${env}-results-conversion-execution-role").
  # Passed to module.data for the user-space bucket policy's principal allowlist from the
  # first apply: the plane reads a user's own results object out of that bucket, and an
  # explicit resource-policy Deny beats its identity Allow. Not on the Lake Formation admins
  # list — it starts no query and runs no DDL.
  results_conversion_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-results-conversion-execution-role"

  # Archive bucket (Bucket 5) computed once the same cycle-free way: the archive
  # module creates it, base's deploy policy is scoped to its NAME (an exact-name statement,
  # because the bucket has no trailing segment and so does not match the plane's
  # {project}-*-archive-* pattern). Overridable via the root archive_bucket_name variable
  # (S3 names are globally unique).
  #
  # NOT IN THE CSP's connect-src, and that absence is a requirement rather than an
  # oversight: the browser never reads this bucket, so its host must not appear in
  # the enumerated list. A reviewer should be able to read that list and see no
  # archive host.
  archive_bucket_name = var.archive_bucket_name != "" ? var.archive_bucket_name : "${var.project_name}-prod-archive"

  # The archive plane's audit trail bucket, and the read-only verification
  # role's ARN. Both computed the same cycle-free way as the archive bucket above — base's
  # deploy policy is scoped to the bucket NAME, and modules/analytics needs the role ARN at
  # PLAN time for its compact() LF-Tag grant, so neither can come from module.verification's
  # own outputs without a cycle.
  #
  # The trail bucket is NOT in the CSP's connect-src either, for the archive bucket's reason:
  # the browser has no relationship with either.
  verification_trail_bucket_name = "${var.project_name}-${var.environment}-archive-audit"
  # EMPTY when no principal has been named, because the role is then not created — and
  # analytics' compact() must drop it rather than granting Lake Formation DESCRIBE to a role
  # that does not exist. A constructed string rather than module.verification's output for the
  # usual reason: analytics needs it at PLAN time, and an unknown value inside a list silently
  # drops the change (the same trap the file-send allowlist records above).
  verification_role_arn = length(var.verification_principal_arns) > 0 ? "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-verification" : ""

  # Archive SHARED execution role ARN — one role for every verb, like every other plane —
  # constructed cycle-free like the role ARNs above (module.archive creates
  # it as "${project}-${env}-archive-execution-role").
  #
  # NOT ON THE LAKE FORMATION ADMINS LIST, for file-send's reason: an archive moves FILES.
  # It creates no table, describes no database and runs no DDL.
  #
  # It is threaded THREE ways, which is one more than any previous plane and each one is
  # load-bearing. (1) module.data, for the user-space bucket policy's principal allowlist —
  # an explicit resource-policy Deny beats an identity-policy Allow, so without it every
  # PERSONAL archive fails AccessDenied while every SHARED one succeeds, which reads like a
  # code bug and is not. (2) module.archive itself, for the archive bucket's OWN policy,
  # which denies every principal but this role and the deploy role. (3) Nothing in the SPA,
  # ever. A constructed string rather than a module output for the usual reason, which the
  # allowlist is precisely the shape of: an unknown-at-plan ARN inside a LIST silently drops
  # the change.
  archive_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-archive-execution-role"

  # Notifications-writer role ARN, constructed cycle-free like the role ARNs
  # above (module.notifications creates it as "${project}-${env}-notifications-writer-role").
  # Passed to module.data so the user-space bucket policy can EXCLUDE it from the
  # data-access Deny — the single writer read-modify-writes {username}/user_settings/
  # notifications.json, and without the exclusion the resource-policy Deny would override
  # the writer's identity-policy Allow. Constructed string (not module.notifications'
  # output) so it's known at plan time; apply ordering (data before notifications, via
  # module.notifications depends_on module.data) is preserved.
  notifications_writer_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-notifications-writer-role"

  # Username-directory builder role ARN, constructed cycle-free like the role ARNs
  # above (module.user_directory creates it as "${project}-${env}-user-directory-build" — no
  # `-role` suffix, matching the deploy grant's ARN pattern).
  #
  # A CONSTRUCTED STRING RATHER THAN A MODULE OUTPUT, and here that is load-bearing rather
  # than stylistic: this ARN goes into the user-space bucket policy's principal allowlist, and
  # an unknown-at-plan ARN inside a LIST attribute made OpenTofu plan NO change to that list —
  # the value was never written (infra/info/deploy-role-iam.md → "An unknown ARN inside compact()/a list
  # silently drops the change"). `scheduled-function` does export a role_arn, so the rule is
  # this string, never module.user_directory.role_arn. Nothing orders the two at apply: the
  # allowlist entry is a string match in a policy condition, and the builder writes only at
  # runtime.
  #
  # Without the allowlist entry the builder's PutObject fails with an opaque AccessDenied that
  # looks like an IAM problem and is not — the bucket policy's Deny overrides its identity
  # policy's Allow. That has bitten this repo three times; modules/observability/README.md
  # carries the long-form account.
  user_directory_build_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-user-directory-build"

  # Logs queue name/ARN/URL, constructed cycle-free like the role ARNs above —
  # and here the cycle is REAL, not merely avoided: module.observability consumes
  # module.auth's user_pool_id, so module.auth referencing module.observability's outputs
  # is a module cycle Tofu rejects outright. The Cognito triggers need the queue, so they
  # get these strings. Must match modules/observability/locals.tf's
  # logs_queue_name and the queue's own url/arn attributes.
  #
  # Nothing is lost by constructing them: an IAM policy does not validate that its resource
  # exists, and LOGS_QUEUE_URL is read with os.environ.get, so a trigger invoked before the
  # queue exists logs to stdout rather than failing.
  logs_queue_name = "${var.project_name}-${var.environment}-logs.fifo"
  logs_queue_arn  = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.logs_queue_name}"
  logs_queue_url  = "https://sqs.${var.aws_region}.amazonaws.com/${data.aws_caller_identity.current.account_id}/${local.logs_queue_name}"

  # Notifications queue ARN/URL, constructed cycle-free like the role ARNs
  # above (module.notifications creates it as "${project}-${env}-notifications-requests.fifo").
  # These feed module.shared_spaces, the first trusted producer: the
  # ARN scopes the orchestrator role's sqs:SendMessage, the URL is the verb Lambdas'
  # NOTIFICATIONS_QUEUE_URL. Constructed strings (not module.notifications' outputs) so
  # they're KNOWN AT PLAN TIME and don't force a shared_spaces→notifications dependency
  # (infra/info/deploy-role-iam.md "unknown ARN" discipline); IAM never validates that the queue
  # exists, so no apply ordering is needed.
  notifications_queue_name = "${var.project_name}-${var.environment}-notifications-requests.fifo"
  notifications_queue_arn  = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.notifications_queue_name}"
  notifications_queue_url  = "https://sqs.${var.aws_region}.amazonaws.com/${data.aws_caller_identity.current.account_id}/${local.notifications_queue_name}"

  # LF registration role ARN, constructed cycle-free like the role ARNs
  # above (analytics creates it as "${project_name}-analytics-lf-registration-role").
  # Passed to the data module so the user-space bucket policy can EXCLUDE it from
  # the data-access Deny: Lake Formation assumes THIS role to vend creds for the
  # registered location, so when a user queries a Glue table the read happens as
  # this role — and without the exclusion the bucket policy's explicit Deny blocks
  # its s3:ListBucket/GetObject (an explicit resource-policy deny overrides the
  # role's own identity-policy allow). Apply ordering (data before analytics) means
  # the role may not exist on the first apply, so this MUST be a constructed string,
  # not module.analytics output.
  lf_registration_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-analytics-lf-registration-role"

  # Post-confirmation Lambda exec role ARN, constructed the same
  # cycle-free way as the portal/deploy roles. The auth module creates this role as
  # "${project_name}-${environment}-post-confirmation-role"; analytics adds it as a
  # Lake Formation admin. It MUST be a constructed string (not module.auth's output)
  # so the value is KNOWN AT PLAN TIME: when it flowed through module.auth's output it
  # was unknown during the apply that creates the role, and an unknown inside the
  # compact() in the LF data-lake settings caused OpenTofu to silently drop the admin
  # change — the role never became an LF admin and provisioning grants failed. Apply
  # ordering (auth -> data -> analytics) still guarantees the role exists first.
  post_confirmation_exec_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-post-confirmation-role"

  # The request DLQs the drain attaches to. Constructed names (each arc module
  # creates its own as "${project}-${env}-<domain>-requests-dlq.fifo"), cycle-free and known
  # at plan time like every other cross-module ARN here.
  #
  # THE NOTIFICATIONS DLQ IS DELIBERATELY ABSENT. The drain's only delivery channel is the
  # notifications queue, so draining the notifications DLQ would ask the queue that just
  # failed to deliver to deliver the news about itself. See the comment on its queue in
  # function-notifications.tf; the honest answer there is operator-facing and out of the
  # drain's scope. Keep this list and dlq_drain.py's SOURCES table in step —
  # lambdas/test_feedback_module.py reads this list and fails if a plane is attached without
  # being in the table, or the other way round.
  drained_dlq_names = [
    "${var.project_name}-${var.environment}-data-quality-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-table-builder-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-table-share-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-shared-space-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-file-send-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-archive-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-file-ops-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-results-conversion-requests-dlq.fifo",
  ]

  # The SPA and the API are two hosts under one registrable domain. Constructed here at
  # root, from the domain variables, and passed DOWN into the modules that need them —
  # never derived a second time inside a module and never taken from another module's
  # output. A constructed string is known at plan time; a module output fed into another
  # module's list attribute is not, and an unknown value inside a list is the shape that
  # forces a whole plan to defer. The Cognito callback list, the API's CORS list and the
  # CSP's connect-src all read these.
  spa_host   = "${var.spa_subdomain}.${var.parent_domain}"
  api_host   = "${var.api_subdomain}.${var.parent_domain}"
  spa_origin = "https://${var.spa_subdomain}.${var.parent_domain}"
  api_origin = "https://${var.api_subdomain}.${var.parent_domain}"

  # The pool's OIDC issuer, in the one form AWS documents. Built once here because both
  # the issuer and the JWKS URL are derived from it, and two spellings of the same string
  # is how they come to disagree.
  cognito_issuer = "https://cognito-idp.${var.aws_region}.amazonaws.com/${module.auth.user_pool_id}"

  # ── The portal server's session ──
  # Each name is written ONCE, here, and both the resource that owns it and the grant that names it
  # read it: the table and the task role, the parameter and the execution role. An ARN built from
  # the same string is known at plan, which the plan-time IAM scan needs.
  session_table_name           = "${var.project_name}-${var.environment}-sessions"
  session_table_arn            = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.session_table_name}"
  session_key_alias            = "alias/${var.project_name}-${var.environment}-session"
  dev_session_table_name       = "${var.project_name}-${var.environment}-dev-sessions"
  dev_session_key_alias        = "alias/${var.project_name}-${var.environment}-dev-session"
  client_secret_parameter_name = "/${var.project_name}-${var.environment}/portal/oidc-client-secret"
  client_secret_parameter_arn  = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.client_secret_parameter_name}"
  dev_session_parameter_name   = "/${var.project_name}-${var.environment}/portal/dev-session-env"

  # The web task role, as the deployed session key's policy names it. Built here from the name the
  # spa module gives the role, because the key sits outside the web tier's switch and reads nothing
  # inside it; the policy matches it by aws:PrincipalArn, which KMS accepts while the role is absent.
  web_task_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-spa-task-role"

  # The origin `npm run dev` serves on, and the only place it is named: the dev client's callback and
  # sign-out URL, and the local server's PORTAL_ORIGIN, are built from it.
  dev_origin = "http://localhost:5173"

  # The OIDC client's endpoints, as FIELDS rather than derived inside the server from a domain:
  # the concatenation happens once, here, as the verifier's JWKS URI's does.
  cognito_domain_origin = "https://${local.cognito_hosted_ui_domain}"

  # The ID-token claim that carries the username, read by BOTH the API's verifier and the portal
  # server, which hands it to the browser to build S3 prefixes and Glue database names. One value, so
  # a provider change cannot move one reader and leave the other attributing requests to a different
  # name. Federated users get a synthetic cognito:username, so the transition changes this line.
  oidc_username_claim = "cognito:username"

  # What the server reads, named exactly as it reads it. Server-only: none is a CONFIG_ key, and
  # the secret is not here (the task definition's `secrets` carries it).
  session_environment = {
    PORTAL_ORIGIN           = local.spa_origin
    API_ORIGIN              = local.api_origin
    OIDC_ISSUER             = local.cognito_issuer
    OIDC_CLIENT_ID          = module.auth.server_client_id
    OIDC_AUTHORIZE_URL      = "${local.cognito_domain_origin}/oauth2/authorize"
    OIDC_TOKEN_URL          = "${local.cognito_domain_origin}/oauth2/token"
    OIDC_REVOKE_URL         = "${local.cognito_domain_origin}/oauth2/revoke"
    OIDC_LOGOUT_URL         = "${local.cognito_domain_origin}/logout"
    OIDC_USERNAME_CLAIM     = local.oidc_username_claim
    SESSION_TABLE_NAME      = local.session_table_name
    SESSION_MAX_AGE_SECONDS = tostring(module.auth.server_session_max_age_seconds)
    AWS_REGION              = var.aws_region
  }

  # What a local server reads, from the SAME locals as the task definition's environment: the
  # document's CONFIG_ keys, the CSP's connect-src and the session settings, with the dev origin and
  # the dev session table in place of the deployed ones. The auth module adds the dev client's own id
  # and secret. Nothing here is written as a literal, so the two environments cannot drift.
  dev_session_environment = merge(
    { for key, value in local.spa_runtime_config : "CONFIG_${key}" => value },
    { PORTAL_CSP_CONNECT_SRC = local.csp_connect_src },
    { for key, value in local.session_environment : key => value if key != "OIDC_CLIENT_ID" },
    { PORTAL_ORIGIN = local.dev_origin },
    { SESSION_TABLE_NAME = local.dev_session_table_name },
  )

  # The load balancer's access-log prefix in the admin bucket. At ROOT because two modules must
  # agree on it: the one that points the balancer at it and writes the bucket policy, and the one
  # that owns the bucket's lifecycle rules. A literal in each would be two literals.
  alb_access_logs_prefix = "alb-access-logs"

  # Every host the browser fetches. This list IS the app's network surface — anything missing
  # is a broken feature, not a hardened one, and nothing observes a CSP offline.
  #
  # Built from CONSTRUCTED STRINGS, never from a module output. api_origin in particular must
  # come from the subdomain variables above rather than from module.api's domain name, which
  # would route a dependency cycle through base.
  #
  # It lives at root because the container reads it directly and a root-level check cannot read
  # a local declared in a module. Every other directive of the policy describes the bundle and
  # lives in the Next.js server's policy builder (apps/portal/src/server/contentSecurityPolicy.ts).
  # The browser signs in through the portal server and calls the API through its own origin's /api/,
  # so it fetches its own origin and presigned bytes, and nothing else. Cognito is reached only by
  # navigation, which connect-src does not govern.
  csp_connect_src = join(" ", [
    "'self'",
    "https://${local.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://${local.shared_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
  ])


  # ── The runtime configuration document ──────────────────────────────────────
  # Every key the portal's runtime-configuration classification declares, with its value. The
  # Next.js server in the container renders /config.json from these.
  #
  # THE KEYS ARE NAMED HERE AND NOWHERE ELSE IN THE INFRASTRUCTURE. modules/spa renders one
  # CONFIG_<key> environment entry per map entry, so a key added to the classification is
  # wired by adding its value here — there is no second list to keep in step, and no shape in
  # which a portal ships carrying only some of the document.
  #
  spa_runtime_config = {
    environment       = var.environment
    maxUploadBytes    = tostring(var.max_upload_bytes)
    userSpaceBucket   = local.user_space_bucket_name
    sharedSpaceBucket = local.shared_space_bucket_name
  }
}

module "base" {
  source = "./modules/base"

  project_name     = var.project_name
  github_repo      = var.github_repo
  state_bucket     = var.state_bucket
  state_lock_table = var.state_lock_table
  aws_region       = var.aws_region
  account_id       = data.aws_caller_identity.current.account_id

  # Scopes the deploy role's Route 53 grant to the single zone the front door owns.
  # The grant and the records that use it read the SAME variable, so they cannot
  # disagree: a wrong id fails ChangeResourceRecordSets with NoSuchHostedZone before
  # anything reaches state, rather than leaving a grant pointing at another zone.
  route53_zone_id = var.route53_zone_id

  # Constructed (not module.data outputs) so base has no dependency on data.
  user_space_bucket_arn       = "arn:aws:s3:::${local.user_space_bucket_name}"
  portal_role_arn             = local.portal_role_arn
  lambda_artifacts_bucket_arn = local.lambda_artifacts_bucket_arn
  athena_admin_bucket_arn     = local.athena_admin_bucket_arn

  # Shared-space control-plane: the bucket ARN scopes the deploy role's
  # s3:* on Bucket 2; the rest of the shared-space deploy grants are scoped by name
  # pattern (${project_name}-*-shared-space-*) inside the policy template.
  shared_space_bucket_arn = local.shared_space_bucket_arn

  # The archive bucket the deploy role manages, by NAME. The rest of the archive
  # deploy grants are scoped by {project_name}-*-archive-* name patterns in the policy
  # template; the bucket needs an exact-name statement because it has no trailing segment.
  archive_bucket_name = local.archive_bucket_name

  # The archive-audit trail bucket, by NAME and for the same reason.
  verification_trail_bucket_name = local.verification_trail_bucket_name
}

module "auth" {
  source = "./modules/auth"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  spa_origin   = local.spa_origin
  # The RESOLVED prefix, not the raw var: the CSP allows a host built from this
  # same local, so root has to be the one place the default is decided. Passing
  # the raw var would leave the module's own ternary free to drift from the CSP's
  # — silently allowing a host the user pool does not have.
  cognito_domain_prefix = local.cognito_domain_prefix

  # Named at root, where the execution role's grant builds its ARN from the same string.
  client_secret_parameter_name = local.client_secret_parameter_name

  # The local-development client and everything a laptop's server needs, outside the web tier's switch
  # with the client itself, so a laptop signs in whether or not the tier is on.
  dev_origin                 = local.dev_origin
  dev_session_parameter_name = local.dev_session_parameter_name
  dev_session_environment    = local.dev_session_environment

  # Post-confirmation Lambda inputs. account_id/region scope the exec
  # role's Glue ARNs; portal_role_arn (constructed, cycle-free) is the LF grant
  # target the Lambda receives via env var.
  aws_region      = var.aws_region
  account_id      = data.aws_caller_identity.current.account_id
  portal_role_arn = local.portal_role_arn

  # Drives the custom:shared_space_1..N user-pool attributes, the claims the API reads to
  # stamp the shared_space_1..N session tags.
  max_shared_memberships = var.max_shared_memberships

  # Both triggers import `cpcommon.observability` and emit
  # under service="auth". CONSTRUCTED strings, not module.observability's outputs — that
  # module consumes user_pool_id from this one, so a real reference is a module cycle.
  logs_queue_arn = local.logs_queue_arn
  logs_queue_url = local.logs_queue_url

  # The deploy role grants itself the cognito-idp permissions (modules/base
  # policies). Without this ordering, Tofu's parallel apply can call
  # CreateUserPool before that grant takes effect, failing with AccessDenied.
  # Force the base policy to settle before any Cognito resource is created.
  depends_on = [module.base]
}

module "data" {
  source = "./modules/data"

  account_id             = data.aws_caller_identity.current.account_id
  project_name           = var.project_name
  spa_origin             = local.spa_origin
  user_space_bucket_name = local.user_space_bucket_name
  portal_role_name       = local.portal_role_name
  deploy_role_arn        = local.deploy_role_arn

  # The portal role's one trust statement: the API assumes this role to act as its caller, with
  # session tags read from the verified token's claims. The key set the statement admits is
  # built from the same two variables the function's environment carries, so the two cannot drift
  # apart by transcription.
  #
  # A REAL module reference, and it is the one cross-module role ARN in this file that must not be
  # a constructed string. The others feed bucket-policy CONDITIONS -- `aws:PrincipalArn`
  # comparisons, which are string matches needing no principal to exist. This one feeds a trust
  # policy's `Principal.AWS`, which IAM VALIDATES: an ARN naming a role that does not exist yet is
  # refused as a malformed policy document. module.data has no other tie to module.api, so without
  # this edge a from-scratch apply is free to create the portal role first and fail. The value is
  # (known after apply) only on the apply that creates the API role, and it feeds a policy document
  # rather than a for_each, so an unknown there is benign.
  api_execution_role_arn = module.api.api_execution_role_arn
  principal_tag_key      = var.principal_tag_key
  max_shared_memberships = var.max_shared_memberships

  # Excluded from the bucket-policy data-access Deny so Lake Formation (assuming
  # this role) can read the registered location when serving Athena queries.
  lf_registration_role_arn = local.lf_registration_role_arn

  # Also excluded from the Deny so the shared-space orchestrator can write
  # each member's per-user cache ({username}/user_settings/shared-connections.json).
  # Constructed string (locals) — known at plan; the role is created in
  # module.shared_spaces, but a bucket-policy condition only needs the ARN string.
  shared_space_orchestrator_role_arn = local.shared_space_orchestrator_role_arn

  # Also excluded from the Deny so the notifications-writer can read-modify-write
  # each user's {username}/user_settings/notifications.json. Constructed string (locals) —
  # known at plan; the role is created in module.notifications.
  notifications_writer_role_arn = local.notifications_writer_role_arn

  # Also excluded from the Deny so the daily directory builder can list the bucket's
  # workspace prefixes and publish _directory/usernames.json. Constructed string (locals) —
  # known at plan; the role is created in module.user_directory, and a bucket-policy condition
  # only needs the ARN string, so no cycle.
  user_directory_build_role_arn = local.user_directory_build_role_arn

  # The three control-plane execution roles that READ user-space data via their own
  # execution role must ALSO be excluded from the Deny, or the bucket
  # resource policy overrides their identity-side s3:GetObject/ListBucket grants and every
  # read 403s. None was ever added here — invisible until the first live run (greenfield).
  # Constructed strings (locals) — known at plan; the roles are created in their own
  # modules, but a bucket-policy condition only needs the ARN string, so no cycle.
  table_builder_execution_role_arn = local.table_builder_execution_role_arn
  table_share_execution_role_arn   = local.table_share_execution_role_arn
  data_quality_execution_role_arn  = local.data_quality_execution_role_arn

  # The file-send execution role reads the sender's personal-space files
  # and writes a `user` recipient's shared_files/ inbox, so it needs the same exclusion.
  # The allowlist is hand-maintained — every future plane that touches this bucket must
  # make this same three-part change (a variable here, the templatefile() argument, the
  # root wiring) or be denied at runtime with nothing in the plan to warn it.
  file_send_execution_role_arn = local.file_send_execution_role_arn

  # The archive execution role reads the actor's personal-space files and
  # deletes them once every object is confirmed copied, so it needs the same
  # exclusion. The allowlist is hand-maintained and this is the FIFTH plane to make the same
  # three-part change (a variable there, the templatefile() argument, the root wiring); a
  # plane that skips it is denied at runtime with nothing in the plan to warn it.
  archive_execution_role_arn = local.archive_execution_role_arn

  # The file-operations execution role will eventually read, copy and delete a personal
  # space's files. It is excluded from the Deny NOW, with the role, rather than with the
  # first verb that needs it — this is the SIXTH plane to make the same three-part change
  # (a variable there, the templatefile() argument, the root wiring), and a plane that
  # skips it is denied at runtime with nothing in the plan to warn it.
  file_ops_execution_role_arn = local.file_ops_execution_role_arn

  results_conversion_execution_role_arn = local.results_conversion_execution_role_arn

  # Same ordering as auth: the deploy role grants itself the S3 + IAM-role
  # permissions (modules/base policy). Force that grant to settle before the
  # bucket/role are created, or a first apply can hit AccessDenied.
  depends_on = [module.base]
}

module "lambda_artifacts" {
  source = "./modules/lambda-artifacts"

  bucket_name = local.lambda_artifacts_bucket_name

  # Same ordering as auth/data: the deploy role grants itself this bucket's
  # management (modules/base policy). Force that grant to settle before the
  # bucket is created, or a first apply can hit AccessDenied.
  depends_on = [module.base]
}

# The Lambda container image's registry. Every function in the fleet runs an image from it; the
# image, its behaviour matrix and the pipeline that fills this live outside Terraform, which owns
# the repository and its lifecycle bound and nothing else.
module "lambda_image" {
  source = "./modules/lambda-image"

  project_name = var.project_name
  environment  = var.environment

  # Same ordering as lambda-artifacts and for the same reason: the deploy role grants itself this
  # registry's management in modules/base, and a first apply that races that grant hits
  # AccessDenied. The grant itself landed in an earlier, separate apply.
  depends_on = [module.base]
}

# Analytics foundation: shared Athena workgroup + admin-only results
# bucket. Phase 1 is this additive infrastructure; Phase 2 adds Lake Formation
# bootstrap, hybrid-mode registration of the user-space bucket, and the portal
# role's Glue/Athena/LF policy (which will pull in module.data's bucket/role and
# the principal-tag key). Names are computed in locals above and passed in.
module "analytics" {
  source = "./modules/analytics"

  # The load balancer's access-log prefix, decided at root: the module that points the balancer
  # at it reads the same value, and two literals could disagree with no symptom but logs that
  # never expire.
  alb_access_log_prefix = local.alb_access_logs_prefix

  workgroup_name           = local.athena_workgroup_name
  athena_admin_bucket_name = local.athena_admin_bucket_name

  # Phase 2: Lake Formation + portal-role policy inputs. Names/ARNs are computed in
  # locals above (cycle-free constructed strings) so analytics consumes data/base
  # outputs only through these values, never creating a module cycle.
  project_name          = var.project_name
  aws_region            = var.aws_region
  account_id            = data.aws_caller_identity.current.account_id
  user_space_bucket_arn = "arn:aws:s3:::${local.user_space_bucket_name}"
  portal_role_name      = local.portal_role_name
  portal_role_arn       = local.portal_role_arn
  principal_tag_key     = var.principal_tag_key
  deploy_role_arn       = local.deploy_role_arn

  # The post-confirmation Lambda's exec role, added as a Lake Formation
  # admin so it can issue per-database grants. Constructed string (see locals above)
  # — NOT module.auth's output — so it's known at plan time; otherwise the unknown
  # value broke the compact() in the LF admins list and the grant silently dropped.
  lambda_provisioner_role_arn = local.post_confirmation_exec_role_arn

  # Add the shared-space orchestrator role as a Lake Formation admin so it
  # can later GrantPermissions on shared DBs + DATA_LOCATION_ACCESS on the shared
  # location. Constructed string (locals above) — known at plan time so it doesn't
  # break the compact() admins list; module.shared_spaces in depends_on guarantees
  # the role exists before this sets data_lake_settings.
  shared_space_orchestrator_role_arn = local.shared_space_orchestrator_role_arn

  # Add the table-builder shared execution role as a Lake Formation admin so
  # its verbs can Describe (check-table-absent) + CREATE (execute-ddl) tables in the
  # dynamic per-user + per-shared-space target databases. Constructed string (locals
  # above) — known at plan time so it's compact()-safe.
  table_builder_execution_role_arn = local.table_builder_execution_role_arn

  # Add the table-share shared execution role as a Lake Formation admin for
  # the same reason — its verbs Describe (check-target-absent) + CREATE (create-table)
  # tables in the dynamic recipient databases. Constructed string (locals above).
  table_share_execution_role_arn = local.table_share_execution_role_arn

  # Add the data-quality shared execution role as a Lake Formation admin for
  # the same reason — create-temp-tables CREATEs and drop-temp-tables DELETEs the
  # throwaway dq_tmp_* external tables in the dynamic target database (the actor's own,
  # or the shared space's). Constructed string (locals above).
  data_quality_execution_role_arn = local.data_quality_execution_role_arn

  # The read-only verification role, granted DESCRIBE on the portal-managed
  # LF-Tag so an owed catalog read-back can be made at all. DESCRIBE only — it is NOT on the
  # Lake Formation admins list and gets no DATA_LOCATION_ACCESS, so it reads definitions and
  # never data. Constructed string (locals above), known at plan time so it is compact()-safe.
  verification_role_arn = local.verification_role_arn

  # Ordering: base grants the deploy role its Athena/Glue/LF/admin-bucket perms;
  # data creates the user-space bucket + portal role that analytics registers in LF
  # and attaches the analytics policy to; shared_spaces + table_builder + table_share +
  # data_quality create the orchestrator/execution roles added to the LF admins list
  # (they must exist before data_lake_settings references them — LF rejects an unknown
  # admin principal). Force all to settle first.
  # module.verification joins the list for the reason the orchestrator role is on it (see the
  # comment above): its role ARN reaches here as a CONSTRUCTED string, so Tofu has no edge to
  # the resource that creates it — and Lake Formation rejects a grant to a principal that does
  # not exist. Latent while `verification_principal_arns` is empty (the ARN is then "" and
  # compact() drops the grant), and hit on exactly the apply that sets it.
  depends_on = [module.base, module.data, module.shared_spaces, module.table_builder, module.table_share, module.data_quality, module.verification]
}


# The structured-logging pipe: one FIFO logs queue every service writes to, and its backlog
# alarm. The sweep that lands its events as Hive-partitioned NDJSON under s3://{admin}/logs/ is a
# scheduled function of its own, in function-log-sweep.tf.
module "observability" {
  source = "./modules/observability"

  project_name = var.project_name
  environment  = var.environment

  # base writes the deploy role's observability grants, so an apply changing one writes it before
  # anything here uses it. The edge also defers every data source in the module to apply, which is
  # why the module declares none: modules/observability/README.md.
  depends_on = [module.base]
}

# ── Verification access ─────────────────────────────────────
# NOT A CONTROL PLANE. Two owed live assertions could not be made by ANY principal, and a
# check nobody can run is indistinguishable from one that passes — the# "did not run is never clean" rule, and blind gates, in a third place.
#
#  1. The restore's negative assertion — that a `destination_occupied` refusal did not already
#     initiate retrieval. `dat-prod-archive` explicit-denies the laptop IAM user, its
#     execution role trusts lambda.amazonaws.com only, the deploy role is GitHub-OIDC-only,
#     and NO TRAILS EXIST, so there was no independent record of whether RestoreObject was
#     ever called. A UI observation does not substitute: the script itself records that a
#     refusal which had already started retrieval looks identical from there, and the cost of
#     being wrong is 3-5 billed, uncancellable hours.
#  2. Catalog read-backs — the Description/comment preservation check and the owed
#     foreign projection fixture — which fail with `Insufficient Lake Formation permission(s):
#     Required Describe`.
#
# Both answers are READ-ONLY and neither widens the data path, which the rule puts out of scope
# explicitly: the trail records calls it does not authorize, and the role reads table
# DEFINITIONS with no SELECT and no DATA_LOCATION_ACCESS anywhere in its grants.
module "verification" {
  source = "./modules/verification"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  trail_bucket_name = local.verification_trail_bucket_name

  # The bucket whose OBJECT-LEVEL calls are recorded, by name: the advanced event selector
  # matches `arn:aws:s3:::{bucket}/` as an ARN prefix. Constructed local, so this module never
  # depends on module.archive and no cycle is possible.
  archive_bucket_name = local.archive_bucket_name

  # Operator identities, from the TF_VAR_verification_principal_arns repo variable (NOT a local
  # terraform.tfvars — a local apply proposes to recreate the data buckets it cannot read; see
  # modules/verification/iam.tf). Empty ⇒ no role, and the TRAIL — the half that unblocks the restore's negative assertion
  # Ships regardless.
  verification_principal_arns = var.verification_principal_arns

  # base grants the deploy role the trail, bucket and role perms (and holds the 30s
  # propagation floor) BEFORE anything here lands.
  depends_on = [module.base]
}

# ── The container platform's network ──────────────────────────────────────────
# No consumer yet: the load balancer and the ECS service arrive with the module that creates
# them. It ships first and alone deliberately — every one of its failure modes (a missing
# endpoint, private DNS off, a gateway endpoint associated with the wrong route table) applies
# green and shows up only when something tries to pull an image through it, so proving the
# network is worth its own apply rather than being debugged underneath a container.
# The API's front door. A leaf: nothing else in this composition reads its outputs, and
# nothing in it is referenced by the CSP — api_origin is a constructed string in the locals
# above precisely so this module never becomes an input to that list.
#
# It takes the six cpcommon required values as ENVIRONMENT, which is not the same as taking
# them as permissions: the function's role names logs and one queue and nothing else, and a
# test asserts that against the rendered policy. cpcommon resolves config lazily, so an
# unset one would fail at first read rather than at import — the environment is complete
# anyway, so the spec that starts verifying tokens inherits no surprise.
module "api" {
  source = "./modules/api"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # The FIFO request queues this function is the only writer of. Their URLs go in the environment
  # and their ARNs into the one grant; the browser's eight grants came off in the same change that
  # added the first eight, so there was never a window with two writers and nothing asserting it.
  #
  # Feedback is the ninth and was never one of the eight: it is the first queue the browser has
  # had no relationship with at all, rather than one whose grant was taken away.
  shared_space_queue_url       = module.shared_spaces.queue_url
  notifications_queue_url      = module.notifications.queue_url
  table_build_queue_url        = module.table_builder.queue_url
  table_share_queue_url        = module.table_share.queue_url
  data_quality_queue_url       = module.data_quality.queue_url
  file_send_queue_url          = module.file_send.queue_url
  archive_queue_url            = module.archive.queue_url
  file_ops_queue_url           = module.file_ops.queue_url
  results_conversion_queue_url = module.results_conversion.queue_url
  feedback_queue_url           = module.feedback.queue_url

  request_queue_arns = [
    module.shared_spaces.queue_arn,
    module.notifications.queue_arn,
    module.table_builder.queue_arn,
    module.table_share.queue_arn,
    module.data_quality.queue_arn,
    module.file_send.queue_arn,
    module.archive.queue_arn,
    module.file_ops.queue_arn,
    module.results_conversion.queue_arn,
    module.feedback.queue_arn,
  ]

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  # Built at root from the domain variables, never derived inside the module.
  api_host        = local.api_host
  route53_zone_id = var.route53_zone_id

  # From the VALIDATION, not the certificate: same ARN, but only this one creates the edge
  # that stops a clean rebuild attaching a still-pending certificate to the domain.
  api_certificate_arn = aws_acm_certificate_validation.api.certificate_arn

  logs_queue_url = module.observability.logs_queue_url
  logs_queue_arn = module.observability.logs_queue_arn

  admin_bucket        = local.athena_admin_bucket_name
  user_space_bucket   = local.user_space_bucket_name
  shared_space_bucket = local.shared_space_bucket_name
  athena_workgroup    = local.athena_workgroup_name

  # The provider block, computed here from resources Terraform already owns. THE JWKS URL IS
  # BUILT ON THIS LINE AND NOWHERE ELSE, and that placement is the decision: Cognito publishes
  # its keys under its issuer and other providers do not, so the concatenation is a fact about
  # this provider rather than about the verifier. Keeping it at the composition root leaves the
  # module and every Python module downstream treating the URL as opaque — so swapping the
  # provider is this line plus the four beside it.
  # The identity layer. The role is the EXISTING portal role: module.data creates it under
  # local.portal_role_name, and local.portal_role_arn is built from that same name. Reusing it
  # is what keeps the user-space bucket policy's hand-maintained allowlist correct without a
  # new entry.
  portal_role_arn        = local.portal_role_arn
  principal_tag_key      = var.principal_tag_key
  max_shared_memberships = var.max_shared_memberships

  oidc_issuer          = local.cognito_issuer
  oidc_audience        = [module.auth.server_client_id, module.auth.dev_client_id]
  oidc_jwks_uri        = "${local.cognito_issuer}/.well-known/jwks.json"
  oidc_username_claim  = local.oidc_username_claim
  oidc_required_claims = jsonencode({ token_use = "id" })

  # base grants the deploy role the apigateway, function, role and log-group permissions
  # BEFORE anything here lands.
  depends_on = [module.base]
}


# ── The web tier's off switch ─────────────────────────────────────────────────
# `network` and `spa` exist only to serve the portal, and idle they are most of what the stack
# costs, so both come and go with web_tier_enabled. Nothing outside them may read their outputs: with the switch off there is no
# instance to index. infra/info/web-tier.md.
locals {
  web_tier_enabled = var.web_tier_enabled == "true"
}

module "network" {
  source = "./modules/network"
  count  = local.web_tier_enabled ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id
  vpc_cidr     = var.vpc_cidr

  # Read at root so the module's depends_on cannot defer it to apply — see the data
  # source's own note. Passed unsorted: the module owns the sort and the slice, because
  # the pairing of AZ to CIDR is its concern and nothing else reads these.
  availability_zone_names = data.aws_availability_zones.available.names

  # base grants the deploy role the VPC, subnet, route-table, security-group, endpoint and
  # flow-log permissions BEFORE anything here lands.
  depends_on = [module.base]
}

# ── The portal server's session stores ───────────────────────────────────────
# OUTSIDE the web tier's switch: switching the tier off must neither schedule a key for deletion
# nor drop every session. Neither reads a `network` or `spa` output. modules/session-store/README.md.
#
# The deployed store's key names its principals: the deploy role, and the web task role for this
# table alone, so no other principal an identity policy allows can read the refresh tokens in it.
module "session_store" {
  source = "./modules/session-store"

  account_id = data.aws_caller_identity.current.account_id
  aws_region = var.aws_region
  table_name = local.session_table_name
  key_alias  = local.session_key_alias

  named_principals = {
    deploy_role_arn = local.deploy_role_arn
    task_role_arn   = local.web_task_role_arn
  }

  # base grants the deploy role the table, key and alias permissions BEFORE anything here lands.
  depends_on = [module.base]
}

# Local dev servers' sessions. A dev server signs in with the developer's own credentials, whatever
# they are, so this key delegates to the account's IAM rather than naming a developer.
module "dev_session_store" {
  source = "./modules/session-store"

  account_id = data.aws_caller_identity.current.account_id
  aws_region = var.aws_region
  table_name = local.dev_session_table_name
  key_alias  = local.dev_session_key_alias

  depends_on = [module.base]
}

# ── The SPA image's registry ──────────────────────────────────────────────────
# Outside the switch: the tier can be off for months, and the registry keeps its images through it.
module "spa_image" {
  source = "./modules/spa-image"

  project_name = var.project_name
  environment  = var.environment

  # base grants the deploy role the registry permissions BEFORE anything here lands.
  depends_on = [module.base]
}


# ── The container platform ────────────────────────────────────────────────────
# The cluster, the task definition and the load balancer that serve the SPA.
# It runs the real image, which CI builds and pushes on every commit to main, while the switch is on.
#
# It takes the network's ids rather than building any of its own. The two are separate modules,
# but the switch takes both: the network exists only to carry this.
# The task security group is the seam: created there with no rules, ruled here, because every
# one of its rules names a group this module owns.
module "spa" {
  source = "./modules/spa"
  count  = local.web_tier_enabled ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  # Passed rather than read from a data source inside the module: the depends_on below would
  # defer any data source there, and a deferred read is a hard error where it feeds a for_each.
  account_id = data.aws_caller_identity.current.account_id

  # [0] because both modules share one count: the network is there whenever this is.
  vpc_id                         = module.network[0].vpc_id
  public_subnet_ids              = module.network[0].public_subnet_ids
  private_subnet_ids             = module.network[0].private_subnet_ids
  task_security_group_id         = module.network[0].task_security_group_id
  vpc_endpoint_security_group_id = module.network[0].vpc_endpoint_security_group_id
  s3_prefix_list_id              = module.network[0].s3_prefix_list_id

  repository_url = module.spa_image.repository_url
  repository_arn = module.spa_image.repository_arn

  # Built at root from the domain variables, never derived inside the module.
  spa_host        = local.spa_host
  route53_zone_id = var.route53_zone_id

  # From the VALIDATION, not the certificate: same ARN, but only this one creates the edge
  # that stops a clean rebuild attaching a still-pending certificate to the listener.
  spa_certificate_arn = aws_acm_certificate_validation.spa.certificate_arn

  # The admin bucket takes the load balancer's access logs, and this module writes that
  # bucket's first policy. Constructed name, as everywhere else; the ordering edge is the
  # depends_on below, because a policy cannot be written to a bucket that does not exist.
  admin_bucket_name  = local.athena_admin_bucket_name
  access_logs_prefix = local.alb_access_logs_prefix

  # The region's load-balancing account, for the access-log policy's second delivery principal.
  # Read at ROOT for the reason the availability zones are: a data source inside a module that
  # carries depends_on is deferred to apply.
  elb_account_arn = data.aws_elb_service_account.main.arn

  desired_count = var.spa_desired_count
  image_tag     = var.spa_image_tag

  runtime_config  = local.spa_runtime_config
  csp_connect_src = local.csp_connect_src

  # The portal server's session: its settings, the secret's parameter, the table its task role may
  # use, and the route to it.
  session_environment         = local.session_environment
  client_secret_parameter_arn = local.client_secret_parameter_arn
  session_table_arn           = local.session_table_arn
  dynamodb_prefix_list_id     = module.network[0].dynamodb_prefix_list_id

  # base grants the deploy role the ECS, ECR, load-balancer, role and log-group permissions
  # BEFORE anything here lands; analytics creates the bucket whose policy this module writes.
  depends_on = [module.base, module.analytics]
}
