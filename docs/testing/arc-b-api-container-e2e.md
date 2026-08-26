# Arc B End-to-End Acceptance Script (SPEC-192 → 202)

**Purpose:** prove the whole API-and-container arc against deployed infrastructure, and gate
SPEC-202's **merge 2** on what it observes. This is the acceptance gate for SPEC-192 → 202
(SPEC-202 FR-009) and the regression checklist for any later change to the API, the image, the CSP or
the origins.

**Status:** ⬜ Not yet executed.

**How to read the markers.** Every section is **BLOCKING** or **non-blocking**. **"Not run" is never
"passed"**; that is the rule `security.yml` already holds for scanners, and it is the rule here.

## Run order is not a suggestion

SPEC-202 ships in two merges and this script runs **between them**. Which merge a section sits after
decides whether it can pass at all.

| Step | What |
|---|---|
| **§0, §1, §2** | Gates, instruments and fixtures. §0 is run **before merge 1** — it holds the trust-policy read-back, and it captures two ids whose Terraform outputs the merges delete. |
| **merge 1** | The retirement: the Identity Pool, the browser's last credential modules, the lint rule, the container's narrowed `connect-src`. **No allowlist and no origin changes**, so CloudFront remains a working rollback. |
| **§3** | Fresh sign-in. |
| **§5 → §7 → §8** | One continuous DevTools recording, `Preserve log` on, never closing the tab. |
| **§4** | Count that recording. It runs **last of the four**, because the `sqs.` row is meaningless over a window with no enqueue in it, and the `cognito-identity.` row is impossible before merge 1. |
| **§6, §9** | Deep link and the clocks; Safari and 400px. |
| **§10** | The rollback rehearsal — after merge 1, **before merge 2**. The only window in which it is both meaningful and possible. |
| **§11** | The merge-1 consequences: the IAM simulation, the pool gone, one trust statement, the lint rule red on a violation. |
| **merge 2** | The narrowing and the destroy. **Does not open until every BLOCKING item above is recorded PASS.** After it applies there is no rollback. |
| **§12** | The merge-2 consequences: the distribution gone, §3 re-run against the narrowed Cognito lists, §5 steps 2–3 re-run against the narrowed bucket CORS. |
| **§13, §14, §15** | What one session cannot settle; cleanup; the Execution Log. |

**§A stands outside that order.** Runtime configuration (SPEC-192) shipped against the existing
CloudFront distribution, so its checks are runnable today and do not wait for merge 1.

**§B stands outside it as well.** The container platform (SPEC-193) is the thing the merges later
move traffic *onto*; its own verification runs against a placeholder image nobody is pointed at, and
proves the platform rather than the product.

---

## A. Runtime configuration (SPEC-192) — runnable NOW, before any of the above

The only section of this script that does not wait for the container. It runs against the CloudFront
distribution as it stands, and **two of its five steps (A.2, A.3) require publishing a
deliberately broken `config.json`**, while A.1 publishes a valid changed one — so run them in one
sitting and restore at the end.

**Already discharged (2026-08-24), recorded so they are not re-run blindly:** `GET /config.json`
returns **200 / `application/json` / `Cache-Control: no-store` / `version: 1`** with all 20 keys, a
second request is still `x-cache: Miss from cloudfront`, and after the switchover the app boots with
**exactly one** `config.json` fetch per page load (Performance API), zero console errors and **no
configuration alert** — the observable proving the document's four Cognito values reached
`Amplify.configure()`, since their absence renders one.

**A.1 — The promotion property. BLOCKING.** This is what the whole spec exists for, and it is
invisible from the UI.

1. Note the current `VITE_MAX_UPLOAD_BYTES` repository variable. Change it to `1048576` (1 MiB).
2. Re-run **Deploy App** from the Actions tab with **no source change**.
3. Load the portal, open DevTools → Network, and read `config.json` on the **first** request:
   `maxUploadBytes` must be `1048576`. A stale value here is the failure the spec exists to prevent.
4. Confirm it took effect: try to upload a file larger than 1 MiB. It must be refused client-side
   before any request.
5. Restore the variable and re-run Deploy App.

**A.2 — The hard-failure path. BLOCKING, and the only way to see it in a production build** (the dev
fallback hides it everywhere else).

1. Download the live document: `aws s3 cp s3://<static-bucket>/config.json .`
2. Delete the `userSpaceBucket` key. Re-upload with
   `--cache-control 'no-store' --content-type 'application/json'`.
3. Load the portal in a fresh tab. Confirm **all** of:
   - the boot-failure screen renders — "The portal could not start" — and **no route mounts** (no
     header, no nav, no file browser; `/files` and `/query` render it too);
   - the console holds **one** `[config] the portal could not start (missing-required): userSpaceBucket`;
   - **no VALUE from the document appears anywhere in the console** — grep the output for the bucket
     name, the user-pool id and the workgroup. A key NAME is the intended diagnostic; a value is the
     app printing its own configuration to a user.
4. **Restore the original document** and confirm the portal boots.

**A.3 — The unparseable path. BLOCKING.** Upload the app's own `index.html` to the `config.json` key
(same headers). The portal must render the **same** boot failure with reason `unparseable` — not a
working app with everything undefined. This is the shape a deployment that never published the
document actually returns, because the distribution answers a missing object with `index.html` under
a **200**. Restore afterwards.

**A.4 — Fresh sign-in, end to end, from a private window. BLOCKING.** Sign out, open a private
window, and complete a full Hosted UI round trip. A warm session cannot exercise this: the browser
arrives already authenticated and a bootstrap that configured Amplify after the first render would
look identical. This is the same shape as the omitted Hosted UI host that broke fresh sign-in for a
day.

**A.5 — The `no-store` header, read directly. Non-blocking.** Read `Cache-Control` off the response
in the Network panel. Do **not** try to infer it from a reload: `/config.json` has its own
`Managed-CachingDisabled` behaviour, so the edge caches nothing whether or not the header is present,
and no observation distinguishes the two. Edge freshness is a property of the cache policy; the
header is what a container will emit once SPEC-194 lands.

---

## B. The container platform (SPEC-193) — runnable when PR 5/6 has applied, outside the merge order

Like §A, this section stands outside the merge order: it proves the platform SPEC-194 builds on,
against a placeholder image no user is pointed at. Production is still CloudFront throughout.

**It does not restate §0's three FR-006 checks.** Those are the two origins on the app client, the
API host inside CloudFront's `connect-src`, and the API's CORS answering both origins. Run §0's
block for them; a failure there is a defect in SPEC-193 and is fixed there.

**Already discharged (2026-08-26), recorded so they are not re-run blindly:**
`curl https://api.dataquarry.app/healthz` → `{"status": "ok", "version": "<HEAD sha>"}`, and the
`api.dataquarry.app` certificate's `RenewalEligibility` flipped `INELIGIBLE` → `ELIGIBLE` once the
custom domain attached it.

**B's instruments.** §1 is written for the merge sequence and defines origins, not hosts; these are
the three values §B needs and it defines them itself. Run from the repository root — §B uses
`tofu -chdir=infra` throughout, which fails if you are already inside `infra/`.

```bash
SPA_HOST=$(tofu -chdir=infra output -raw spa_host)          # portal.<parent>, no scheme
API_HOST=$(tofu -chdir=infra output -raw api_host)          # api.<parent>, no scheme
SPA_CERT=$(tofu -chdir=infra output -raw spa_certificate_arn)

# There is no target-group output: the group is internal to the module, and the live check
# reads the DEPLOYED value rather than adding an output for one assertion.
TG_ARN=$(aws elbv2 describe-target-groups --names "$(tofu -chdir=infra output -raw ecs_cluster_name)-tg" \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
```

**B.0 — The prerequisite nothing in this repo provisions. BLOCKING, and check it BEFORE B.6.**

The placeholder push needs an identity holding `ecr:GetAuthorizationToken` (account-wide — the
action takes no resource type) plus `BatchCheckLayerAvailability`, `InitiateLayerUpload`,
`UploadLayerPart`, `CompleteLayerUpload` and `PutImage` on the repository. **The deploy role holds
none of them and that is deliberate**: it creates the registry and never writes to it, and the
pipeline that pushes on every commit arrives with SPEC-194, which owns those grants.

```bash
aws sts get-caller-identity                       # which identity is about to push
aws ecr get-login-password --region us-east-1 >/dev/null && echo 'auth ok'
```

A refusal here is not a defect in this spec — it is this step's own precondition, and it is cheaper
to discover now than half way through a build.

**B.1 — The apply. BLOCKING.**

- [ ] `Deploy Infrastructure` on `main` is green. A first-run `AccessDenied` on a newly-granted
      action is expected once; **the same action failing twice is a defect**, not propagation.
- [ ] `ecs:RegisterTaskDefinition` in particular: it is scoped by resource *type* on the strength of
      the AWS Service Reference, while the ECS developer guide still says task-definition policies
      take no resource-level permissions. If it denies, the fix is a grants PR moving it to
      `PlatformContainerTaskDefinitionGlobal`.

**B.2 — Both names resolve, each with its own certificate.**

```bash
for h in "$SPA_HOST" "$API_HOST"; do
  dig +short "$h" | head -3
  echo | openssl s_client -connect "$h:443" -servername "$h" 2>/dev/null \
    | openssl x509 -noout -subject -dates
done
```

- [ ] Each certificate's subject is the host asking for it. A single certificate answering both is
      the two-equal-subdomains failure the certificate's own precondition refuses at plan.
- [ ] `$SPA_HOST` resolves to the load balancer named by `tofu -chdir=infra output -raw alb_dns_name`
      — not to a stale one.

**B.3 — The API's span reaches the log store. BLOCKING; nothing offline can make this assertion.**

- [ ] After a `curl` of the API, `logs/service=api/year=…/data.jsonl` carries the invocation's span
      with `env` and `version` populated. This is the cold-start assertion: it proves the `cpcommon`
      layer attached, which no unit test observes.

**B.4 — The image, built for the platform the task declares.**

```bash
REPO=$(tofu -chdir=infra output -raw ecr_repository_url)
SHA=$(git rev-parse HEAD)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/amd64 -f apps/portal/Dockerfile.placeholder -t "$REPO:$SHA" .
docker push "$REPO:$SHA"
```

- [ ] `--platform linux/amd64` is not optional on an Apple Silicon machine. Without it the task fails
      with an image-manifest error that reads nothing like the architecture mismatch it is.
- [ ] `:latest` is impossible here by construction — the repository is `IMMUTABLE` and the tag is the
      sha. A tag cannot be re-pushed, so a bad build needs a new sha, not a retry.

**B.5 — Raise the service.**

```bash
gh variable set TF_VAR_spa_image_tag     --body "$SHA"
gh variable set TF_VAR_spa_desired_count --body '1'
gh workflow run 'Deploy Infrastructure'
```

**B.6 — The arc's central claim: a pull with no NAT. BLOCKING, and it must be read as a PAIR.**

```bash
CLUSTER=$(tofu -chdir=infra output -raw ecs_cluster_name)
SERVICE=$(tofu -chdir=infra output -raw ecs_service_name)
aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].[runningCount,desiredCount,events[:5].message]'

# The other half. WITHOUT THIS, a pull that succeeded through a route somebody added
# reads as proof of the endpoints, and the whole of FR-001 is unverified.
aws ec2 describe-route-tables \
  --route-table-ids $(tofu -chdir=infra output -json private_route_table_ids | jq -r '.[]') \
  --query 'RouteTables[].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId]'
```

- [ ] `runningCount == 1`, and **no `CannotPullContainerError`** in the event list.
- [ ] The private tables carry the local route and the prefix-list route, and **no `0.0.0.0/0` of any
      kind**. Assert the absence of a default route and the presence of the prefix-list one — never a
      route *count*, which the spec's own Phase 6 step 7 got wrong and FR-001 AC4 got right.
- [ ] A `ResourceInitializationError` here is NOT the pull failing — it is the log group or the task
      role. Read the message before diagnosing the network.

**B.7 — The gateway endpoint's association set.**

```bash
aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$(tofu -chdir=infra output -raw vpc_id)" \
  --query 'VpcEndpoints[?VpcEndpointType==`Gateway`].RouteTableIds'
```

- [ ] It **equals** `tofu output -json private_route_table_ids`. A gateway endpoint associated with
      the wrong table applies green, drifts nothing, and shows no symptom but a pull that hangs.

**B.8 — The front door answers.**

```bash
curl -i "https://$SPA_HOST/healthz"          # 200 through the load balancer
curl -i "http://$SPA_HOST/"                  # 301 to the https:// URL
aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --query 'TargetHealthDescriptions[].TargetHealth.State'
```

- [ ] `/healthz` returns 200 and target health is `healthy`.
- [ ] **The redirect can only be verified with `curl`.** `.app` is HSTS-preloaded, so Safari rewrites
      the scheme before the request leaves the browser and the 301 is never exercised.

**B.9 — The SPA certificate's renewal eligibility.**

```bash
aws acm describe-certificate --certificate-arn "$SPA_CERT" \
  --query 'Certificate.[DomainName,RenewalEligibility,InUseBy]'
```

- [ ] It reports `RenewalEligibility: ELIGIBLE` once the listener holds it, and `InUseBy` names the
      load balancer. `INELIGIBLE` means the certificate is attached to nothing — which is exactly
      the state it was in before this PR.

---

## 0. Gates, before anything — BLOCKING

Run this section **before merge 1 is merged.**

- [ ] `gh run list --branch main --limit 8` is green, including **Deploy Infrastructure**, **Deploy
      Lambdas** and **Deploy SPA Image**. A red deploy makes every failure below unreadable.
- [ ] **Arc A has landed** (SPEC-187 → 191). §8's file-ops row and its queue do not exist otherwise,
      and SPEC-200's `QUEUES` set-equality guard hard-fails without them.
- [ ] `curl -s $SPA_ORIGIN/healthz` returns the **same build sha as `git rev-parse HEAD`**. A stale
      task serving an old image passes most of this script and proves nothing about HEAD.
- [ ] `curl -s $API_ORIGIN/healthz` returns `200`. **Its `version` is the sha of the last commit
      that changed `lambdas/api/` — NOT HEAD.** `deploy-lambdas.yml` deploys only changed functions,
      so an unrelated commit leaves the API on its own last build; reading this as HEAD makes a
      healthy deployment look broken. (Measured 2026-08-26: the API reported `7cba61f8…` while `main`
      was six commits further on, and everything was correct.)
- [ ] **SPEC-193 FR-006's three additive changes are live. Verify them; do not add them** — a missing
      one is a defect in SPEC-193 and is fixed there, because SPEC-202 only ever narrows.
      ```bash
      # 1. Both origins on the app client, in BOTH lists.
      aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" \
        --client-id "$CLIENT_ID" --query 'UserPoolClient.[CallbackURLs,LogoutURLs]'
      # -> each list contains BOTH $SPA_ORIGIN and $CLOUDFRONT_URL (plus localhost).
      #    One entry each = the rollback is already gone; stop.

      # 2. CloudFront's connect-src names the API host — the state nobody notices
      #    until the rollback is needed.
      curl -sSI "$CLOUDFRONT_URL" | grep -io 'connect-src[^;]*'      # must contain $API_ORIGIN

      # 3. The API's CORS answers BOTH origins.
      for o in "$SPA_ORIGIN" "$CLOUDFRONT_URL"; do
        printf '%s -> ' "$o"
        curl -sSI -X OPTIONS "$API_ORIGIN/healthz" \
          -H "Origin: $o" -H 'Access-Control-Request-Method: GET' \
          | grep -i '^access-control-allow-origin' || echo 'MISSING'
      done
      ```
- [ ] **The deployed portal-role trust policy already carries SPEC-196's statement.** Merge 1 removes
      the federated one; if SPEC-196's is not *applied*, the role becomes trusted by nobody and every
      API call in the product fails. A plan is not evidence.
      ```bash
      aws iam get-role --role-name "$(basename "$PORTAL_ROLE")" \
        --query 'Role.AssumeRolePolicyDocument.Statement[].Principal'
      # -> two statements today: cognito-identity.amazonaws.com, and the API Lambda's
      #    execution role. The second MUST be present before merge 1.
      ```
- [ ] The two ids in §1 marked "record it NOW" are captured and pasted into §15. Their Terraform
      outputs are deleted by the merges; after that there is nothing left to name.

## 1. Instruments

```bash
cd infra    # every `tofu output` below is run from here

# --- origins and Cognito -------------------------------------------------
SPA_ORIGIN=$(tofu output -raw spa_origin)                  # https://portal.<parent>
API_ORIGIN=$(tofu output -raw api_origin)                  # https://api.<parent>
CLOUDFRONT_URL=$(tofu output -raw cloudfront_domain)       # the rollback, deleted in merge 2
POOL_ID=$(tofu output -raw cognito_user_pool_id)
CLIENT_ID=$(tofu output -raw cognito_user_pool_client_id)
HOSTED_UI=$(tofu output -raw cognito_domain)               # <prefix>.auth.<region>.amazoncognito.com
REGION=$(tofu output -raw aws_region)
USER_BUCKET=$(tofu output -raw s3_user_space_bucket_name)
SHARED_BUCKET=$(tofu output -raw shared_space_bucket_name)

# --- record these NOW: the merges delete the outputs ---------------------
POOL_ARN_ID=$(tofu output -raw cognito_identity_pool_id)       # merge 1 deletes this output; §11 asserts it is gone
DIST_ID=$(tofu output -raw cloudfront_distribution_id)         # merge 2 deletes this output; §12 asserts it is gone

# --- roles: NONE of these is a root output -------------------------------
# `portal_role_arn` is a LOCAL in infra/main.tf; the API Lambda's role and the SPA
# task role are internal to SPEC-193's modules. `tofu output -raw portal_role_arn`
# fails. Read the DEPLOYED values instead — which is what FR-010 asks for anyway.
API_FN=$(tofu output -raw api_function_name)
API_CFG=$(aws lambda get-function-configuration --function-name "$API_FN")
PORTAL_ROLE=$(printf '%s' "$API_CFG" | jq -r '.Environment.Variables.PORTAL_ROLE_ARN')
API_ROLE=$(printf '%s' "$API_CFG" | jq -r '.Role')

TASK_DEF=$(aws ecs describe-services \
  --cluster "$(tofu output -raw ecs_cluster_name)" \
  --services "$(tofu output -raw ecs_service_name)" \
  --query 'services[0].taskDefinition' --output text)
SPA_TASK_ROLE=$(aws ecs describe-task-definition --task-definition "$TASK_DEF" \
  --query 'taskDefinition.taskRoleArn' --output text)

# Sanity: all three must be non-empty ARNs before §11 is worth running.
printf 'portal=%s\napi=%s\nspa=%s\n' "$PORTAL_ROLE" "$API_ROLE" "$SPA_TASK_ROLE"
```

Two accounts are needed: **`arcb_owner`** and **`arcb_member`** (§5's Lake Formation step, §8's
shared-space and file-send fixtures). Both satisfy `^[a-z][a-z0-9_]{2,62}$`.

### Traps, all measured previously — read before you start

- **A hidden Chrome window pauses polling.** A healthy Athena query looks hung. Override
  `visibilityState` before §5, or keep the window frontmost.
- **`cognito-identity.` cannot read zero before merge 1.** `lib/amplify.ts` configures
  `identityPoolId` whenever the runtime key is present, so every `fetchAuthSession()` — including the
  one `getIdToken` makes on each API call — vends pool credentials. §4 is therefore a post-merge-1
  section, and running it earlier and recording PASS is the failure mode SPEC-202 exists to prevent.
- **CDP `Runtime.evaluate` is exempt from `script-src`, not from `connect-src`.** SPEC-140 measured
  the first (`new Function` reported *allowed* under `script-src 'self'`) and the rule it wrote down
  over-generalised. §7 step 3 explains what actually runs and why, and asserts on a **positive**
  violation event so a bypass reads FAIL rather than PASS.
- **An Elements-panel `<script>` never executes.** A script element created by the HTML fragment
  parser is marked non-executable, so pasting one into the DOM logs nothing — which looks exactly
  like a policy that blocked it. Do not use it.
- **Safari refuses to evaluate a report-only policy naming no reporting endpoint**, logging that the
  policy will have no effect. A Chromium harness cannot surface that, which is one reason §9 is the
  discharging pass and not a formality.
- **400px is not reachable by window resize on macOS**, and the automation's `resize_window` reports
  success while changing nothing the page sees. Use the DevTools device toolbar and assert on
  `matchMedia` (§9).
- **The laptop IAM user cannot read `dat-prod-user-space` at all** — the bucket policy allowlists the
  portal, deploy and execution roles. Anything touching a user's space goes through the portal UI or
  an assumed role.
- **Never run `tofu apply` locally.** The local identity cannot read the data buckets, so a local plan
  proposes to destroy them. `tofu output` reads state only and is safe.
- **The CloudFront distribution maps `403/404 → /index.html` with a 200.** A status code tells you
  nothing about whether an object exists. §12 asserts the *distribution* is gone, not a status.

## 2. Fixtures — build once, up front

Through the portal UI as `arcb_owner`, after merge 1 and before §3:

| Fixture | Shape | Why this shape |
|---|---|---|
| `arcb_files/small.txt` | 12 bytes, `text/plain` | The single-file copy/move/delete path |
| `arcb_files/big.bin` | **12 MiB** | Above the old `lib-storage` 5 MiB multipart threshold. Under presigned bytes it is **one** `PUT`, and the request count is the observable difference |
| `arcb_files/report.csv` | 150 rows, 4 columns | `EXPLORATION_PAGE_SIZE` is **100**, so 150 rows is the smallest fixture that can page. A ">25 rows" fixture cannot |
| `arcb_files/name.txt`, `name (1).txt` … `name (3).txt` | 4 objects | The free-name route: the answer is `name (4).txt`, in **one** API call |
| `arcb_send/` | 3 files, one nested folder | §8's file-send and file-ops fixture |
| A shared space `arcb_space` | `arcb_owner` owner, `arcb_member` added | §5's Lake Formation step and §8's shared-space plane |
| A saved query `arcb.sql` | `SELECT * FROM arcb_owner.arcb_report LIMIT 10` | §5's saved-queries round trip |
| A Glue table `arcb_report` | Built from `arcb_files/report.csv` | §5's catalog surface and §8's table planes |

---

## 3. Fresh sign-in, from a clean signed-out profile — BLOCKING

**Run this first of the browser sections, after merge 1, and in a brand-new browser profile.** An
existing session refreshes against `cognito-idp` and stays perfectly healthy while fresh sign-in is
completely broken — SPEC-140's omitted `connect-src` host did exactly that for a day, and no
signed-in check would have caught it. §12 re-runs this whole section after merge 2, which is what
exercises the *narrowed* Cognito lists.

1. Open `$SPA_ORIGIN` in a clean profile. **Expected:** the landing page renders with **"Sign in"**
   and **"Create account"**. No console errors, no CSP violations.
   - [ ] Pass
2. Click **Sign in**. **Expected:** full-page redirect to `$HOSTED_UI/login?...` for the right pool
   and client. **A `redirect_mismatch` error page here means `appUrl` and the app client's
   `callback_urls` disagree** — that is the distinguishing symptom, not a blank page.
   - [ ] Pass
3. Sign in as `arcb_owner`. **Expected:** back on **`$SPA_ORIGIN`**`/files` — *not* on
   `$CLOUDFRONT_URL`, which would mean the task definition's `appUrl` still names the old origin
   (SPEC-193's environment block; fix it there) — authenticated, username in the header. In the
   network panel confirm a `POST` to `https://$HOSTED_UI/oauth2/token` that returned **200** — the
   code exchange is a `fetch`, not a navigation, and it is what `connect-src` governs.
   - [ ] Pass — record the origin you landed on.
4. Reload `/files`. **Expected:** stays signed in, no flash of the landing page.
   - [ ] Pass
5. Sign out, then sign in again. **Expected:** lands on `/` then back on `/files`.
   - [ ] Pass

## 4. The load-bearing negative: the browser makes no AWS calls — BLOCKING

**Runs after merge 1, and the counting step runs after §8.** Two reasons, and both have been a
vacuous pass in a draft of this script:

- While the Identity Pool exists, `lib/amplify.ts` configures `identityPoolId` and every
  `fetchAuthSession()` vends credentials — so `cognito-identity.` **cannot** read zero, whatever the
  app does. The row is only meaningful once merge 1 has applied.
- The `sqs.` row counted over §5 and §7 alone spans a window with **no enqueue in it**. It must be
  counted over a window that includes §8, which is the surface SPEC-200 actually moved.

1. Open DevTools → Network, tick **Preserve log**, clear it, and complete **§5, §7 and §8** without
   closing the tab.
2. In the Network panel's filter box, run each filter **verbatim** (substituting the shell variables
   from §1) and record the request count:

| # | Filter string | Expected |
|---|---|---|
| 1 | `$API_ORIGIN` | **> 20** (the positive control — record the actual number) |
| 2 | `s3.$REGION.amazonaws.com` | **≥ 2**, and at least one `GET` and one `PUT` (positive control) |
| 3 | `cognito-idp.$REGION.amazonaws.com` | any (sign-in and token refresh; not a failure) |
| 4 | `$HOSTED_UI` | any (the code exchange) |
| 5 | `athena.` | **0** |
| 6 | `glue.` | **0** |
| 7 | `sqs.` | **0** |
| 8 | `cognito-identity.` | **0** |
| 9 | the catch-all below | **0** |

Row 9 is the only one that can catch a host nobody thought to list, so it is given as a literal
string rather than described. Chrome's Network filter box treats a `-`-prefixed term as an
exclusion; paste this as one line:

```
amazonaws.com -cognito-idp.$REGION.amazonaws.com -$USER_BUCKET.s3.$REGION.amazonaws.com -$SHARED_BUCKET.s3.$REGION.amazonaws.com
```

The Hosted UI host is deliberately **not** excluded: it is `*.auth.$REGION.amazoncognito.com` and
contains no `amazonaws.com` substring, so it never matches. `$API_ORIGIN` is a custom domain and does
not match either. Anything this filter shows is an AWS host the browser reached that no one declared.

- [ ] Every count matches. Record all nine numbers, not a tick.

3. **Each S3 request must be *presigned*.** A SigV4 *header*-signed S3 request is the browser holding
   credentials — the exact thing this arc removes — and it is indistinguishable from a presigned one
   at the host level. For each S3 request in the panel:
   - **Expected:** the query string contains `X-Amz-Signature` **and** `X-Amz-Expires`.
   - **Expected:** the request headers contain **no** `Authorization` and **no**
     `x-amz-security-token`.
   - [ ] Pass — record how many S3 requests were inspected.
4. **The presigned URL never appears in a log.** Spot-check `logs/service=api/` for the day: no record
   contains `X-Amz-Signature`, a bearer token, or an email address. A presigned URL is a bearer token.
   - [ ] Pass

## 5. Every ported surface, exercised once — BLOCKING

Keep §4's recording running throughout — it spans §5, §7 and §8.

1. **File browser.** List `/files`, open `arcb_files/`, page it, view the details panel for
   `small.txt`, create a folder `arcb_tmp/`, copy `small.txt` into it, move it back, delete
   `arcb_tmp/small.txt`. **Expected:** each completes and the listing reconciles.
   - [ ] Pass
2. **Presigned upload, with progress.** Upload `big.bin` (12 MiB). **Expected:** the progress bar
   *moves* — 0 → 100, not a jump. `fetch` reports no upload progress, so a bar frozen at 0% until
   completion means the `XMLHttpRequest` path SPEC-198 requires was not built, and the feature is
   silently lost. Confirm **one** `PUT` in the panel, not a multipart series.
   - [ ] Pass — record the observed `PUT` count (expected **1**).
3. **Presigned download.** Download `big.bin`. **Expected:** the file saves with its original name and
   the right byte count; the request carries `response-content-disposition`.
   - [ ] Pass
4. **The free-name route.** Copy `name.txt` into its own folder. **Expected:** the offered name is
   `name (4).txt`, produced by **one** API call — not 4, and not 999. Record the call count.
   - [ ] Pass
5. **Saved queries.** Open `arcb.sql` from the picker, edit it, save it back (Replace confirmed once),
   then save it into `arcb_space`. **Expected:** exactly **one** write per save.
   - [ ] Pass
6. **Query workspace.** Run `arcb.sql`. **Expected:** 10 rows; the disclosed SQL is byte-identical to
   what the API sent; a NULL renders visibly differently from an empty string.
   - [ ] Pass
7. **Data Explorer.** Open `arcb_report`, page past row 100 (**0** new executions — the page is
   cached), apply a filter whose value contains an apostrophe (`O'Brien`), and confirm the filter
   *is* a new execution with a changed row count. Copy a selection and export.
   - [ ] Pass
8. **Lake Formation still filters.** As `arcb_member`, open the catalog. **Expected:** `arcb_space`'s
   database is listed and `arcb_owner`'s is **not**. This is the assertion that LF grants attach to
   the **assumed** role, not to the API's own — if the API had a direct grant, `arcb_owner`'s
   database would appear and everything would still "work".
   - [ ] Pass
9. **Notifications.** Open the inbox, mark one read. **Expected:** the count updates.
   - [ ] Pass
10. **Membership propagation is unchanged.** Add `arcb_member` to a second shared space and, **without
    refreshing the token**, confirm the API refuses that space; then press **Refresh connections** and
    confirm the same request succeeds. **Both halves are required** — the first alone is
    indistinguishable from a broken grant, the second alone from a grant that was always live. This is
    also what proves SPEC-202 FR-005's `getIdToken(true)` substitution is real rather than a no-op.
    - [ ] Pass

## 6. Deep link, return path, and the clocks — BLOCKING

1. Signed out in a clean profile, open `$SPA_ORIGIN/files?prefix=arcb_files/`. Sign in.
   **Expected:** you land on `arcb_files/`, not on `/files`.
   - [ ] Pass
2. Repeat step 1 in **private browsing**. `lib/returnPath.ts` holds the return path in
   `sessionStorage`, which private browsing provides but scopes per window — so **assert on where you
   land**, never on whether storage exists.
   - [ ] Pass
3. **Two clocks, not three.** The BFF's session cookie is deferred to the target-environment arc, so
   Arc B has the Cognito session and the ID token's own lifetime and nothing else. Any procedure here
   asking about a third clock is reading a superseded draft.
   - **Expired ID token:** stage it (advance the system clock past the token's `exp`, or wait it out).
     Make any request. **Expected:** the API returns **401**, `apiClient` refreshes **once**, and the
     request succeeds — the user sees nothing.
     - [ ] Pass
   - **Ended Cognito session:** `aws cognito-idp admin-user-global-sign-out --user-pool-id $POOL_ID
     --username arcb_owner`, then act in the tab. **Expected:** the refresh fails and the user is put
     on sign-in — **not** a generic "Contact the Administrator". A raw provider string here is a
     SPEC-106 violation.
     - [ ] Pass

## 7. CSP, enforcing, with a negative control — BLOCKING

**A report-only pass proves nothing about enforcement.** The header name alone is not the check;
step 3 is. Run this section inside §4's recording, with the tab still open.

1. ```bash
   curl -sSI "$SPA_ORIGIN/" | grep -i 'content-security-policy'
   ```
   **Expected:** the header is `content-security-policy`, **not** `-report-only`. Record the full
   `connect-src`.
   - [ ] Pass
2. `connect-src` contains exactly: `'self'`, `$API_ORIGIN`, the S3 endpoint, `https://cognito-idp.$REGION.amazonaws.com`,
   `https://$HOSTED_UI`. **And contains none of** `athena.`, `glue.`, `sqs.`, `cognito-identity.`.
   - [ ] Pass
3. **Enforcement, with a negative control.** Paste the block below into the DevTools **Console** on
   the deployed page at `$SPA_ORIGIN` and press Enter.

   *Why this runs, and why it is not the bypass SPEC-140 measured.* Two other methods do **not**
   work here and neither fails visibly: an inline `<script>` you inject is refused by
   `script-src 'self'`, and a `<script>` pasted through the **Elements** panel is created by the HTML
   fragment parser, which marks it non-executable — it logs nothing at all, and "nothing logged"
   reads like a blocked probe. What SPEC-140 measured was the console's exemption from **script
   evaluation** (`new Function` reported allowed under `script-src 'self'`); `connect-src` is a
   different check at a different moment — it is applied to the *fetch*, whose client is this
   document. And the pass condition below is a **positive** violation event, which a bypassed policy
   does not emit at all: if the exemption did extend to `connect-src`, this row reads FAIL, never a
   false PASS.

   ```js
   addEventListener('securitypolicyviolation', e =>
     console.log('VIOLATION', e.effectiveDirective, e.blockedURI, e.disposition));

   fetch('https://example.com/probe').then(
     () => console.log('PROBE: BAD — allowed'),
     () => console.log('PROBE: blocked'));

   fetch(location.origin + '/healthz').then(r => console.log('CONTROL:', r.status));
   ```

   **Expected — all three lines, in any order:**
   ```
   VIOLATION connect-src https://example.com enforce
   PROBE: blocked
   CONTROL: 200
   ```
   `blockedURI` may be reported as the origin rather than the full URL; that is not a failure.
   **All three are required.** A blocked fetch alone is indistinguishable from a broken network
   (hence `CONTROL`), and an inert policy reports nothing whether or not anything occurred (hence
   `VIOLATION`). `disposition` is the direct read on enforce-vs-report; **in Safari it may be
   `undefined`** — record that verbatim if so and fall back to step 1's header name for that half,
   rather than marking the row FAIL for a missing property.
   - [ ] Pass — paste the three console lines.

   *Escalation, non-blocking, only if the console method is disputed.* Use DevTools → Sources →
   **Overrides** to override `/config.json`, setting `apiBaseUrl` to a host absent from `connect-src`,
   then reload. The app's own bundle — a genuine `script-src 'self'` page script, no console
   involved — issues the fetch, and the same `VIOLATION connect-src … enforce` appears. The app is
   non-functional while the override is active; delete it and reload afterwards.
4. The full SPEC-140 header set is present and `Server` is absent:
   ```bash
   curl -sSI "$SPA_ORIGIN/" | grep -iE 'strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy|cross-origin-opener|cross-origin-resource|^server:'
   ```
   - [ ] Pass
5. Cache classes: `/assets/<hashed>.js` carries `max-age=31536000, immutable`; `/index.html` carries
   `no-cache`; `/config.json` carries **`no-store`**. A stale `config.json` is a browser pinned to a
   retired environment's API.
   - [ ] Pass

## 8. One request per plane, and its notification — BLOCKING

Each row is enqueued **through the API** (the browser makes no `sqs:SendMessage` — §4 asserts that
count is 0). For each: perform the gesture, wait for the notification, and confirm the
`logs/service={plane}/` record carries a real `env` and a real build sha (never empty, never `0.0.0`).

| Plane | Gesture | Expected notification |
|---|---|---|
| shared-space | Add `arcb_member` to `arcb_space` | member added |
| notifications | Mark a notification read | (no notification; assert the inbox write) |
| table-build | Build `arcb_report2` from `arcb_files/report.csv` | table created, with a link |
| table-share | Share `arcb_report` with `arcb_member` | recipient told, with a link |
| data-quality | Check `arcb_files/report.csv` | report ready, with a link into the report route |
| file-send | Send `arcb_send/` to `arcb_member` | sender told once; recipient told once, linking to `shared_files/arcb_owner/` |
| archive | Archive `arcb_files/small.txt` | archived, with the archive id |
| file-ops | Move `arcb_send/` to `arcb_send_moved/` | operation summary |

- [ ] All eight enqueued, all eight notifications received.
- [ ] Every link in those notifications **resolves in the app** — the links are minted in Python and
      honoured by a TypeScript route rule, and nothing offline connects the two.
- [ ] `logs/` records for all eight carry `env` and a real sha.

> The **archive** direction only. A restore is 3–5 billed, uncancellable hours and belongs to
> `e2e.md`, not here.

## 9. Safari, and 400px — BLOCKING

**Safari is the discharging pass.** The user browses in Safari; a Chromium run corroborates and cannot
discharge, and Safari's report-only blind spot means it is the browser most likely to differ.

1. In **Safari**, repeat §3 (fresh sign-in, clean profile), §5 steps 1–3 and 6–7, and §7 steps 1–4.
   - [ ] Pass — note any divergence from Chrome explicitly, including "none".
2. **400px.** Not reachable by window resize on macOS. Open the device toolbar, set the width to
   **400**, reload (so load-time device gates re-run), and record:
   ```js
   [matchMedia('(min-width: 900px)').matches, matchMedia('(min-width: 1300px)').matches,
    innerWidth]
   // expected: [false, false, 400]
   ```
   Assert on that output, not on a screenshot. Then check: the nav is a hamburger, no dialog overflows
   the viewport, and the file browser, Query workspace and Data Explorer are each usable.
   - [ ] Pass — paste the `matchMedia` output.

## 10. Rollback rehearsal — BLOCKING, and it must run AFTER merge 1 and BEFORE merge 2

Merge 1 left the distribution, both Cognito lists, both buckets' CORS and CloudFront's own
`connect-src` exactly as they were, so this is a real rollback and this is the only window in which
rehearsing it is both meaningful and still possible.

1. Open `$CLOUDFRONT_URL` in a clean profile and sign in. **Expected:** the app loads and completes at
   least one API call.
   - [ ] Pass
2. Record, in the log below, what the rollback actually is: **a CloudFront-served HEAD bundle talking
   to the API.** It is *not* a pre-arc portal — that code is gone from `main`. A future reader rolling
   back while expecting browser-direct AWS will be surprised at the worst moment.
   - [ ] Recorded

## 11. The merge-1 consequences — BLOCKING

Run **after merge 1**, not after merge 2: the pool, the trust statement, the browser modules and the
lint rule are all merge 1's. §12 covers what merge 2 changes and re-runs nothing from here.

`$PORTAL_ROLE`, `$API_ROLE` and `$SPA_TASK_ROLE` come from §1 — **none of them is a
`tofu output`**, and `tofu output -raw portal_role_arn` fails (it is a local in `infra/main.tf`).

**Every denial is paired with an `allowed` control**: an `implicitDeny` alone cannot distinguish an
ungranted action from a wrong resource ARN — this repo learned that on a mistyped
`dat-prod-athena-admin`.

```bash
sim() { # sim <role> <action> <resource> [context-entries...]
  printf '%-22s %-24s %-62s ' "$(basename $1)" "$2" "$3"
  aws iam simulate-principal-policy --policy-source-arn "$1" --action-names "$2" \
    --resource-arns "$3" "${@:4}" \
    --query 'EvaluationResults[0].EvalDecision' --output text
}
TAG_ALICE='--context-entries ContextKeyName=aws:PrincipalTag/username,ContextKeyType=string,ContextKeyValues=arcb_owner'

# Worked example — the first row of the table below. Expand the shorthand in the
# `Resource` column the same way: `user-space/<key>` is
# arn:aws:s3:::$USER_BUCKET/<key>, `user-space` alone is the bucket ARN,
# `shared-space/<key>` is arn:aws:s3:::$SHARED_BUCKET/<key>, and
# `database/<name>` is arn:aws:glue:$REGION:<account>:database/<name>.
sim "$PORTAL_ROLE" s3:GetObject "arn:aws:s3:::$USER_BUCKET/arcb_owner/x.csv" $TAG_ALICE
# -> allowed
```

**The portal role — SPEC-196's table, row for row, re-run after the pool is gone. A changed decision
is a defect in SPEC-202, not a new decision.**

| Action | Resource | Context | Expect |
|---|---|---|---|
| `s3:GetObject` | `user-space/arcb_owner/x.csv` | `username=arcb_owner` | `allowed` (control) |
| `s3:GetObject` | `user-space/arcb_member/x.csv` | `username=arcb_owner` | `implicitDeny` |
| `s3:ListBucket` | `user-space` | `username=arcb_owner`, `s3:prefix=arcb_owner/` | `allowed` (control) |
| `s3:ListBucket` | `user-space` | `username=arcb_owner`, `s3:prefix=arcb_member/` | `implicitDeny` |
| `s3:DeleteObject` | `user-space/arcb_owner/reports/x.csv` | `username=arcb_owner` | `allowed` (control) |
| `s3:DeleteObject` | `user-space/arcb_owner/DO_NOT_DELETE.txt` | `username=arcb_owner` | `explicitDeny` |
| `s3:PutObject` | `user-space/arcb_owner/archive/r.txt` | `username=arcb_owner` | `explicitDeny` |
| `glue:GetTable` | `database/arcb_owner` | `username=arcb_owner` | `allowed` (control) |
| `glue:GetTable` | `database/arcb_member` | `username=arcb_owner` | `implicitDeny` |
| `s3:GetObject` | `shared-space/arcb_space/x` | `shared_space_1=arcb_space` | `allowed` (control) |
| `s3:GetObject` | `shared-space/arcb_space/x` | **slot tags absent** | `implicitDeny` |
| `s3:DeleteObject` | `shared-space/arcb_space/athenaresults/x` | `shared_space_1=arcb_space` | `explicitDeny` |

- [ ] All twelve match, and match what SPEC-196 recorded pre-retirement.

**The API Lambda's execution role:**

| Action | Resource | Expect |
|---|---|---|
| `sts:AssumeRole` | the portal role | `allowed` (control) |
| `s3:GetObject` | `user-space/arcb_owner/x.csv` | `implicitDeny` |

- [ ] Both match. The second is the one worth the trouble: a stray direct grant would make every route
      work while silently bypassing the `username` tag, and nothing user-facing would look wrong.

**The SPA task role — not proved by simulation.** A role with no policies returns `implicitDeny` for
everything with no control available, and an unpaired `implicitDeny` presented as a pass is exactly
the failure mode this section exists to avoid. Enumerate instead:

```bash
aws iam list-attached-role-policies --role-name "$(basename $SPA_TASK_ROLE)"   # -> []
aws iam list-role-policies          --role-name "$(basename $SPA_TASK_ROLE)"   # -> []
```
- [ ] Both empty.

**The portal role's trust:**
```bash
aws iam get-role --role-name "$(basename $PORTAL_ROLE)" --query 'Role.AssumeRolePolicyDocument'
```
- [ ] Exactly **one** statement, naming the API Lambda's execution role, with `sts:AssumeRole` and
      `sts:TagSession`. No `cognito-identity.amazonaws.com`.

**The Identity Pool, and the browser tripwires:**
```bash
aws cognito-identity describe-identity-pool --identity-pool-id "$POOL_ARN_ID"
# -> ResourceNotFoundException  (a positive absence; "gone from the plan" is a different claim)
```
- [ ] `ResourceNotFoundException`, on the id recorded in §1 before merge 1 deleted its output.
- [ ] `npm run lint` is green, and a deliberate `@aws-sdk/client-s3` import — **one in a feature file
      and one in a `*.test.ts` file** — makes it **red for both**. Revert both. Reading the config is
      not verification.
- [ ] `grep -n '@aws-sdk/' apps/portal/package.json` returns nothing.

## 12. The merge-2 consequences — BLOCKING

Run **after merge 2 has applied**. Merge 2 narrows two allowlists a browser can observe and destroys
one distribution; each of the three is re-exercised by the check that can actually detect it.

```bash
aws cloudfront get-distribution --id "$DIST_ID"
# -> NoSuchDistribution. Do NOT check a status code: this distribution mapped 403/404 -> /index.html
#    with a 200, so a deleted object answered 200 and a deleted origin would too.
```
- [ ] The distribution is gone.
- [ ] Re-run **§3** in a clean profile — it exercises the Cognito callback and logout lists, which
      merge 2 narrowed to `$SPA_ORIGIN`. A `redirect_mismatch` page here means `appUrl` and the app
      client disagree.
- [ ] Re-run **§5 steps 2 and 3** — a real presigned upload and a real presigned download. This is
      the only check that can detect the bucket-CORS narrowing to `$SPA_ORIGIN` and `["GET","PUT"]`,
      because a CORS failure presents as an opaque browser error with no AWS text in it.
- [ ] `curl -sSI "$CLOUDFRONT_URL"` returns a DNS or connection failure, not any status code.
- [ ] `describe-user-pool-client` returns **two** `CallbackURLs` and two `LogoutURLs` —
      `$SPA_ORIGIN` and `http://localhost:5173`, and **no** CloudFront domain.

---

## 13. What one session cannot settle

Record these as **owed**, not discharged:

- Anything about the target-environment arc — no BFF, no session cookie, no PKCE, no Entra, no
  Identity Center ships in Arc B, so nothing here says anything about them.
- The container under real concurrency, a task failure mid-request, or an AZ loss. Autoscaling and
  the availability work `transition_plan.md` §4.6 names are deferred.
- The archive **restore** direction (3–5 billed hours) — `e2e.md` owns it.
- **Everything the container owns about `/config.json`**: the entrypoint rendering it from the task
  environment, nginx emitting `no-store`, and image promotion itself. §A proves the document's
  contract and the browser's half against the static site; the server half is SPEC-194's to check.
- **Other arcs' owed live checks are not absorbed by this script.** Classify each before closing:
  anything asserting a URL, a CSP, a browser AWS call or a bucket-CORS behaviour is **invalidated by
  the origin change and must be re-run**; anything asserting a Lambda, a state machine, an IAM
  simulation or a `logs/` record is **unaffected**. Leaving one unclassified is how a discharged check
  silently becomes stale.

## 14. Cleanup

- [ ] Delete `arcb_files/`, `arcb_send/`, `arcb_send_moved/`, `arcb_tmp/`, `arcb.sql`, `arcb_report`,
      `arcb_report2`, and the archive created in §8.
- [ ] Delete `arcb_space` (type-to-confirm) and confirm the Glue database is gone from the rail — a
      partial teardown leaves the name locked.
- [ ] Delete the two test users from the User Pool and their prefixes.

## 15. Execution Log

**Recorded before merge 1** (their Terraform outputs do not survive the merges):

| Value | Captured |
|---|---|
| `cognito_identity_pool_id` → `$POOL_ARN_ID` | |
| `cloudfront_distribution_id` → `$DIST_ID` | |

| Date | Section | Merge state | Browser | Result | Notes |
|---|---|---|---|---|---|
| | | pre-merge-1 / post-merge-1 / post-merge-2 | | | |
