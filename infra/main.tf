# ── Module composition ────────────────────────────────────────────────────────
# Infrastructure is grouped into bounded-context modules:
#   app  — SPA hosting: static assets bucket, CloudFront distribution, OAC
#   base — foundation: GitHub Actions OIDC provider and deployment role
#   auth — Cognito: User Pool, SPA app client, Hosted UI domain (SPEC-006)
#   data — user-space S3 bucket (Bucket 1) + CORS/encryption (SPEC-010)
# Future contexts get their own modules rather than growing resource-type files.

# The user-space bucket name is computed once here and shared two ways: the data
# module creates the bucket with it, and the base module's deploy policy is scoped
# to its ARN — passed as a constructed string to avoid a data→base dependency
# cycle (the deploy role must be able to manage a bucket the data module creates).
data "aws_caller_identity" "current" {}

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

  # Analytics names (SPEC-032) computed once: the analytics module creates the
  # workgroup + admin bucket, and base's deploy policy is scoped to the admin
  # bucket ARN (constructed string -> no analytics->base cycle). Overridable via
  # the root workgroup_name / athena_admin_bucket_name variables (S3 names are
  # globally unique).
  athena_workgroup_name    = var.workgroup_name != "" ? var.workgroup_name : "${var.project_name}-prod-portal-wg"
  athena_admin_bucket_name = var.athena_admin_bucket_name != "" ? var.athena_admin_bucket_name : "${var.project_name}-prod-athena-admin"
  athena_admin_bucket_arn  = "arn:aws:s3:::${local.athena_admin_bucket_name}"

  # Shared-space bucket (Bucket 2, SPEC-050) computed once the same cycle-free way:
  # the shared-spaces module creates the bucket, base's deploy policy is scoped to
  # its ARN (constructed string -> no shared-spaces->base cycle). Overridable via the
  # root shared_space_bucket_name variable (S3 names are globally unique).
  shared_space_bucket_name = var.shared_space_bucket_name != "" ? var.shared_space_bucket_name : "${var.project_name}-prod-shared-space"
  shared_space_bucket_arn  = "arn:aws:s3:::${local.shared_space_bucket_name}"

  # Shared-space orchestrator role ARN (SPEC-050), constructed cycle-free like the
  # other role ARNs (shared-spaces creates it as
  # "${project}-${env}-shared-space-orchestrator-role"). SPEC-056 adds it to the
  # analytics Lake Formation admins list as a CONSTRUCTED STRING — known at plan time
  # so it doesn't break the compact() in data_lake_settings (architecture.md trap);
  # apply ordering (module.analytics depends_on module.shared_spaces) guarantees the
  # role exists first.
  shared_space_orchestrator_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-shared-space-orchestrator-role"

  # Table-builder SHARED execution role ARN (SPEC-070; consolidated from the per-verb
  # roles by user decision), constructed cycle-free like the other role ARNs
  # (module.table_builder creates it as "${project}-${env}-table-builder-execution-role").
  # Added to the analytics Lake Formation admins list as a CONSTRUCTED STRING so the
  # verbs' GetTable (check-table-absent) + CREATE (execute-ddl) resolve in the DYNAMIC
  # (per-user + per-shared-space) target databases — the model's fit for a catalog-wide
  # creator, since target DBs can't be enumerated in static Terraform. Known at plan
  # time → doesn't break the compact() admins list. module.analytics depends_on
  # module.table_builder, so the role is created BEFORE data_lake_settings references
  # it (LF rejects an unknown admin principal) — no from-scratch re-run needed.
  table_builder_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-table-builder-execution-role"

  # Table-share SHARED execution role ARN (SPEC-092; one role for all five verbs, user
  # decision mirroring the table-builder). Added to the analytics Lake Formation admins
  # list as a CONSTRUCTED STRING — known at plan time so it's compact()-safe — because
  # the recipient databases are DYNAMIC (per-user + per-shared-space): check-target-absent
  # Describes and create-table CREATEs in DBs static Terraform can't enumerate.
  # module.analytics depends_on module.table_share, so the role exists BEFORE
  # data_lake_settings references it (LF rejects an unknown admin principal).
  table_share_execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-table-share-execution-role"

  # Notifications-writer role ARN (SPEC-058), constructed cycle-free like the role ARNs
  # above (module.notifications creates it as "${project}-${env}-notifications-writer-role").
  # Passed to module.data so the user-space bucket policy can EXCLUDE it from the
  # data-access Deny — the single writer read-modify-writes {username}/user_settings/
  # notifications.json, and without the exclusion the resource-policy Deny would override
  # the writer's identity-policy Allow. Constructed string (not module.notifications'
  # output) so it's known at plan time; apply ordering (data before notifications, via
  # module.notifications depends_on module.data) is preserved.
  notifications_writer_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-notifications-writer-role"

  # Notifications queue ARN/URL (SPEC-058), constructed cycle-free like the role ARNs
  # above (module.notifications creates it as "${project}-${env}-notifications-requests.fifo").
  # SPEC-061 feeds these into module.shared_spaces — the FIRST trusted producer: the
  # ARN scopes the orchestrator role's sqs:SendMessage, the URL is the verb Lambdas'
  # NOTIFICATIONS_QUEUE_URL. Constructed strings (not module.notifications' outputs) so
  # they're KNOWN AT PLAN TIME and don't force a shared_spaces→notifications dependency
  # (architecture.md "unknown ARN" discipline); IAM never validates that the queue
  # exists, so no apply ordering is needed (same pattern as the portal role's enqueue).
  notifications_queue_name = "${var.project_name}-${var.environment}-notifications-requests.fifo"
  notifications_queue_arn  = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.notifications_queue_name}"
  notifications_queue_url  = "https://sqs.${var.aws_region}.amazonaws.com/${data.aws_caller_identity.current.account_id}/${local.notifications_queue_name}"

  # LF registration role ARN (SPEC-032), constructed cycle-free like the role ARNs
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

  # Post-confirmation Lambda exec role ARN (SPEC-033), constructed the same
  # cycle-free way as the portal/deploy roles. The auth module creates this role as
  # "${project_name}-${environment}-post-confirmation-role"; analytics adds it as a
  # Lake Formation admin. It MUST be a constructed string (not module.auth's output)
  # so the value is KNOWN AT PLAN TIME: when it flowed through module.auth's output it
  # was unknown during the apply that creates the role, and an unknown inside the
  # compact() in the LF data-lake settings caused OpenTofu to silently drop the admin
  # change — the role never became an LF admin and provisioning grants failed. Apply
  # ordering (auth -> data -> analytics) still guarantees the role exists first.
  post_confirmation_exec_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-post-confirmation-role"
}

module "app" {
  source = "./modules/app"

  project_name = var.project_name
}

module "base" {
  source = "./modules/base"

  project_name      = var.project_name
  github_repo       = var.github_repo
  state_bucket      = var.state_bucket
  state_lock_table  = var.state_lock_table
  aws_region        = var.aws_region
  static_bucket_arn = module.app.static_assets_bucket_arn

  # Constructed (not module.data outputs) so base has no dependency on data.
  user_space_bucket_arn       = "arn:aws:s3:::${local.user_space_bucket_name}"
  portal_role_arn             = local.portal_role_arn
  lambda_artifacts_bucket_arn = local.lambda_artifacts_bucket_arn
  athena_admin_bucket_arn     = local.athena_admin_bucket_arn

  # Shared-space control-plane (SPEC-050): the bucket ARN scopes the deploy role's
  # s3:* on Bucket 2; the rest of the SPEC-050 deploy grants are scoped by name
  # pattern (${project_name}-*-shared-space-*) inside the policy template.
  shared_space_bucket_arn = local.shared_space_bucket_arn
}

module "auth" {
  source = "./modules/auth"

  project_name          = var.project_name
  environment           = var.environment
  app_url               = var.app_url
  cognito_domain_prefix = var.cognito_domain_prefix

  # SPEC-033 post-confirmation Lambda inputs. account_id/region scope the exec
  # role's Glue ARNs; portal_role_arn (constructed, cycle-free) is the LF grant
  # target the Lambda receives via env var.
  aws_region      = var.aws_region
  account_id      = data.aws_caller_identity.current.account_id
  portal_role_arn = local.portal_role_arn

  # SPEC-056: drives the ten custom:shared_space_1..N user-pool attributes + the
  # Identity-Pool shared_space_1..N principal-tag mappings.
  max_shared_memberships = var.max_shared_memberships

  # The deploy role grants itself the cognito-idp permissions (modules/base
  # policies). Without this ordering, Tofu's parallel apply can call
  # CreateUserPool before that grant takes effect, failing with AccessDenied.
  # Force the base policy to settle before any Cognito resource is created.
  depends_on = [module.base]
}

module "data" {
  source = "./modules/data"

  project_name           = var.project_name
  app_url                = var.app_url
  user_space_bucket_name = local.user_space_bucket_name
  portal_role_name       = local.portal_role_name
  deploy_role_arn        = local.deploy_role_arn

  # Excluded from the bucket-policy data-access Deny so Lake Formation (assuming
  # this role) can read the registered location when serving Athena queries.
  lf_registration_role_arn = local.lf_registration_role_arn

  # SPEC-051: also excluded from the Deny so the shared-space orchestrator can write
  # each member's per-user cache ({username}/user_settings/shared-connections.json).
  # Constructed string (locals) — known at plan; the role is created in
  # module.shared_spaces, but a bucket-policy condition only needs the ARN string.
  shared_space_orchestrator_role_arn = local.shared_space_orchestrator_role_arn

  # SPEC-058: also excluded from the Deny so the notifications-writer can read-modify-write
  # each user's {username}/user_settings/notifications.json. Constructed string (locals) —
  # known at plan; the role is created in module.notifications.
  notifications_writer_role_arn = local.notifications_writer_role_arn

  # Identity Pool ID from auth — used as the portal role's trust audience and the
  # pool's authenticated-role binding. Dependency stays one-directional: data -> auth.
  identity_pool_id = module.auth.identity_pool_id

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

# Analytics foundation (SPEC-032): shared Athena workgroup + admin-only results
# bucket. Phase 1 is this additive infrastructure; Phase 2 adds Lake Formation
# bootstrap, hybrid-mode registration of the user-space bucket, and the portal
# role's Glue/Athena/LF policy (which will pull in module.data's bucket/role and
# the principal-tag key). Names are computed in locals above and passed in.
module "analytics" {
  source = "./modules/analytics"

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

  # SPEC-033: the post-confirmation Lambda's exec role, added as a Lake Formation
  # admin so it can issue per-database grants. Constructed string (see locals above)
  # — NOT module.auth's output — so it's known at plan time; otherwise the unknown
  # value broke the compact() in the LF admins list and the grant silently dropped.
  lambda_provisioner_role_arn = local.post_confirmation_exec_role_arn

  # SPEC-056: add the shared-space orchestrator role as a Lake Formation admin so it
  # can later GrantPermissions on shared DBs + DATA_LOCATION_ACCESS on the shared
  # location. Constructed string (locals above) — known at plan time so it doesn't
  # break the compact() admins list; module.shared_spaces in depends_on guarantees
  # the role exists before this sets data_lake_settings.
  shared_space_orchestrator_role_arn = local.shared_space_orchestrator_role_arn

  # SPEC-070: add the table-builder shared execution role as a Lake Formation admin so
  # its verbs can Describe (check-table-absent) + CREATE (execute-ddl) tables in the
  # dynamic per-user + per-shared-space target databases. Constructed string (locals
  # above) — known at plan time so it's compact()-safe.
  table_builder_execution_role_arn = local.table_builder_execution_role_arn

  # SPEC-092: add the table-share shared execution role as a Lake Formation admin for
  # the same reason — its verbs Describe (check-target-absent) + CREATE (create-table)
  # tables in the dynamic recipient databases. Constructed string (locals above).
  table_share_execution_role_arn = local.table_share_execution_role_arn

  # Ordering: base grants the deploy role its Athena/Glue/LF/admin-bucket perms;
  # data creates the user-space bucket + portal role that analytics registers in LF
  # and attaches the analytics policy to; shared_spaces + table_builder + table_share
  # create the orchestrator/execution roles added to the LF admins list (they must
  # exist before data_lake_settings references them — LF rejects an unknown admin
  # principal). Force all to settle first.
  depends_on = [module.base, module.data, module.shared_spaces, module.table_builder, module.table_share]
}

# Shared-space foundation (SPEC-050): Bucket 2 + the async provisioning control
# plane (FIFO SQS -> EventBridge Pipe -> Step Function -> provisioner Lambda) under a
# single privileged orchestrator role. Plumbing only — no access model, no action
# semantics (SPEC-056 + SPEC-051->055). Standalone-deployable: every cross-module ARN
# it references (the admin registry bucket, its own resources) is a constructed string
# in the module's locals, so it plans without analytics/data resource attributes.
module "shared_spaces" {
  source = "./modules/shared-spaces"

  project_name             = var.project_name
  environment              = var.environment
  aws_region               = var.aws_region
  account_id               = data.aws_caller_identity.current.account_id
  shared_space_bucket_name = local.shared_space_bucket_name
  athena_admin_bucket_name = local.athena_admin_bucket_name
  app_url                  = var.app_url

  # SPEC-051: the orchestrator writes each member's per-user cache into the
  # user-space bucket; it also targets the shared portal role in per-DB LF grants.
  user_space_bucket_name = local.user_space_bucket_name

  # SPEC-056: the membership-slot count + the portal role this module attaches the
  # membership inline policy + sqs:SendMessage + shared delete-denies to.
  max_shared_memberships = var.max_shared_memberships
  portal_role_name       = local.portal_role_name

  # SPEC-056 trusted-actor binding: the provisioner Lambda verifies caller ID tokens
  # against the pool JWKS (env vars). Module.auth outputs (one-directional dep: auth
  # applies before data, which this module already depends on).
  user_pool_id  = module.auth.user_pool_id
  app_client_id = module.auth.user_pool_client_id

  # SPEC-061: the FIRST trusted notifications producer. The verb Lambdas emit a SPEC-058
  # `create` notification at each lifecycle terminal outcome — the ARN scopes the
  # orchestrator role's sqs:SendMessage; the URL is the verbs' NOTIFICATIONS_QUEUE_URL.
  # Constructed strings (above) so this module still plans standalone.
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # base grants the deploy role its SQS/Pipes/Step-Functions/Lambda/IAM/logs/S3
  # perms for this module; data creates the portal role this module attaches the
  # membership policy to. Force both to settle first (first-apply propagation +
  # role-exists ordering, as analytics does).
  depends_on = [module.base, module.data]
}

# Notifications write pipeline (SPEC-058): a FIFO SQS queue that triggers a single
# notifications-writer Lambda directly (SQS event-source mapping — no Pipe, no Step
# Function). The writer is the only writer of each user's notifications.json in the
# existing user-space bucket. Standalone-deployable: cross-module ARNs are constructed
# strings in the module's locals. The deploy-role grants this module needs landed +
# applied in SPEC-058 PR 1/2, so no in-module time_sleep propagation guard is required.
module "notifications" {
  source = "./modules/notifications"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # The writer reads/writes {username}/user_settings/notifications.json in Bucket 1.
  user_space_bucket_name = local.user_space_bucket_name

  # The portal role this module attaches the sqs:SendMessage inline policy to, by name.
  portal_role_name = local.portal_role_name

  # Actor binding (FR-005): the writer verifies caller ID tokens against the pool JWKS
  # for user-originated actions. Module.auth outputs (one-directional dep: auth applies
  # before data, which this module already depends on).
  user_pool_id  = module.auth.user_pool_id
  app_client_id = module.auth.user_pool_client_id

  # base grants the deploy role its SQS/Lambda/event-source-mapping/IAM/logs perms for
  # this module (SPEC-058 PR 1/2, already applied); data creates the portal role this
  # module attaches the enqueue policy to. Force both to settle first.
  depends_on = [module.base, module.data]
}

# Table-builder control plane (SPEC-066): a DEDICATED FIFO SQS → EventBridge Pipe →
# Step Function pipeline orchestrating five single-task verb Lambdas
# (validate-authorize → check-table-absent → inspect-source → infer-schema →
# execute-ddl) that turn a folder of files into a Glue/Athena external table. Mirrors
# the shared-spaces control-plane PATTERN with PER-VERB least-privilege roles.
# Foundation only here (plumbing + Lambda stubs); the request contract + action
# semantics land in SPEC-067→070. Standalone-deployable: cross-module ARNs are
# constructed strings passed from root locals. The deploy-role grants this module
# needs landed + applied in SPEC-066 PR1, so no in-module time_sleep guard is required.
module "table_builder" {
  source = "./modules/table-builder"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # Source-data buckets (read by inspect/infer/execute verbs) + the admin bucket
  # (shared-spaces registry for shared authz, SPEC-067; Athena results, SPEC-070).
  # Constructed names (not module outputs) so this module plans standalone.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name
  admin_bucket_name        = local.athena_admin_bucket_name

  # The analytics workgroup execute-ddl runs the CREATE in (wired in SPEC-070).
  athena_workgroup = local.athena_workgroup_name

  # SPEC-067: the portal role this module attaches the sqs:SendMessage enqueue policy
  # to (by name), and the Cognito pool/client validate-authorize verifies tokens with.
  portal_role_name = local.portal_role_name
  user_pool_id     = module.auth.user_pool_id
  app_client_id    = module.auth.user_pool_client_id

  # SPEC-072: the SPEC-058 notifications queue every verb emits its outcome to (the ARN
  # scopes each verb role's sqs:SendMessage; the URL is their NOTIFICATIONS_QUEUE_URL).
  # Constructed-string locals (known at plan, cycle-free — same as shared_spaces above).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # base grants the deploy role its table-builder perms (SPEC-066 PR1, already
  # applied); data creates the portal role this module attaches the enqueue policy to.
  # Settle those first. NOTE: this module is ordered BEFORE module.analytics (which
  # depends_on it) so the shared execution role EXISTS before analytics adds it to the
  # Lake Formation admins list — LF rejects an unknown admin principal, so the role
  # must be created first (same reason module.shared_spaces precedes analytics). The
  # verbs read the analytics-owned catalog only at RUNTIME, by which point the full
  # apply has created it.
  depends_on = [module.base, module.data]
}

# Table-share control plane (SPEC-088): a DEDICATED FIFO SQS → EventBridge Pipe →
# Standard Step Function pipeline orchestrating five single-task verb Lambdas
# (validate-authorize → inspect-source → Map(recipients): check-target-absent →
# copy-objects → create-table) that copy a table's data files into recipient spaces
# and create a clone table in each recipient database. Mirrors the table-builder
# control-plane PATTERN with ONE shared execution role (logs-only at this stage;
# grants land with SPEC-089→092). Foundation only here (plumbing + Lambda stubs);
# decision record: docs/table-share-architecture.md. Standalone-deployable: names
# derive from {project}-{environment} inside the module. The deploy-role grants this
# module needs landed + applied in SPEC-088 PR1, so no in-module time_sleep guard is
# required. SPEC-092: the shared execution role is on the analytics LF admins list
# (module.analytics depends_on module.table_share for the role-exists ordering).
module "table_share" {
  source = "./modules/table-share"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # SPEC-089: the portal role this module attaches the sqs:SendMessage enqueue
  # policy to (by name), the Cognito pool/client validate-authorize verifies tokens
  # with, and the admin bucket holding the shared-spaces registry (source authz +
  # recipient-space existence — read-only).
  portal_role_name  = local.portal_role_name
  user_pool_id      = module.auth.user_pool_id
  app_client_id     = module.auth.user_pool_client_id
  admin_bucket_name = local.athena_admin_bucket_name

  # SPEC-090: source LOCATIONs must resolve inside one of the two data buckets;
  # inspect-source lists them for the copy plan (constructed names — plans standalone).
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name

  # SPEC-092: the analytics workgroup create-table runs the recipient CREATE in.
  athena_workgroup = local.athena_workgroup_name

  # base grants the deploy role its table-share perms (SPEC-088 PR1, already
  # applied); data creates the portal role this module attaches the enqueue policy
  # to. Settle both first.
  depends_on = [module.base, module.data]
}
