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
  # The CSP's connect-src must allow it: Amplify's authorization-code exchange
  # POSTs to https://<this>/oauth2/token, so without it sign-in cannot complete.
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
  # silently drops the change"). The module therefore exposes no role_arn output at all, so
  # there is nothing to reach for by mistake. Apply ordering is preserved by
  # module.user_directory's depends_on chain.
  #
  # Without the allowlist entry the builder's PutObject fails with an opaque AccessDenied that
  # looks like an IAM problem and is not — the bucket policy's Deny overrides its identity
  # policy's Allow. That has bitten this repo three times; modules/observability/iam.tf
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
  # exists, so no apply ordering is needed (same pattern as the portal role's enqueue).
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
  # failed to deliver to deliver the news about itself. See the comment in
  # modules/notifications/sqs.tf; the honest answer there is operator-facing and out of
  # the drain's scope. Keep this list and dlq_drain.py's SOURCES table in step — a test in
  # lambdas/control-plane-dlq-drain/ reads the module locals.tf files and fails if a fifth
  # control plane appears without being wired or explicitly excluded.
  drained_dlq_names = [
    "${var.project_name}-${var.environment}-data-quality-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-table-builder-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-table-share-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-shared-space-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-file-send-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-archive-requests-dlq.fifo",
    "${var.project_name}-${var.environment}-file-ops-requests-dlq.fifo",
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
  # It lives at root because the container reads it directly and the assembled policy below
  # reads it too. Neither belongs in a module: a root-level check cannot read a local
  # declared in one.
  csp_connect_src = join(" ", [
    "'self'",
    "https://cognito-idp.${var.aws_region}.amazonaws.com",
    # NOT reachable via cognito-idp: Amplify's authorization-code exchange POSTs to
    # https://<domain>/oauth2/token. Omitting it blocks the exchange, so the returning
    # `?code=` is never redeemed and the app sits signed-out over a live session.
    #
    # That exchange is the ONLY fetch to this host. Both redirects are navigations, which
    # connect-src does not govern, and refresh plus RevokeToken are cognito-idp calls.
    "https://${local.cognito_hosted_ui_domain}",
    "https://${local.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://${local.shared_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    local.api_origin,
  ])


  # ── The Content-Security-Policy, assembled once ─────────────────────────────
  # AT ROOT, and that placement is the decision. `connect-src` above is one
  # directive of this policy; every other directive describes the BUNDLE — what
  # it may execute, style, fetch a font from, spawn a worker as — so the two
  # halves have different owners and only this one is environment-shaped.
  #
  # NO Terraform resource reads this string any more — the distribution that did is
  # retired. It stays because it is the container's DECLARED policy: the image bakes
  # every directive but `connect-src`, and `lambdas/test_spa_image.py` asserts the baked
  # set against this computation. Delete it and the image's directives have no source of
  # truth at all, which nothing observes offline — which is the whole reason the assertion
  # exists. The container takes `csp_connect_src` from its task environment and inherits
  # the rest from this.
  #
  # ASSEMBLED FROM VARIABLES, NEVER LITERALS. A hardcoded region or bucket has
  # to be found and edited by hand during the client-environment transition
  # (docs/transition_plan.md), which is the one thing this file is read for
  # then.
  #
  # The policy is ENFORCING. It shipped report-only first, and that was not
  # ceremony: a CSP wrong about `worker-src` or `style-src` breaks the Monaco
  # editor in production and nowhere else, because no unit test observes a CSP.
  # Report-only earned its keep twice — it caught the fonts.googleapis.com
  # omission below, and it exposed that Safari will not evaluate a report-only
  # policy naming no reporting endpoint (so an unverified CSP would have looked
  # verified).
  content_security_policy = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    # 'unsafe-inline' is for STYLES ONLY, and it is monaco-editor's requirement:
    # it injects <style> elements at runtime for theming. Scripts get no such
    # allowance, which is the allowance that matters.
    #
    # fonts.googleapis.com is NOT optional: src/index.css line 1 is
    # `@import url('https://fonts.googleapis.com/css2?family=Inter…')`, and Vite
    # leaves remote @imports in the built CSS. Without this the app loses its
    # typeface site-wide — caught by the report-only pass before it ever reached
    # an enforcing policy.
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data:",
    # The Google stylesheet above serves its actual font files from gstatic.
    "font-src 'self' data: https://fonts.gstatic.com",
    # Monaco's worker is a Vite `?worker` import (SqlEditor.tsx). Vite emits a
    # same-origin chunk, but its worker shim can fall back to a blob: URL.
    "worker-src 'self' blob:",
    "connect-src ${local.csp_connect_src}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    # These two are INERT in report-only by spec — Safari says so out loud
    # ("directive is ignored when delivered in a report-only policy"). They
    # take effect only now that the policy is enforcing, so report-only never
    # tested them. Both were assessed instead of assumed:
    #   frame-ancestors — its enforcing twin X-Frame-Options: DENY was already
    #     live and nothing broke, so framing is already proven.
    #   upgrade-insecure-requests — every subresource is already https
    #     (same-origin assets, Google Fonts, AWS endpoints), so it is a no-op.
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ])

  # ── The runtime configuration document, as the container receives it ────────
  # Every key the portal's runtime-configuration classification declares, with its value. The
  # container renders /config.json from these, and it is the only renderer — the second path
  # rendered the same document from repository variables and went with the distribution.
  #
  # THE KEYS ARE NAMED HERE AND NOWHERE ELSE IN THE INFRASTRUCTURE. modules/spa renders one
  # CONFIG_<key> environment entry per map entry, so a key added to the classification is
  # wired by adding its value here — there is no second list to keep in step, and no shape in
  # which a container ships carrying only some of the document.
  #
  # `appUrl` IS THE CONTAINER'S OWN ORIGIN. Amplify builds redirectSignIn and redirectSignOut
  # from it, so a container serving any other origin sends a sign-in STARTED here somewhere
  # else: the container never receives the ?code=, and the user lands signed-out on a live
  # session. There is one origin now, so the two can no longer disagree — the rule is kept
  # because the failure it names is invisible in every offline check.
  spa_runtime_config = {
    apiBaseUrl              = local.api_origin
    appUrl                  = local.spa_origin
    awsRegion               = var.aws_region
    environment             = var.environment
    maxUploadBytes          = tostring(var.max_upload_bytes)
    cognitoUserPoolId       = module.auth.user_pool_id
    cognitoUserPoolClientId = module.auth.user_pool_client_id
    cognitoDomain           = local.cognito_hosted_ui_domain
    userSpaceBucket         = local.user_space_bucket_name
    sharedSpaceBucket       = local.shared_space_bucket_name
  }
}

module "base" {
  source = "./modules/base"

  project_name     = var.project_name
  github_repo      = var.github_repo
  state_bucket     = var.state_bucket
  state_lock_table = var.state_lock_table
  aws_region       = var.aws_region

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

  # Post-confirmation Lambda inputs. account_id/region scope the exec
  # role's Glue ARNs; portal_role_arn (constructed, cycle-free) is the LF grant
  # target the Lambda receives via env var.
  aws_region      = var.aws_region
  account_id      = data.aws_caller_identity.current.account_id
  portal_role_arn = local.portal_role_arn

  # Drives the ten custom:shared_space_1..N user-pool attributes + the
  # Identity-Pool shared_space_1..N principal-tag mappings.
  max_shared_memberships = var.max_shared_memberships

  # Both triggers attach the cpcommon layer for `observability` and emit
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

  project_name           = var.project_name
  spa_origin             = local.spa_origin
  user_space_bucket_name = local.user_space_bucket_name
  portal_role_name       = local.portal_role_name
  deploy_role_arn        = local.deploy_role_arn

  # The portal role's SECOND trust statement: the API assumes this same role to act as its
  # caller, with the same tag set read from the same claims. The key set the statement admits is
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

# The Lambda container image's registry. Nothing is deployed from it yet — the fleet still ships
# as zips with layers — so this creates a repository and stops. The image, its behaviour matrix
# and the pipeline that fills this are the rest of the arc.
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

# Shared-space foundation: Bucket 2 + the async provisioning control
# plane (FIFO SQS -> EventBridge Pipe -> Step Function -> provisioner Lambda) under a
# single privileged orchestrator role. Plumbing only — no access model, no action
# semantics. Standalone-deployable: every cross-module ARN
# it references (the admin registry bucket, its own resources) is a constructed string
# in the module's locals, so it plans without analytics/data resource attributes.
module "shared_spaces" {
  source = "./modules/shared-spaces"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name             = var.project_name
  environment              = var.environment
  aws_region               = var.aws_region
  account_id               = data.aws_caller_identity.current.account_id
  shared_space_bucket_name = local.shared_space_bucket_name
  athena_admin_bucket_name = local.athena_admin_bucket_name
  spa_origin               = local.spa_origin

  # Not used by any shared-space verb — required by the cpcommon layer's config.
  # That config resolves on FIRST READ, not at import, so a missing one is no
  # longer a cold-start crash but a failure on whichever branch reads it first. The
  # union is still what must be set; do not prune one as "unused". Wired and applied here, one
  # PR ahead of the code that imports cpcommon.
  athena_workgroup = local.athena_workgroup_name

  # The orchestrator writes each member's per-user cache into the
  # user-space bucket; it also targets the shared portal role in per-DB LF grants.
  user_space_bucket_name = local.user_space_bucket_name

  # The membership-slot count + the portal role this module attaches the
  # membership inline policy and the shared delete-denies to. Its enqueue statement is gone —
  # the API is the only writer of the request queue now.
  max_shared_memberships = var.max_shared_memberships
  portal_role_name       = local.portal_role_name

  # TBAC fix: the three control-plane execution roles get
  # DATA_LOCATION_ACCESS on the shared bucket here (the `portal-managed` tag +
  # tag-policy grants live in module.analytics). Constructed strings so the module
  # still plans standalone.
  control_plane_execution_role_arns = [
    local.table_builder_execution_role_arn,
    local.table_share_execution_role_arn,
    local.data_quality_execution_role_arn,
  ]

  # The orchestrator looks members up (AdminGetUser), which is the only reason this plane
  # still carries the pool id — it verifies nothing. Module.auth output (one-directional dep:
  # auth applies before data, which this module already depends on).
  user_pool_id = module.auth.user_pool_id

  # The first trusted notifications producer. The verb Lambdas emit a
  # `create` notification at each lifecycle terminal outcome — the ARN scopes the
  # orchestrator role's sqs:SendMessage; the URL is the verbs' NOTIFICATIONS_QUEUE_URL.
  # Constructed strings (above) so this module still plans standalone.
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The eight verbs join the structured-logging pipe. Taken from
  # module.observability's OUTPUTS rather than reconstructed, so the queue's `.fifo` suffix
  # cannot drift between producer and consumer.
  #
  # NO CYCLE, and it is worth stating because this module sits inside one of the repo's
  # trickier dependency chains: module.observability takes only locals, module.auth and
  # depends_on = [module.base] — it reaches neither shared_spaces nor analytics, so
  # shared_spaces -> observability adds an edge to an already-settled corner of the graph.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its SQS/Pipes/Step-Functions/Lambda/IAM/logs/S3
  # perms for this module; data creates the portal role this module attaches the
  # membership policy to. Force both to settle first (first-apply propagation +
  # role-exists ordering, as analytics does).
  depends_on = [module.base, module.data]
}

# Notifications write pipeline: a FIFO SQS queue that triggers a single
# notifications-writer Lambda directly (SQS event-source mapping — no Pipe, no Step
# Function). The writer is the only writer of each user's notifications.json in the
# existing user-space bucket. Standalone-deployable: cross-module ARNs are constructed
# strings in the module's locals. The deploy-role grants this module needs are already
# applied, so no in-module time_sleep propagation guard is required.
module "notifications" {
  source = "./modules/notifications"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # The writer reads/writes {username}/user_settings/notifications.json in Bucket 1.
  user_space_bucket_name = local.user_space_bucket_name

  # The identity the writer must REFUSE a `create` from. That grant is unconditioned — IAM
  # has no condition key that reaches a field inside a message body — so the boundary is a
  # runtime check against the SenderId SQS stamps, and this is the value it compares.
  # A resource attribute rather than a name: SenderId carries the unique ID and nothing else.
  portal_role_unique_id = module.data.portal_role_unique_id

  # The writer attaches the cpcommon layer for `observability` and emits
  # under service="notifications". A real reference is safe here (unlike module.auth's —
  # module.observability does not consume anything from this module), so it also orders
  # the queue's creation before the grant that scopes to it.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its SQS/Lambda/event-source-mapping/IAM/logs perms for
  # this module (already applied); data creates the portal role this
  # module attaches the enqueue policy to. Force both to settle first.
  depends_on = [module.base, module.data]
}

# Feedback: a FIFO queue and one writer Lambda, the same standalone shape as notifications
# above. No Pipe and no state machine — there is one verb, and it appends one event to one object.
#
# The queue's ONLY writer is module.api's execution role. The portal role has no statement naming
# it, which is what makes a feedback record attributable: on the user plane the browser could
# write one directly, under whatever username it chose.
module "feedback" {
  source = "./modules/feedback"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # The writer appends one object per day under this bucket's `feedback/` prefix. No lifecycle
  # rule expires it, and a test asserts no expiring rule's prefix could ever match it.
  admin_bucket_name = local.athena_admin_bucket_name

  # The writer attaches the cpcommon layer for `observability` and emits under service="feedback".
  # A real reference is safe here (module.observability consumes nothing from this module), so it
  # also orders the logs queue's creation before the grant that scopes to it.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its SQS/Lambda/event-source-mapping/IAM/logs perms for this
  # module — applied in its own PR, ahead of these resources.
  depends_on = [module.base]
}

# Table-builder control plane: a DEDICATED FIFO SQS → EventBridge Pipe →
# Step Function pipeline orchestrating five single-task verb Lambdas
# (validate-authorize → check-table-absent → inspect-source → infer-schema →
# execute-ddl) that turn a folder of files into a Glue/Athena external table. Mirrors
# the shared-spaces control-plane PATTERN with PER-VERB least-privilege roles.
# Foundation only here (plumbing + Lambda stubs); the request contract + action
# semantics land with the verbs. Standalone-deployable: cross-module ARNs are
# constructed strings passed from root locals. The deploy-role grants this module
# needs are already applied, so no in-module time_sleep guard is required.
module "table_builder" {
  source = "./modules/table-builder"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # Source-data buckets (read by inspect/infer/execute verbs) + the admin bucket
  # (shared-spaces registry for shared authz; Athena results).
  # Constructed names (not module outputs) so this module plans standalone.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name
  admin_bucket_name        = local.athena_admin_bucket_name

  # The analytics workgroup the execute-ddl verb runs its CREATE in.
  athena_workgroup = local.athena_workgroup_name


  # The notifications queue every verb emits its outcome to (the ARN
  # scopes each verb role's sqs:SendMessage; the URL is their NOTIFICATIONS_QUEUE_URL).
  # Constructed-string locals (known at plan, cycle-free — same as shared_spaces above).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The five verbs join the structured-logging pipe. From module.observability's
  # OUTPUTS rather than reconstructed, so the queue's `.fifo` suffix cannot drift between
  # producer and consumer. No cycle: observability takes only locals, module.auth
  # and depends_on = [module.base].
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its table-builder perms (already
  # applied); data creates the portal role this module attaches the enqueue policy to.
  # Settle those first. NOTE: this module is ordered BEFORE module.analytics (which
  # depends_on it) so the shared execution role EXISTS before analytics adds it to the
  # Lake Formation admins list — LF rejects an unknown admin principal, so the role
  # must be created first (same reason module.shared_spaces precedes analytics). The
  # verbs read the analytics-owned catalog only at RUNTIME, by which point the full
  # apply has created it.
  depends_on = [module.base, module.data]
}

# Table-share control plane: a DEDICATED FIFO SQS → EventBridge Pipe →
# Standard Step Function pipeline orchestrating five single-task verb Lambdas
# (validate-authorize → inspect-source → Map(recipients): check-target-absent →
# copy-objects → create-table) that copy a table's data files into recipient spaces
# and create a clone table in each recipient database. Mirrors the table-builder
# control-plane PATTERN with ONE shared execution role (logs-only at this stage;
# grants land with the verbs). Foundation only here (plumbing + Lambda stubs);
# decision record: lambdas/info/planes/table-share.md. Standalone-deployable: names
# derive from {project}-{environment} inside the module. The deploy-role grants this
# module needs are already applied, so no in-module time_sleep guard is
# required. The shared execution role is on the analytics LF admins list
# (module.analytics depends_on module.table_share for the role-exists ordering).
module "table_share" {
  source = "./modules/table-share"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  user_pool_id      = module.auth.user_pool_id
  admin_bucket_name = local.athena_admin_bucket_name

  # Source LOCATIONs must resolve inside one of the two data buckets;
  # inspect-source lists them for the copy plan (constructed names — plans standalone).
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name

  # The analytics workgroup create-table runs the recipient CREATE in.
  athena_workgroup = local.athena_workgroup_name

  # The notifications queue the verbs emit sender + recipient
  # outcome notifications to — the ARN scopes the execution role's sqs:SendMessage,
  # the URL is the verbs' NOTIFICATIONS_QUEUE_URL. Constructed-string locals (known
  # at plan, cycle-free — same as shared_spaces / table_builder).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The five verbs join the structured-logging pipe. From module.observability's
  # OUTPUTS rather than reconstructed, so the FIFO `.fifo` suffix cannot drift between
  # producer and consumer.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its table-share perms (already
  # applied); data creates the portal role this module attaches the enqueue policy
  # to. Settle both first.
  depends_on = [module.base, module.data]
}

# File-send control plane: a DEDICATED FIFO SQS → EventBridge Pipe → Standard
# Step Function pipeline that copies a user's files and folders into another person's or
# space's shared_files/ inbox. The browser cannot write into another user's prefix — that
# is the isolation model working — so sending needs a privileged path, exactly as table
# share did.
#
# ITS OWN PLANE, NOT A MODE OF TABLE SHARE. The two share an ALGORITHM (cpcommon.transfer)
# and nothing else: different request contract, different authorization question,
# different failure vocabulary. One queue and one DLQ under two unrelated user features
# would let a malformed send dead-letter someone's table share.
#
# The plane and its front door. Nothing is listed or copied by the front door itself. Decision record: lambdas/info/planes/file-send.md.
# Standalone-deployable: names derive from {project}-{environment} inside the module. The
# deploy-role grants this module needs are already applied, so no in-module
# time_sleep guard is required. NOT on the analytics LF admins list — this plane creates no
# table and runs no DDL — so module.analytics does not depend on it.
module "file_send" {
  source = "./modules/file-send"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  user_pool_id      = module.auth.user_pool_id
  admin_bucket_name = local.athena_admin_bucket_name

  # The two data buckets a send moves between. Set as env on every verb; the S3 grants on
  # them arrive with the verbs that need them.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name

  # The notifications queue the pre-verb failure path emits to. The ARN
  # scopes the execution role's sqs:SendMessage, the URL is the verbs'
  # NOTIFICATIONS_QUEUE_URL. Constructed-string locals (known at plan, cycle-free).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The verbs join the structured-logging pipe. From module.observability's
  # OUTPUTS rather than reconstructed, so the FIFO `.fifo` suffix cannot drift between
  # producer and consumer.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its file-send perms (already applied); data
  # creates the portal role this module attaches the enqueue policy to. Settle both first.
  depends_on = [module.base, module.data]
}

# File-operations control plane: a DEDICATED FIFO SQS → EventBridge Pipe → Standard Step
# Function pipeline running single-task verb Lambdas on ONE shared execution role. The
# SEVENTH plane, and the one whose absence is felt daily rather than one enabling a new
# feature: recursive folder copy, move and delete are the last bulk data operations this
# product performs in the BROWSER.
#
# The plane and its front door — the plumbing, the request contract, the per-space lock and
# validate-authorize. Nothing is listed, planned, copied or deleted yet, and the execution
# role holds NO grant on either data bucket; a test asserts the rendered policy names
# neither, so the grant cannot arrive early and unreviewed.
#
# ITS OWN QUEUE AND ITS OWN DLQ, for file-send's recorded reason: one queue under two
# unrelated user features would let a malformed file operation dead-letter someone's send.
#
# NOT on the analytics LF admins list — this plane creates no table and runs no DDL — so
# module.analytics does not depend on it. It passes no CSP input and no CORS origin either:
# the browser has no relationship with it at all now: the API writes the request queue.
#
# base grants the deploy role its file-ops perms; data creates the portal role this module
# attaches the enqueue policy to. Settle both first.
module "file_ops" {
  source = "./modules/file-ops"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  admin_bucket_name = local.athena_admin_bucket_name

  # The two data buckets a file operation moves between. Set as env on every verb so the
  # domain layer can resolve a space; the S3 grants on them arrive with the verbs that
  # actually touch bytes.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name

  # The notifications queue the pre-verb failure path emits to. The ARN scopes the
  # execution role's sqs:SendMessage, the URL is the verbs' NOTIFICATIONS_QUEUE_URL.
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The verbs join the structured-logging pipe. From module.observability's OUTPUTS rather
  # than reconstructed, so the FIFO `.fifo` suffix cannot drift between producer and
  # consumer.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  depends_on = [module.base, module.data]
}

# Archive control plane + the archive bucket: a DEDICATED FIFO SQS → EventBridge
# Pipe → Standard Step Function pipeline running single-task verb Lambdas on ONE shared
# execution role, plus Bucket 5 — the vault. ONE plane serves both archive and restore,
# branching on `mode`, because the two share the bucket, the role, the key layout and the
# receipt (the table-builder's create/refresh branch is the precedent).
#
# The vault bucket, the plane and its front door. Decision record:
# lambdas/info/planes/archive.md.
#
# THE BROWSER HAS NO RELATIONSHIP WITH THE ARCHIVE BUCKET: no CORS configuration, no
# connect-src entry, and the portal role holds zero statements naming it. Its only browser
# surface is nothing — the API writes the request queue on the caller's behalf.
#
# NOT on the analytics LF admins list — this plane creates no table and runs no DDL — so
# module.analytics does not depend on it.
module "archive" {
  source = "./modules/archive"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # The bucket this module creates, and the two ARNs its bucket policy admits. The
  # execution-role ARN is the CONSTRUCTED twin from locals — the same string module.data
  # gets for the user-space allowlist, so the two cannot drift.
  archive_bucket_name = local.archive_bucket_name
  deploy_role_arn     = local.deploy_role_arn
  execution_role_arn  = local.archive_execution_role_arn

  admin_bucket_name = local.athena_admin_bucket_name

  # The two space buckets an archive moves OUT of. Set as env on every verb; the S3 grants
  # on them arrive with the verbs that need them.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name

  # The notifications queue the pre-verb failure path emits to. The ARN
  # scopes the execution role's sqs:SendMessage, the URL is the verbs'
  # NOTIFICATIONS_QUEUE_URL. Constructed-string locals (known at plan, cycle-free).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The verbs join the structured-logging pipe. From module.observability's
  # OUTPUTS rather than reconstructed, so the FIFO `.fifo` suffix cannot drift between
  # producer and consumer.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url

  # base grants the deploy role its archive perms (including the bucket) BEFORE this
  # module's resources land; data creates the portal role this module attaches the enqueue
  # policy to. Settle both first.
  depends_on = [module.base, module.data]
}

# Data-quality control plane: a DEDICATED FIFO SQS → EventBridge Pipe →
# Standard Step Function pipeline orchestrating nine single-task verb Lambdas around ONE
# Athena profile query (validate-authorize → inspect-source → create-temp-tables →
# start-profile-query → [Wait → check-query → Choice] → byte-scan → assemble-report →
# drop-temp-tables). Diagnoses a file or folder and writes a report; it NEVER modifies a
# source. Mirrors the table-builder/table-share control-plane PATTERN with ONE shared
# execution role — logs-only at this stage (S3, Glue, Athena and LF admin land with
# the verbs). Foundation only here (plumbing + Lambda stubs); decision record:
# lambdas/info/planes/data-quality.md.
#
# The engine is ATHENA, not Lambda: a full pass over a 250 GB source is impossible inside
# Lambda's 900 s ceiling, so a short Lambda STARTS the query and the STATE MACHINE waits
# (Standard executions run for up to a year). It runs in the SHARED portal Athena
# workgroup — the same one table-builder/table-share use. This plane originally had
# its own workgroup to escape the portal workgroup's 10 GiB scan cutoff, but Athena ties
# Lake Formation to the workgroup: a dedicated workgroup fails LF's Create/Describe checks
# even for an LF-admin role (measured live). TRADEOFF: the portal workgroup's scan
# cutoff now applies to data-quality's profile queries, so a check over a source larger
# than the cutoff fails until it is raised — tracked with the deferred DML-timeout quota
# increase (lambdas/info/planes/data-quality.md).
#
# Standalone-deployable: names derive from {project}-{environment} inside the module. The
# deploy-role grants this module needs are already applied, so no in-module
# time_sleep guard is required. The shared execution role is added to the analytics
# LF admins list (module.analytics will depend_on this module for the role-exists
# ordering, exactly as it does for table_builder / table_share).
module "data_quality" {
  source = "./modules/data-quality"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  # Source + report buckets, and the admin bucket (shared-spaces registry for shared
  # authorization by the verbs; this workgroup's FALLBACK Athena result location).
  # Constructed names (not module outputs) so this module plans standalone.
  #
  # These are wired now — before any verb uses them — because every verb attaches the
  # cpcommon layer and its config requires them. That requirement moved from
  # import to FIRST READ, so a verb missing one no longer crashes at cold start — it
  # fails on whichever branch reads it. The union is still what must be set; do not prune one
  # as "unused". Same reason the Cognito pair is passed here.
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name
  admin_bucket_name        = local.athena_admin_bucket_name


  # Run every verb's Athena queries in the SHARED portal workgroup (the same
  # one table-builder/table-share use) — Athena ties Lake Formation to the workgroup, so a
  # dedicated workgroup fails LF's table Create/Describe even for an LF-admin role.
  athena_workgroup = local.athena_workgroup_name

  # The notifications queue the verbs emit outcomes to. Constructed-
  # string locals (known at plan, cycle-free — same as the other control planes).
  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # base grants the deploy role its data-quality perms (already applied);
  # data creates the portal role this module attaches the enqueue policy to, and the
  # user-space bucket the reports land in. Settle both first.
  depends_on = [module.base, module.data]
  # The nine verbs produce structured logs onto the logs queue.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url
}

# ── Control-plane DLQ drain ───────────────────────────────────────
# The one function that turns a dead-lettered request into a sentence in the actor's inbox.
# Before this, a request the pipeline refused simply vanished: no verb ran, so no failure
# notification fired, and the person who made it waited for a result that never came.
#
# The four DLQ ARNs are CONSTRUCTED STRINGS (locals below), not the arc modules' outputs —
# known at plan time, so the drain's IAM policy plans cleanly and no module→module edge is
# created (the infra/info/deploy-role-iam.md "unknown ARN in list" discipline; the same reason every
# producer scopes to a constructed notifications queue ARN).
module "control_plane_dlq_drain" {
  source = "./modules/control-plane-dlq-drain"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  dlq_arns = [for name in local.drained_dlq_names : "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${name}"]

  notifications_queue_arn = local.notifications_queue_arn
  notifications_queue_url = local.notifications_queue_url

  # The drain joins the structured-logging pipe. Taken from the observability
  # module's outputs rather than reconstructed, so the queue's FIFO `.fifo` suffix cannot
  # drift between producer and consumer.
  logs_queue_arn = module.observability.logs_queue_arn
  logs_queue_url = module.observability.logs_queue_url


  # Required by the cpcommon layer's config, not used by the drain.
  # (that config resolves on FIRST READ, not at import, so a missing one is
  # no longer a cold-start crash, but a failure on whichever branch reads it
  # first. The union is still what must be set; do not prune one as "unused".)
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name
  admin_bucket_name        = local.athena_admin_bucket_name
  athena_workgroup         = local.athena_workgroup_name

  # base grants the deploy role its drain perms (already applied).
  depends_on = [module.base]
}

# The structured-logging pipe: one standard SQS logs queue and one scheduled sweep
# that lands log-foundry events as Hive-partitioned NDJSON under s3://{admin}/logs/.
module "observability" {
  source = "./modules/observability"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  admin_bucket_name = local.athena_admin_bucket_name
  admin_bucket_arn  = "arn:aws:s3:::${local.athena_admin_bucket_name}"


  # Required by the cpcommon layer's config, not used by the sweep.
  # (that config resolves on FIRST READ, not at import, so a missing one is
  # no longer a cold-start crash, but a failure on whichever branch reads it
  # first. The union is still what must be set; do not prune one as "unused".)
  user_space_bucket_name   = local.user_space_bucket_name
  shared_space_bucket_name = local.shared_space_bucket_name
  athena_workgroup         = local.athena_workgroup_name

  # base grants the deploy role its observability perms (already applied).
  depends_on = [module.base]
}

# Username directory: one scheduled Lambda that lists the user-space bucket's
# workspace prefixes once a day and publishes them as _directory/usernames.json, which the
# browser reads to suggest usernames. Not a control plane — no queue, no state
# machine, no verbs; the closest sibling is module.observability's sweep.
#
# The bucket ARN and the logs queue arrive as CONSTRUCTED STRINGS from the locals above rather
# than as module.data / module.observability outputs, so this module plans standalone and its
# IAM templates render at plan time. module.data must exist first (the builder writes into its
# bucket), which the depends_on below orders.
module "user_directory" {
  source = "./modules/user-directory"

  # The fleet's one container image, and the tag these functions are CREATED from. The tag
  # is ignored after creation — CI re-points every function on each deploy — so it is an
  # INPUT github.sha already knows rather than anything Terraform derives.
  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  user_space_bucket_name = local.user_space_bucket_name
  user_space_bucket_arn  = "arn:aws:s3:::${local.user_space_bucket_name}"

  logs_queue_arn = local.logs_queue_arn
  logs_queue_url = local.logs_queue_url

  # Required by the cpcommon layer's config, not used by the builder.
  # (that config resolves on FIRST READ, not at import, so a missing one is
  # no longer a cold-start crash, but a failure on whichever branch reads it
  # first. The union is still what must be set; do not prune one as "unused".)
  # The two Cognito variables left this list when the planes stopped verifying tokens: the
  # pool id is now lazily required by the three planes that look a recipient up, and this
  # builder is not one of them.
  shared_space_bucket_name = local.shared_space_bucket_name
  admin_bucket_name        = local.athena_admin_bucket_name
  athena_workgroup         = local.athena_workgroup_name

  # base grants the deploy role its user-directory perms (already applied);
  # data owns the bucket this writes into.
  depends_on = [module.base, module.data]
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
# test asserts that against the rendered policy. The layer resolves config lazily, so an
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
  shared_space_queue_url  = module.shared_spaces.request_queue_url
  notifications_queue_url = module.notifications.notifications_queue_url
  table_build_queue_url   = module.table_builder.table_build_queue_url
  table_share_queue_url   = module.table_share.table_share_queue_url
  data_quality_queue_url  = module.data_quality.data_quality_queue_url
  file_send_queue_url     = module.file_send.file_send_queue_url
  archive_queue_url       = module.archive.archive_queue_url
  file_ops_queue_url      = module.file_ops.file_ops_queue_url
  feedback_queue_url      = module.feedback.feedback_queue_url

  request_queue_arns = [
    module.shared_spaces.request_queue_arn,
    module.notifications.notifications_queue_arn,
    module.table_builder.table_build_queue_arn,
    module.table_share.table_share_queue_arn,
    module.data_quality.data_quality_queue_arn,
    module.file_send.file_send_queue_arn,
    module.archive.archive_queue_arn,
    module.file_ops.file_ops_queue_arn,
    module.feedback.feedback_queue_arn,
  ]

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  # Built at root from the domain variables, never derived inside the module.
  api_host        = local.api_host
  spa_origin      = local.spa_origin
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
  # The identity layer. The role is the EXISTING portal role, named by the same local the
  # Identity Pool's role attachment uses -- reusing it is what keeps the user-space bucket
  # policy's hand-maintained allowlist correct without a new entry.
  portal_role_arn        = local.portal_role_arn
  principal_tag_key      = var.principal_tag_key
  max_shared_memberships = var.max_shared_memberships

  oidc_issuer          = local.cognito_issuer
  oidc_audience        = module.auth.user_pool_client_id
  oidc_jwks_uri        = "${local.cognito_issuer}/.well-known/jwks.json"
  oidc_username_claim  = "cognito:username"
  oidc_required_claims = jsonencode({ token_use = "id" })

  # base grants the deploy role the apigateway, function, role and log-group permissions
  # BEFORE anything here lands.
  depends_on = [module.base]
}


module "network" {
  source = "./modules/network"

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


# ── The container platform ────────────────────────────────────────────────────
# The registry, the cluster, the task definition and the load balancer that serve the SPA.
# It runs the real image, which CI builds and pushes on every commit to main. It is production,
# and there is no second path: the distribution that used to serve the portal is destroyed.
#
# It takes the network's ids rather than building any of its own — the two modules are split
# because the network outlives the front door, not because the front door is optional to it.
# The task security group is the seam: created there with no rules, ruled here, because every
# one of its rules names a group this module owns.
module "spa" {
  source = "./modules/spa"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  # Passed rather than read from a data source inside the module: the depends_on below would
  # defer any data source there, and a deferred read is a hard error where it feeds a for_each.
  account_id = data.aws_caller_identity.current.account_id

  vpc_id                         = module.network.vpc_id
  public_subnet_ids              = module.network.public_subnet_ids
  private_subnet_ids             = module.network.private_subnet_ids
  task_security_group_id         = module.network.task_security_group_id
  vpc_endpoint_security_group_id = module.network.vpc_endpoint_security_group_id
  s3_prefix_list_id              = module.network.s3_prefix_list_id

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

  # base grants the deploy role the ECS, ECR, load-balancer, role and log-group permissions
  # BEFORE anything here lands; analytics creates the bucket whose policy this module writes.
  depends_on = [module.base, module.analytics]
}
