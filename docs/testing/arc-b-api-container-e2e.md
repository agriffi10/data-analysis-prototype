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

> **The placeholder is gone (SPEC-194, 2026-08-27).** `Dockerfile.placeholder` and the dispatch
> workflow that pushed it are deleted; `Deploy SPA image` builds and pushes the real image on every
> push to `main`, and its own `workflow_dispatch` re-points the service at an existing tag. This
> block is kept because §B's steps were run against the placeholder and the record should say what
> was actually executed — it is not a procedure to re-run.

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

## C. The SPA container (SPEC-194) — runnable NOW, outside the merge order

Like §A and §B, this stands outside the merge sequence: `portal.dataquarry.app` serves the **real
SPA** from a container while CloudFront remains production and the rollback. Nothing a user can see
has changed.

**What the offline gates already prove, so this section does not re-prove it.** The image's
behaviour matrix runs against a real container started the way ECS starts it — read-only root, uid
101, the two tmpfs mounts — and asserts 189 checks over the response classes, the refusals, the
cache classes and the compression. **What it cannot prove is anything between the container and the
browser**, which is what §C is for.

**Two expected non-failures, so they are not diagnosed as defects.** Bucket CORS allowlists the
CloudFront origin and localhost only, so the browser's direct S3 calls fail **preflight** from the
container origin until SPEC-198 — the portal loads and signs in; file operations do not work. And
Terraform registers task-definition revisions that CI never points the service at, so a change to
the runtime-configuration map or the CSP does not reach the running container until the next push
to `main`; the deploy workflow's `workflow_dispatch` is the lever.

**Already discharged (2026-08-27), recorded so they are not re-run blindly.** Read back from
`https://portal.dataquarry.app` against the deployed load balancer:

- **The full header set on five response classes** — the shell, a deep link, a hashed asset, the
  honest 404 and `/config.json` — every one carrying CSP, HSTS, `X-Frame-Options`, `nosniff`,
  `Referrer-Policy`, `Permissions-Policy`, COOP and CORP. **The load balancer adds and strips
  nothing**, which is the assertion no offline gate can make.
- `strict-transport-security: max-age=31536000; includeSubDomains` with **no `preload`**, and **no
  `Cross-Origin-Embedder-Policy` on any response**.
- `server: nginx` with **no version**.
- The cache classes: `/` and a deep link `no-cache`, `/assets/<hashed>`
  `public, max-age=31536000, immutable`, `/config.json` and `/healthz` `no-store`.
- `GET /config.json` → 200 / `application/json` / `no-store`, **21 keys** (`version` plus the 20
  classified) and `version: 1`.
- `GET /healthz` → 200 / `text/plain` / body exactly `ok`.
- `GET /assets/index-DEADBEEF.js` → **404**, `content-type: application/javascript`, body
  `not found` — not the shell, and not HTML.
- A hashed asset with `Accept-Encoding: gzip` → `content-encoding: gzip` + `vary: Accept-Encoding`;
  with `Accept-Encoding: br` → **no** `content-encoding`, the accepted brotli residual.
- **The served `connect-src` carries all ten terms**, including the two a signed-in tester cannot miss the loss of — the User Pool endpoint and the Hosted UI domain:
  `'self'`, `cognito-idp.us-east-1`, `cognito-identity.us-east-1`,
  `dat-prod-portal.auth.us-east-1.amazoncognito.com`, both bucket endpoints, `athena.`, `glue.`,
  `sqs.` and `https://api.dataquarry.app`.
- The deploy reported `desired=1 running=1 rollout=COMPLETED`, the settled PRIMARY equalled the
  revision the run registered, and the revision carried **20 configuration keys**.

### C.1 — Fresh sign-in, in a private window. BLOCKING, and it cannot be substituted.

**A signed-in pass never tests sign-in.** The authorization-code exchange is the only `fetch` to the
Hosted UI host; a warm tab never makes it. A `connect-src` missing that host produces a portal that
works for everyone already signed in and for nobody else — which is this repository's own recorded
outage, and it lasted a day. **A pass that begins at an authenticated `/files` has not tested this
and must not be recorded as having done so.**

1. Sign out. **Close the window.** Open a **private** one.
2. Go to `https://portal.dataquarry.app`, open DevTools → Console with `Preserve log` **on**.
3. Complete the Hosted UI round trip.
4. - [ ] The redirect back is redeemed and the app renders signed in.
   - [ ] **Zero CSP violations in the console**, across the redirect — not just after it.
   - [ ] The `POST` to `dat-prod-portal.auth.us-east-1.amazoncognito.com/oauth2/token` succeeded.

### C.2 — The CSP is enforcing, with a negative control. BLOCKING.

A pass that reports no violations proves nothing on its own — it may have succeeded *because* the
policy was inert. **Do not use CDP `Runtime.evaluate`**: it bypasses page CSP entirely and once
reported `new Function` as allowed under `script-src 'self'`.

- [ ] From a **same-origin page script**, `new Function('return 1')()` is **blocked** — the negative
      control that proves enforcement is live.
- [ ] `fetch('https://example.com')` is blocked; a fetch to the API origin is not.

### C.3 — Safari, once. BLOCKING.

The tooling here is Chromium, so this step names the browser. Safari refuses to evaluate a
report-only policy naming no reporting endpoint — the blind spot no Chromium harness surfaces.

- [ ] Sign in fresh in Safari, private window. The app renders and the console shows no CSP error.

### C.4 — Deep links, cold, in a private window. BLOCKING.

- [ ] `/files?prefix=…`, `/explore` and `/query` each load the SPA on a **cold** load, not a 404.
- [ ] `curl -I` each of the four cache classes — devtools reports *effective* freshness rather than
      the header, which is why this is `curl` and not the network panel.

### C.5 — A rolling deployment, watched. BLOCKING.

FR-002's residual, observed rather than assumed: a task serves exactly one image's file set, so a
browser holding the **old** shell routed to a **new** task 404s a lazily-imported chunk immediately.

1. Open the portal and leave the tab open.
2. Merge any change to `apps/portal/` and let `Deploy SPA image` run.
3. - [ ] Navigating to a lazy route in the **old** tab may 404 inside the Suspense boundary.
   - [ ] **A reload recovers**, because the shell is `no-cache`.

### C.6 — The health check doing its job. BLOCKING, and it needs the right kind of broken.

**The obvious version of this check cannot run.** The pipeline is build → matrix → push → deploy, so
an entrypoint that exits 1 reddens at the **matrix** and never reaches the deploy gate — recording
that as discharged would prove only the matrix.

**And the obvious alternative does not work either.** Adding a key to the entrypoint's baked
`REQUIRED` list reddens `pytest` before anything builds — a test pins that list against the
browser's classification — and removing a key from `local.spa_runtime_config` reddens the portal
suite. Every offline gate has an opinion about both ends of the document.

The break has to be **env-only, on the task-definition side, in a variable the image defaults**.
Add `PORTAL_LOG_LEVEL = "chatty"` to the container definition's `environment` block and apply.
The image defaults that variable to `warn`, so the matrix never supplies it and never sees the
change; no test pins the task definition's environment *set*, only that the configuration keys are
derived. On Fargate the entrypoint's level allowlist refuses, and the container never starts.

Confirm before writing any new recipe down that no test pins whatever you are about to change —
two of the three obvious breaks are caught offline, which is the gates working, and would make this
check prove nothing.

- [ ] The ECS deployment does **not** reach `COMPLETED`.
- [ ] **The workflow goes red**, on `rolloutState`, not on a timeout alone.
- [ ] Revert, and confirm the next run is green.

### C.7 — A ZAP baseline against the container origin. Non-blocking.

- [ ] Diff against `security-baseline.md` **per alert ID, never by total** — a clearing and an
      appearing finding once cancelled out at 305 and made the total look untouched.
- [ ] Expect the `style-src 'unsafe-inline'` Medium and the COEP Info to persist **by decision**.
- [ ] **No new *Server Leaks Version Information* row** — that alert fires on a version, and
      `server_tokens off` is what keeps it clear.

### C.8 — Owed, because nothing offline or in one session can settle it

- That a browser honours `immutable` across a real deployment.
- That a warm-cache user of the CloudFront origin is unaffected while both delivery paths run.
- Whether the ALB's own idle timeout or header handling changes under load.

---

> **§E (SPEC-196, the AWS identity layer) follows this section**, at the end of the file rather
> than here, because it is the only section that has not been run at all — Arc B's live
> verification happens once, at SPEC-202. It stands outside the merge order like §A–§D. Its
> items 1 and 9 overlap §11's trust-statement and IAM-simulation steps deliberately: whichever
> runs first discharges both, and the other records that it did.

## D. The API's auth boundary (SPEC-195) — PARTLY RUN 2026-08-27

> **STATUS.** **D.1 and D.2 ran** on 2026-08-27 against `GET /_auth/whoami` and are recorded in
> [`sessions.md`](sessions.md): the happy path, and four refusals with one repeated body digest and
> the challenge header on all four. **D.3, D.5 and D.6 did not run.**
>
> **The probe this section is written against is deleted** (SPEC-197 FR-014). The three outstanding
> items are all token-refusal checks, and `GET /v1/user-directory` serves them identically — every
> refusal here is refused **before dispatch**, so the route being a real feature changes nothing
> about what they measure. **Substitute `/v1/user-directory` for `/_auth/whoami` throughout**, and
> read D.1's happy-path assertion as "suggestions render" (§F.1) rather than an echoed username.

Like §A–§C this stands outside the merge sequence.

**EVERY LOAD-BEARING CHECK BELOW IS NEGATIVE, and that is the whole design of this section.** A
request carrying a genuine token succeeds against a correct implementation *and against one that
does not verify at all* — so the happy path proves the wiring and nothing else. What can fail is the
refusals, and three of them cannot be reached offline at any price: that the JWKS endpoint is
reachable from the function's network placement, that a browser preflight allows the bearer header,
and that a genuinely expired token is refused **by the expiry check** rather than by something
earlier.

**What the offline gates already prove, so this section does not re-prove it.** 77 assertions over
the boundary, including: eight refusal shapes returning byte-identical responses; the expired body
byte-identical to the no-token body; four distinct reason codes in the log records, which is what
says four different checks actually ran; an undeclared route refused rather than served; the token
read from the bearer header and nowhere else; five provider-unreachable shapes answering 5xx and
never 401; and a sentinel token appearing in no byte of any log record, `error.stack` included.

```bash
API=https://api.dataquarry.app
SPA=https://portal.dataquarry.app
```

**D.1 — The happy path, once. It proves the wiring and nothing about the verification.**

Take a real ID token from a signed-in browser session (DevTools → Application → Local Storage →
the `...idToken` key), then:

```bash
ID_TOKEN='<paste>'
curl -s -o /dev/stdout -w '\n%{http_code}\n' -H "authorization: Bearer $ID_TOKEN" "$API/_auth/whoami"
```

- [ ] `200` and `{"username":"<your signed-in username>"}` — the username, not the `sub`.

**D.2 — Four refusals, and their bodies compared. BLOCKING.**

Row 2 is the cheapest real proof that `aud` and `token_use` are enforced: a genuine, correctly
signed, unexpired token **from the same pool and the same user**, which an implementation checking
only the signature accepts. Row 4 is the only one that tests key-set **provenance** rather than
signature integrity — a well-formed token whose `kid` this pool never published.

```bash
ACCESS_TOKEN='<paste the accessToken from the same session>'

# One payload byte flipped: the signature no longer covers the body.
FLIPPED=$(python3 - "$ID_TOKEN" <<'EOF'
import sys
h, p, s = sys.argv[1].split('.')
print(f"{h}.{p[:-1]}{'A' if p[-1] != 'A' else 'B'}.{s}")
EOF
)

# Signed by a key this pool never published — a real RS256 token with a foreign kid.
FOREIGN=$(python3 - <<'EOF'
import json, time, jwt
from cryptography.hazmat.primitives.asymmetric import rsa
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
print(jwt.encode({"cognito:username": "alice", "token_use": "id",
                  "aud": "<the app client id from /config.json>",
                  "iss": "<the OIDC_ISSUER value>", "exp": int(time.time()) + 3600},
                 key, algorithm="RS256", headers={"kid": "not-a-key-this-pool-published"}))
EOF
)

for label in no-token access-token flipped-payload foreign-key; do
  case $label in
    no-token)        AUTH=() ;;
    access-token)    AUTH=(-H "authorization: Bearer $ACCESS_TOKEN") ;;
    flipped-payload) AUTH=(-H "authorization: Bearer $FLIPPED") ;;
    foreign-key)     AUTH=(-H "authorization: Bearer $FOREIGN") ;;
  esac
  printf '%s: ' "$label"
  curl -s -D "/tmp/h.$label" -o "/tmp/b.$label" -w '%{http_code}\n' "${AUTH[@]}" "$API/_auth/whoami"
done

shasum -a 256 /tmp/b.no-token /tmp/b.access-token /tmp/b.flipped-payload /tmp/b.foreign-key
grep -i www-authenticate /tmp/h.no-token /tmp/h.access-token /tmp/h.flipped-payload /tmp/h.foreign-key
cat /tmp/b.no-token; echo
```

- [ ] All four are `401`.
- [ ] All four bodies hash **identically** — one digest repeated four times.
- [ ] `www-authenticate: Bearer` on **all four** — four lines, not one.
- [ ] The body is exactly `{"error": "unauthorized", "code": "SessionExpired"}`: no reason,
      no `kid`, no issuer, no fragment of any token.

**D.3 — A genuinely expired token, and the obvious recipe does not work. BLOCKING.**

A Cognito ID token lives an hour, so this has to be set up rather than waited for.

**Do NOT mint it from a throwaway app client.** `oidc_audience` is a *single* client id
(`infra/main.tf`), so a second client's token is refused on **audience** — the verifier never
reaches the expiry check, and nothing tells you which check refused: the wire is byte-identical by
design, and `verification_failed` is one reason code covering signature, issuer, audience and
expiry alike. The check would pass while proving the opposite of what it claims.

What works is temporarily shortening the **existing** app client's ID-token validity to its
**5-minute minimum**, in the Cognito console (App client → Authentication flow session duration →
token expiration). Sign in fresh, capture the ID token, wait six minutes.

```bash
EXPIRED='<the token captured six minutes ago>'
curl -s -D /tmp/h.expired -o /tmp/b.expired -w '%{http_code}\n' \
  -H "authorization: Bearer $EXPIRED" "$API/_auth/whoami"
shasum -a 256 /tmp/b.expired /tmp/b.no-token
```

- [ ] `401`, and the body hashes **identically** to `/tmp/b.no-token` from D.2.
- [ ] This is the only way to see the verifier reach the expiry check at all rather than failing
      earlier — every offline test fakes the clock and cannot distinguish the two.
- [ ] **Restore the app client's token validity afterwards** (§14), or every session in the
      environment expires in five minutes.

**D.4 — The browser's refresh-once path. OWED, not runnable here — and the reason is worth stating.**

`apiFetch` has **no caller**: no route is ported, so no user action anywhere in the portal issues a
request to count. "Leave a tab idle and act" has nothing to act on. It is recorded in `owed.md` and
belongs to the pass for the spec that ports the first route, where it becomes an ordinary check
rather than a staged one.

What it will assert there, unchanged: exactly **two** requests on a 401 — the refusal and the retry
that succeeds — the user **not** signed out, and then, with the refresh broken (sign out in a second
tab), a retry that `401`s with **no third request**. A refresh loop against a dead refresh token is
invisible in a passing offline test and obvious in a network panel.

**D.5 — The preflight, in a browser. BLOCKING, and curl proves nothing here.**

Only a browser enforces CORS. From the SPA origin's console:

```js
await fetch('https://api.dataquarry.app/_auth/whoami', {headers: {authorization: 'Bearer x'}})
```

- [ ] The `OPTIONS` preflight returns `authorization` in `access-control-allow-headers`, and the
      request reaches the API (a 401 is the expected answer — the point is that it was *sent*).
- [ ] **Run this in Safari as well as Chromium.** Safari is the browser this project has been
      surprised by before.

**D.6 — The stack scrub against a REAL token. BLOCKING.**

The offline sentinel is synthetic; the question here is whether a real token's characters survive a
real serialisation path.

**It has to be a refusal, and a valid request will not do.** The success path emits no record beyond
its span, and that span carries no `error` at all — so grepping after a 200 returns `0` for the same
reason an empty file does. A query parameter will not force one either: the handler passes only the
method, the path and the headers, so `?anything` never reaches the router. `$FLIPPED` from D.2 is
what works — it carries the real token's header and signature characters and is refused.

```bash
curl -s -o /dev/null -H "authorization: Bearer $FLIPPED" "$API/_auth/whoami"

ADMIN_BUCKET=$(tofu -chdir=infra output -raw athena_admin_bucket_name)
DAY=$(date -u +'year=%Y/month=%m/day=%d')
# after the logs sweep has run for that window
aws s3 cp "s3://$ADMIN_BUCKET/logs/service=api/$DAY/data.jsonl" - > /tmp/api-records.jsonl
grep -c "$(cut -d. -f1 <<<"$ID_TOKEN")" /tmp/api-records.jsonl   # header segment
grep -c "$(cut -d. -f3 <<<"$ID_TOKEN")" /tmp/api-records.jsonl   # signature segment
grep -c '"reason": "verification_failed"' /tmp/api-records.jsonl
```

- [ ] The last count is **≥ 1** — the refusal was recorded, so the two counts above mean something.
      Without this the grep proves nothing.
- [ ] Both token-segment counts are **0**.
- [ ] The day's records carry a real `env` and a real build sha, **never `0.0.0`**.

**D.7 — Owed, because nothing in one signed-in session can settle it**

- A JWKS **rotation** across the cooldown window. Cognito publishes both keys across a rotation and
  the window is 60s, so no real rotation is expected to reach a user — untestable without forcing a
  pool key rotation, and recorded as accepted rather than verified.
- The unknown-`kid` **refetch bound** under real load. The counter is asserted offline; what is not
  observed is the fetch rate a real burst produces against the real endpoint.

## 0. Gates, before anything — BLOCKING

Run this section **before merge 1 is merged.**

- [ ] `gh run list --branch main --limit 8` is green, including **Deploy Infrastructure**, **Deploy
      Lambdas** and **Deploy SPA Image**. A red deploy makes every failure below unreadable.
- [ ] **Arc A has landed** (SPEC-187 → 191). §8's file-ops row and its queue do not exist otherwise,
      and SPEC-200's `QUEUES` set-equality guard hard-fails without them.
- [ ] **The running task is HEAD's image.** Read the TAG, not the health endpoint:
      `/healthz` returns the literal string `ok` by design (`default.conf.template`), so it cannot
      report a build at all — an earlier version of this line asked for a sha and was unrunnable.
      ```bash
      aws ecs describe-task-definition --task-definition "$TASK_DEF" \
        --query 'taskDefinition.containerDefinitions[0].image' --output text
      # -> ...dat-prod-spa:<sha>, and <sha> must equal `git rev-parse origin/main`.
      ```
      A stale task serving an old image passes most of this script and proves nothing about HEAD.
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

## 4. The load-bearing negative: the browser makes no AWS calls — RUN 2026-08-31, in Chromium

> **RESULT (2026-08-31, after merge 1 deployed).** Nine filters over one document that held a
> listing, a folder create, a 7 MB upload, a download, an Athena query and an enqueue:
> `api.dataquarry.app` **69**; the user bucket **2** (one `PUT`, one `GET`); `athena.` **0**;
> `glue.` **0**; `sqs.` **0**; **`cognito-identity.` 0**; catch-all **empty**. The whole host table
> was four entries — the SPA, the API, the user bucket and `fonts.googleapis.com`. Rows 3 and 4
> read 0 because no sign-in or refresh fell inside the window, which the table permits as *any*.
> `/config.json` no longer carries `cognitoIdentityPoolId` **at all** — the key is absent, not
> empty, which is what makes row 8 meaningful for the first time. **Chromium; Safari still owed.**

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

3. **Each S3 request must be *presigned*.** A *header*-signed S3 request is the browser holding
   credentials — the exact thing this arc removes — and it is indistinguishable from a presigned one
   at the host level. For each S3 request in the panel:
   - **Expected:** the query string carries the signature. **The version is now pinned to SigV4 in
     code** — `identity.S3_SIGNATURE_VERSION`, with a test asserting the client is built with it —
     so expect `X-Amz-Algorithm`, `X-Amz-Credential`, `X-Amz-Date`, `X-Amz-Expires`,
     `X-Amz-SignedHeaders`, `X-Amz-Security-Token` and `X-Amz-Signature`.

     **This row has been wrong in BOTH directions, which is why it now says to record the shape
     rather than trust this paragraph.** It first asserted the SigV4 spelling against a deployment
     that minted SigV2 (botocore's S3 default, unpinned); it was then rewritten to assert the SigV2
     spelling, which the pin has just invalidated. Assert *a* signature and *an* expiry parameter in
     the query, **record which family you saw**, and treat a mismatch with this paragraph as a
     question about the deployed image before it is a failure — step 4's sweep depends on the
     answer.
   - **Expected:** the request *headers* contain **no** `Authorization` and **no**
     `x-amz-security-token`. The token riding in the **query** is normal for a URL presigned by an
     assumed session; the header is what would mean the browser holds credentials.
   - [x] **Pass, 2026-08-31** — 2 requests inspected (one `PUT`, one `GET`), both with an empty
     request-header set and both signed in the query. Upload and download windows were both 900 s,
     unclamped, so the credential had more than that left and the clamp did not bite.
   - [x] **Re-run PASSED 2026-09-01, against the SigV4 pin, on both mint paths.** Upload `PUT`:
     `X-Amz-Algorithm=AWS4-HMAC-SHA256`, `X-Amz-Credential`, `X-Amz-Date`, `X-Amz-Expires=900`,
     `X-Amz-SignedHeaders`, `X-Amz-Security-Token`, `X-Amz-Signature`; **no** `AWSAccessKeyId` and
     no SigV2 parameter. Download `GET`: the same seven plus `response-content-disposition`, which
     names the file. **Request headers on the `PUT` were `content-type` alone** — no
     `Authorization`, no `x-amz-security-token` header — which is the half that says the browser
     holds no credentials. Observed by patching `XMLHttpRequest.open` in the page, so the URL
     recorded is the one the app was handed.
4. **The presigned URL never appears in a log.** Spot-check `logs/service=api/` for the day: no record
   contains a presigned URL's signature, a bearer token, or an email address. A presigned URL is a
   bearer token.

   **Sweep for BOTH families, always, and the reason is that this sweep has already been unfailable
   once.** The 2026-08-30 run swept 470 records for `X-Amz-Signature` against a deployment that
   minted SigV2 and could not have failed; the fix was to sweep for the SigV2 spelling instead, and
   the SigV4 pin has now made *that* the half that matches nothing. A sweep naming only the family
   currently deployed goes unfailable on the next change to a line of code in a different tree. So
   sweep for all of:

   ```
   X-Amz-Signature   X-Amz-Credential   X-Amz-Security-Token
   AWSAccessKeyId    x-amz-security-token   Signature=
   ```

   `Signature=` matches inside `X-Amz-Signature=` as well, so it is the backstop for a family
   nobody has thought of. **A run reporting zero across all six needs its positive control** — the
   window must contain at least one real presign mint, evidenced by the `key_length` records — or
   zero means the window was empty, not that nothing leaked.

   **And a HIT is not automatically a leak.** `error.stack` is built by
   `traceback.format_exception`, which carries the SOURCE LINES of every frame, and
   `botocore/auth.py` contains all six of these tokens as string literals. An exception raised
   inside signing — a vanished session raising `NoCredentialsError` is the realistic one — puts
   those frames in a traceback that matches every pattern while containing no credential at all.
   Read the matching record before escalating: a real leak carries a signature *value*, a
   traceback carries the parameter *name*.
   - [x] **Pass, 2026-08-31** — all six patterns zero across 1,605 records, with the positive
     control that the window held two real presign mints (six `key_length` records).
   - [x] **Re-run PASSED 2026-09-01.** All six patterns **zero across 473 records** in
     `logs/service=api/year=2026/month=09/day=01/`, swept from the admin bucket. The positive
     control is strong and is the reason the zero means anything: the window carried **58**
     `key_length` and **58** `presign_expires_in` records, so it contained real presign mints —
     including the SigV4 ones minted minutes earlier for step 3.

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

## E. The AWS identity layer (SPEC-196) — PARTLY RUN 2026-08-27

> **STATUS: PARTLY RUN, 2026-08-27.** E.0, E.1, E.2 (username half), E.3, E.6 and E.7 were run
> against the deployed API and are recorded in [`sessions.md`](sessions.md); the rest is still
> owed. The 2026-08-27 decision to run Arc B's live verification once at SPEC-202 was **narrowed
> for this section**, because SPEC-197 deletes the probe these items are driven through — running
> them at 202 would have meant deleting the only instrument that can observe the isolation model
> before it was ever observed. **The probe routes are gone as of SPEC-197: the remaining items
> need a different vehicle**, named per item. Do not read a written step as a discharged one.

**Everything that matters in SPEC-196 is invisible to the offline suite**, and each of the reasons
is one this project has already paid for once. Every offline test supplies its own claims and its
own stubbed STS: not one of them can tell you that the token really carries the claims, that the
trust policy admits the API, that the tag was stamped, or that the bucket policy's allowlist
resolves an assumed-role request the way `s3.tf`'s comment says it does.

**Two mechanisms were verified BY READING while building, and they are recorded here as mechanism
only.** Recording them matters because a later reader cannot otherwise tell a proof from a
coincidence:

- The portal role's `UserPrefixList` statement grants `s3:ListBucket` **only** under
  `"s3:prefix": ["$${aws:PrincipalTag/username}/", …]`
  (`infra/modules/data/policies/portal-role-permissions.json.tftpl`). That is why item 6's
  `ownPrefixListable: true` is reachable **only** with the username tag correctly stamped —
  behaviour is the proof, because this account records no `AssumeRole` event anywhere.
- `DenyDataAccessExceptPortalRole` lists **`s3:ListBucket`** beside `GetObject`/`PutObject`/
  `DeleteObject`, on `${bucket_arn}` as well as `${bucket_arn}/*`
  (`infra/modules/data/policies/user-space-bucket-policy.json.tftpl`). That is why the probe's
  listing is subject to the same allowlist a `GetObject` would be.

**Sign in as a member of at least two shared spaces.** Items 0 and 8 both need it.

```bash
API=https://api.dataquarry.app
```

**E.0 — The claims this whole spec reads are actually in the ID token. DO THIS FIRST.**
If it fails, nothing else in the section matters. Capture the ID token from a signed-in session and
decode its payload; confirm `cognito:username` **and** one `custom:shared_space_k` per occupied slot
are present. The inference from `identity-pool.tf` is strong — AWS reads those very claims out of
this very token to stamp today's tags — but it is an inference, and a token that turned out not to
carry them would pass the entire offline suite and fail on the first real request.

```bash
ID_TOKEN='<paste>'
python3 -c "import base64,json,sys;p=sys.argv[1].split('.')[1];print(json.dumps(json.loads(base64.urlsafe_b64decode(p+'='*(-len(p)%4))),indent=2))" "$ID_TOKEN" | grep -E 'cognito:username|shared_space'
```

**E.1 — The trust policy admits the API's role, with BOTH actions.** A statement granting
`sts:AssumeRole` without `sts:TagSession` renders, plans, applies and unit-tests green. Any
successful response from E.6 proves it; a failure that names neither the tag nor the action is what
this looks like when it is wrong.

**E.2 — The tags are stamped, and only the `username` half is observable in this spec.**
There is **no `AssumeRole` event to read**: the account's only trail is one advanced event selector
for data events on the archive bucket, with `is_multi_region_trail = false` and management events
recorded for nothing. A criterion phrased against that trail **cannot fail** — it returns nothing
whether the call happened or not. So the username tag is proved **behaviourally**, by E.6's own
session, against the mechanism recorded above.

> **The slot half is OWED and this spec cannot discharge it.** Every call SPEC-196 ships touches the
> user-space bucket only, and `spaceCount` is counted from the token's claims rather than from the
> session's tags — it reports the same number with the slot tags dropped entirely. The first
> observation that can settle it is a successful user-plane call against a shared space the caller
> belongs to, where the shared-space bucket has no bucket policy and the tag set is therefore the
> entire gate. That arrives with SPEC-198's routes.

**E.3 — The user-space bucket-policy allowlist admits the assumed session.** The IAM simulator does
not fetch a bucket policy, so `aws:PrincipalArn` resolving to the role's IAM ARN under
`sts:AssumeRole` — as opposed to `AssumeRoleWithWebIdentity` — needs a real call through the assumed
session. `GET /_identity/self` is that call, for the mechanism reason recorded above. A principal
the allowlist did not admit would be Denied outright and `ownPrefixListable` would come back
**false**.

**E.4 — Lake Formation still authorizes the session. OWED, and not runnable here.** LF is not
modelled by the simulator at all, and confirming it needs one Athena query on the user plane, for
which there is no route until SPEC-199. Running it by hand from a laptop proves nothing about this
layer — the local IAM user is a different principal.

**E.5 — The cache does not leak in a real warm container.** Two users' tokens, interleaved inside
one execution environment. **Confirm the same `logStream`**, or the observation is two cold starts
and proves nothing. The observation is the two **responses**, not a trail: each body must carry its
**own** caller's `username` and `ownPrefixListable: true` — a leaked session makes the second one's
username wrong, or its `ownPrefixListable` false, because the cached session's tag no longer matches
the prefix it lists. Confirm as well that `logs/service=api/` shows the second request carrying the
second username.

**E.6 — The probe, and both booleans.** Recording only the first proves nothing: an unstamped tag
makes the first false, and an over-granted policy makes the second true.

```bash
curl -s -H "authorization: Bearer $ID_TOKEN" "$API/_identity/self"
# expect: {"username":"...","spaceCount":N,"ownPrefixListable":true,"foreignPrefixListable":false}
```

**E.7 — The records carry a real `env` and a real build sha**, neither empty nor `0.0.0`, and no
record contains a token or an email. Read `logs/service=api/` for the day.

**E.8 — The propagation delay is what SPEC-056 documents, not something new.** Add the signed-in
user to a new shared space and, **without refreshing the token**, confirm the API still refuses that
space; then press **Refresh connections** and confirm the same request now succeeds. Both halves are
required: the first alone is indistinguishable from a broken grant, and the second alone from a
grant that was always live.

### E.9 — The IAM policy simulation, against the DEPLOYED role

**Every denial is paired with an `allowed` control**, because an `implicitDeny` alone cannot
distinguish an ungranted action from a wrong ARN — this repo learned that on `dat-prod-athena-admin`.

```bash
ROLE=$(aws iam get-role --role-name dat-portal-user-role --query 'Role.Arn' --output text)
aws iam simulate-principal-policy --policy-source-arn "$ROLE" \
  --action-names s3:GetObject --resource-arns arn:aws:s3:::dat-prod-user-space/alice/x.csv \
  --context-entries ContextKeyName=aws:PrincipalTag/username,ContextKeyType=string,ContextKeyValues=alice \
  --query 'EvaluationResults[].EvalDecision' --output text
```

| Action | Resource | Context | Expect |
|---|---|---|---|
| `s3:GetObject` | `user-space/alice/x.csv` | `username=alice` | `allowed` (control) |
| `s3:GetObject` | `user-space/bob/x.csv` | `username=alice` | `implicitDeny` |
| `s3:ListBucket` | `user-space` | `username=alice`, `s3:prefix=alice/` | `allowed` (control) |
| `s3:ListBucket` | `user-space` | `username=alice`, `s3:prefix=bob/` | `implicitDeny` |
| `s3:DeleteObject` | `user-space/alice/reports/x.csv` | `username=alice` | `allowed` (control) |
| `s3:DeleteObject` | `user-space/alice/DO_NOT_DELETE.txt` | `username=alice` | `explicitDeny` |
| `s3:PutObject` | `user-space/alice/archive/r.txt` | `username=alice` | `explicitDeny` |
| `glue:GetTable` | `database/alice` | `username=alice` | `allowed` (control) |
| `glue:GetTable` | `database/bob` | `username=alice` | `implicitDeny` |
| `s3:GetObject` | `shared-space/marketing/x` | `shared_space_1=marketing` | `allowed` (control) |
| `s3:GetObject` | `shared-space/marketing/x` | **slot tags absent** | `implicitDeny` |
| `s3:DeleteObject` | `shared-space/marketing/athenaresults/x` | `shared_space_1=marketing` | `explicitDeny` |

**The last two rows are the ones worth the trouble:** the eleventh is the silent-success failure
made visible, and the twelfth proves the Deny is matching rather than merely present.

### E.10 — Cleanup

- [ ] `GET /_identity/self` and `GET /_auth/whoami` are both scaffolding and leave together, deleted
      by SPEC-197 — **on the condition that §D and §E have actually been run and recorded**, not on
      SPEC-197 merely arriving.



## F. The transport contract and the first ported feature (SPEC-197) — MOSTLY RUN 2026-08-30

> **STATUS: F.1, F.3, F.4 and F.6 ran on 2026-08-30** and F.2's header half with them; the
> evidence is in [`sessions.md`](sessions.md). **Still owed: F.5** (the refresh-once path — Amplify
> refreshes *proactively*, so an aged token is not enough to reach it; the refresh must be broken)
> and **F.2 in Safari**, since the tooling here is Chromium and a Chromium pass corroborates
> without discharging.

**What nothing offline can settle.** That the `cpcommon` layer attaches at **cold start** — SPEC-137
shipped instrumented code whose attachment was missing while every offline gate passed. That a real
browser's **preflight** is satisfied by the deployed CORS block; this section exists partly because
the preflight was found broken on 2026-08-27 by a browser and by nothing else. And that an
assumed-role credential minted inside a Lambda actually reaches S3 against the deployed portal role
*through the ported route*.

**Sign in FRESH, signed out to start.** A signed-in pass never tests the token path.

```bash
API=https://api.dataquarry.app
SPA=https://portal.dataquarry.app
```

**F.1 — The feature, rendered. BLOCKING, and the assertion is on the NAMES.**

Open each of the three dialogs that suggest usernames — **`AddMembersDialog`** (Connections → a
space → Add members), **`TableShareDialog`** (a table → Share) and **`SendFilesDialog`** (Files →
select → Send) — and type a prefix of a username you know is in the directory.

- [ ] Suggestions **render**, and they are the names you expected. A `200` carrying an empty array
      looks identical to a healthy but empty directory, so "the request succeeded" proves nothing
      here — the rendered names are the only evidence the whole path worked.
- [ ] In the network panel: **one** request to `GET {API}/v1/user-directory`, status **200**,
      preceded by a **preflight**, with `access-control-allow-origin` **exactly** the SPA origin and
      `cache-control: no-store`.
- [ ] The three dialogs together issue **one** request, not three: the hour-long `staleTime` is
      unchanged by the port.

**F.2 — The preflight, in a browser. BLOCKING, and `curl` cannot settle it.**

This is the check that was failing on 2026-08-27, before the router answered `OPTIONS`.

```js
await fetch('https://api.dataquarry.app/v1/user-directory', {headers: {authorization: 'Bearer x'}})
```

- [ ] The `OPTIONS` preflight returns **2xx** and lists `authorization`, `content-type` and
      `x-request-id` in `access-control-allow-headers`.
- [ ] The request is **sent** — a 401 is the expected answer, and the point is that it was sent
      rather than blocked before leaving the browser.
- [ ] Run it from **both** origins: the container and the CloudFront rollback.
- [ ] **Safari as well as Chromium.** A Chromium pass corroborates and cannot discharge.

**F.3 — The refusals, from `curl`. BLOCKING.**

```bash
curl -s -D - -o /dev/stdout -w '\n%{http_code}\n' "$API/v1/user-directory"
```

- [ ] **401**, envelope-shaped: `{"error": {"code": "SessionExpired", "requestId": "…"}}`, with a
      `requestId` present. Repeat with an expired token and a token from another issuer: all three
      **401**, all three byte-identical apart from the request id.
- [ ] `curl -H 'Origin: https://example.invalid'` on the preflight → **no**
      `access-control-allow-origin`. This is the assertion a `"*"` configuration fails and the
      positive one passes.
- [ ] **Carry a valid bearer for both 404 checks.** The router resolves a principal **before** it
      resolves the route, and refuses an unknown path as *unauthenticated* — deliberately, because a
      404 to an unauthenticated caller tells them which paths exist. Unauthenticated, both of the
      next two answer **401**, and asserting 404 on them fails against correct behaviour. *(Measured
      2026-08-30; this block previously asserted 404 without a bearer.)*
- [ ] `curl -H "Authorization: Bearer $ID_TOKEN" -X POST "$API/v1/user-directory"` — a registered
      path, an unregistered method → **404** `NotFound`, never 405.
- [ ] `curl -H "Authorization: Bearer $ID_TOKEN" -X POST "$API/v1/nope" -d '{"requestId":"spoofed"}'`
      → **404**, envelope-shaped — and the logged `request_id` is the **gateway's**, with
      `client_request_id: null`. `spoofed` must appear in no record.

**F.4 — The correlation key is the gateway's. BLOCKING.**

After the sweep has run for that window, read the record for F.3's last request back from
`logs/service=api/…/data.jsonl`.

- [ ] Its correlation field is the **API Gateway request id**, and **not** `spoofed`. The structured
      logging layer falls back to parsing the event `body` for a `requestId`, and an API Gateway v2
      body *is* a JSON string — so this is a live check of a trap the offline suite also covers.
- [ ] The same record carries `env: "prod"`, a `version` equal to the build sha and neither empty
      nor `0.0.0`, `route_id`, `status` and `actor`.
- [ ] **Absent** from the day's records: any bearer substring, any email address, and the
      `usernames` array. `username_count` is present instead.

**F.5 — The refresh-once path. BLOCKING, and this is the spec that can finally run it.**

Owed since SPEC-195, when `apiFetch` had no caller. It has one now.

- [ ] Leave a tab idle past the token's hour, then open a suggesting dialog. In the network panel:
      **exactly two** requests — the 401 and the retry that succeeds — and the user is **not**
      signed out.
- [ ] Then break the refresh (sign out in a second tab) and repeat: the retry 401s and there is
      **no third request**. A refresh loop against a dead refresh token is invisible in a passing
      offline test and obvious here.

**F.6 — Cold start. BLOCKING.**

- [ ] The **first** invocation after a deploy succeeds. That is the one that exercises layer
      attachment, and the failure mode is silent everywhere else.

**F.7 — Owed, and passed on rather than fudged**

- **The isolation proof.** `GET /v1/user-directory` cannot carry it and does not claim to: the
  `ReadTheUsernameDirectory` grant is unconditioned and the document is byte-identical for every
  caller, so the route returns the same bytes with the principal tag dropped. What it *does* prove
  live is the plane — an assumed-role credential reaching S3 through the API at all. **→ SPEC-198's
  first per-user route.**
- **A live 403 on this plane**, which cannot be staged against a bucket-wide grant. **→ SPEC-198.**

**The ported FEATURES are checked in [`e2e.md`](e2e.md), not here.** SPEC-198's object surface is
§4.2, SPEC-199's catalog surface is §4.3 with three rows in §4.5, and their owed rows are in
[`owed.md`](owed.md). This script proves the arc's *platform* — the container, the boundary, the
transport — and a check on a feature a user drives belongs in the guide beside every other check on
that feature, which is where it will still be after this script is folded in and deleted.

## G. The enqueue paths and the delegated actor (SPEC-200) — PARTLY RUN 2026-08-30

**G.5 and two of G.1's ten rows ran on 2026-08-30** — archive (row 8) and restore (row 9), each end
to end, with G.3's record read back for the archive plane. Evidence in [`sessions.md`](sessions.md).
The other eight rows, G.2 and G.4 are still owed. The paragraph below stands for those.

Nothing below has been executed. The code merged and all four deploy workflows went green on
`b0ad3f5b`, which is the whole of what is verified — every claim about how the deployed system
behaves is offline reasoning until this section is run.

**Do not start until `python3 scripts/watch_ci.py --branch main` is green for the merge sha on
EVERY workflow that merge triggered.** `Deploy App` and `Deploy Infrastructure` race, and an IAM
simulation run before the apply lands reads the exact inverse of the truth on both roles: the
portal role still `allowed`, the API role still `implicitDeny`. Both misreadings point at the code.

**Sign in FRESH, signed out to start.** A signed-in pass never tests the token path.

### G.1 — One request per plane, ten in all

Submitted from the portal UI. The load-bearing part is the **outcome**, not the 200: an enqueue that
answers 200 and lands in the wrong FIFO group still succeeds from outside.

| # | Action | What proves it arrived |
|---|---|---|
| 1 | Create a shared space | the space appears and reaches `active` |
| 2 | Mark one notification read | it stays read after a reload |
| 3 | Build a table | the table appears in the schema browser |
| 4 | Refresh that table | the outcome notification names it |
| 5 | Share a table | the recipient's catalog gains the copy |
| 6 | Run a data-quality check | the report link in the notification opens a report |
| 7 | Send files | they land in the recipient's `shared_files/{sender}/` |
| 8 | Archive a selection | the source is gone and a receipt exists |
| 9 | Start a restore | `restore_started` arrives — the 3–5 h wait is the archive arc's own check, not repeated here |
| 10 | Copy a folder (Arc A's plane) | the copy exists at the destination |

### G.2 — The double-submit guard, per plane

Submit the same gesture twice: **one** outcome, not two.

On **table-share** do it with a forced token refresh between the two submits —
`await (await import('aws-amplify/auth')).fetchAuthSession({forceRefresh: true})` from the console.
One share is the new behaviour and two is the old one; this is the only place the actor-keyed dedup
digest is observable live.

### G.3 — One log record per plane

From `logs/service=api/…/data.jsonl`, waiting for the 10-minute sweep rather than concluding from an
empty query. **Present:** `route_id`, `queue`, `actor`, `message_group_id`, `body_request_id`,
`env: "prod"`, a `version` equal to the build sha and neither empty nor `0.0.0`. **Absent:** any
bearer substring, any email, any object key, any recipient name.

### G.4 — The refusals

- `curl` an enqueue route with **no** `Authorization` → 401, envelope-shaped, and **zero**
  `SendMessage` (a 401 issued after a successful send looks identical from outside).
- `curl` one with a body carrying `actor`, `identity` and the plane's token field → 400
  `InvalidRequest`, nothing enqueued.
- One deliberately oversized selection → **413**, nothing on the queue.

### G.5 — The grants, simulated against the DEPLOYED roles

`aws iam simulate-principal-policy` on `sqs:SendMessage` against all eight request-queue ARNs:

- the **portal role** → `implicitDeny` on all eight, each row paired with an `allowed` control on a
  grant it still holds (an `s3:GetObject` under the caller's own prefix), because an `implicitDeny`
  alone cannot tell an ungranted action from a wrong ARN;
- the **API's execution role** → `allowed` on all eight.

### G.6 — Browser

**Safari** at desktop is the discharging pass, since that is the browser in use. A Chromium pass
corroborates and cannot discharge — record it as such.

### G.7 — Recorded as OWED, not discharged

Anything needing a second account (a shared space where the submitter is a non-owner member), and the
malformed-body DLQ path, which belongs to the drain's own owed check.

## H. The Lambda trust boundary (SPEC-201) — H.1-H.3 and H.6 RUN 2026-08-30

**H.1, H.3 and H.6 are DISCHARGED and H.2 is half discharged, 2026-08-30.** Step one: all eight
planes on cold starts, both notification branches, and the recipient-existence refusal that
exercises the lazy `COGNITO_USER_POOL_ID` read. Step two: four verbs covering both envelope shapes,
after `healthz` confirmed the token-free build. Evidence in [`sessions.md`](sessions.md). Still
owed: **H.2's** non-member / foreign-prefix negatives (a second account), **H.4** and **H.5** (the
API role's `sqs:SendMessage`), and **H.7** (a message must genuinely dead-letter, which needs the
Pipe's delivery to fail).

**This section runs in TWO passes, and running it once after both deploys loses the only
observation that distinguishes "the planes read the block" from "the planes still read the token".**
H.1–H.5 run after **step one** (merged `ff3a76b6`, deployed — `api.dataquarry.app/healthz` reports
that sha), with the API still sending a token beside the block. H.6–H.7 run after **step two**,
which is [#561](https://github.com/agriffi10/data-analysis-prototype/pull/561) and **must not merge
until H.1–H.5 have run** (FR-006 AC2). Step two is the merge that cannot be rolled back.

**Sign in FRESH, signed out to start.** Override `document.visibilityState` before anything that
polls — a hidden Chrome window pauses polling and a healthy query reads as hung.

### H.1 — One real request per plane, all eight, each on a COLD start

Invoke each plane after the deploy rather than after a warm neighbour, or the import is never
exercised. This change removed an import and two required environment variables from a dozen
functions at once, and a shared layer's import-time failure shows only at cold start — the class
that once broke sign-up for nine days while pytest, the deploy job and the instrumentation harness
were all green.

| # | Plane | Do this in the portal | Expect |
|---|---|---|---|
| 1 | shared-space | Create a shared space | It appears, and a notification arrives |
| 2 | table-builder | Create a table from a folder | Table appears in the rail |
| 3 | table-builder | Refresh that table | Succeeds, notification arrives |
| 4 | data-quality | Run a quality check | Report link in the notification |
| 5 | table-share | Share a table with a second user | Recipient annotated, notification |
| 6 | file-send | Send a file to a recipient | Lands in their `shared_files/` |
| 7 | archive | Archive a folder | Receipt written, source swept |
| 8 | file-ops | Copy or move a multi-file selection | Outcomes per item |

Each one must reach its **normal terminal state and produce its normal notification**. A plane that
completes but notifies nobody is the failure mode a hoisted actor read produces, and it is silent.

### H.2 — The load-bearing negative, per plane

A request whose actor names a user who is **not** authorized — a non-member's space, a foreign
prefix, an out-of-root key — is refused with the reason it is refused with today.

**Send it through the API as that unauthorized user.** A hand-crafted body cannot reach the queue
any more, which is SPEC-200 FR-008 working; and the point of the check is that the API writes a
genuine verified `identity.actor` that the plane then declines to act for. Offline this is the
deliberate-violation run (1,1,1,1,1,1,1,2 tests redden); live it is the same claim against a real
principal.

### H.3 — Notifications, BOTH branches, in one pass

1. **Mark a notification read from the UI.** The user path: it carries an identity block, and is
   refused without one.
2. **Confirm the notification a control plane produced in H.1 arrived at all.** This is the
   `create` branch. It has no actor, is written by the execution roles, and is what a
   `trusted_actor` hoisted above `_resolve_username`'s branch silently kills.

A run that only checks mark-read reports success over an inbox nothing can write to. Both, or
neither is evidence.

### H.4 — The staged pre-cutover message

Enqueue one message with the **old** envelope on one plane: a flat `actor` holding a raw JWT, and
no `identity` block.

Expect: refused terminally with `unauthorized`, **no notification**, and the execution visible in
the state machine's history with that reason. **It does NOT dead-letter** — every plane's Pipe is
`FIRE_AND_FORGET`, so `StartExecution` succeeds and the refusal happens inside the execution, so
there is no DLQ record and no `logs/service=dlq-drain/` body for this case. The spec's original
criterion asked for one; it is amended, and looking for it would read as the drain being broken.

### H.5 — `assurance` refused live, with a neighbour

Enqueue one message carrying `identity.assurance: "delegated"` and one carrying
`identity.delegated_by: "svc-x"`. Both refused with `unsupported_assurance`, while a neighbouring
`interactive` message **on the same queue** succeeds. Without the neighbour the refusal proves only
that the plane is broken.

**Aim this at a plane that takes the DEFAULT exception** — table-builder, data-quality, table-share,
file-send, archive or file-ops. On shared-space and notifications the reader is given the plane's
own exception type, which carries a string and no reason code, so the distinction rides the detail
text only.

### H.6 — After step two: one request per plane again

That deploy changes the body every plane receives, and nothing offline sees both sides of it. Repeat
H.1.

### H.7 — After step two: the exposure closed

Dead-letter one message on each of the eight queues — this needs the Pipe's *delivery* to fail, which
is what a real DLQ record requires. Then read the drain's CloudWatch log group and
`logs/service=dlq-drain/` and confirm:

- no three-segment JWT-shaped string in either, and
- the user was notified, with the recipient taken from `identity.actor`.

This is the observation the whole spec is for. It cannot be made offline, and run before H.6 it
fails for the right reason.

### H.8 — Recorded as OWED, not discharged

- **H.4 and H.5 both need `sqs:SendMessage`,** which after SPEC-200 is the API's execution role
  alone. A laptop identity holds no grant, and this session's production AWS writes are
  classifier-blocked regardless of chat authorization — so both go through an assumed session of
  that role driven from CI, or they stay owed. Do not record a proxy as a run.
- **Safari** is the discharging browser, since that is the one in use; a Chromium pass corroborates
  and cannot discharge.
- **A second account** for H.2's shared-space non-member case.

## 14. Cleanup

**Restore the app client's ID-token validity if D.3 was run.** It is shortened to five minutes to
reach the expiry check, and left that way every session in the environment expires in five minutes —
a change nobody would connect back to a test run days later.



- [ ] Delete `arcb_files/`, `arcb_send/`, `arcb_send_moved/`, `arcb_tmp/`, `arcb.sql`, `arcb_report`,
      `arcb_report2`, and the archive created in §8.
- [ ] Delete `arcb_space` (type-to-confirm) and confirm the Glue database is gone from the rail — a
      partial teardown leaves the name locked.
- [ ] Delete the two test users from the User Pool and their prefixes.

## 15. Execution Log

**Recorded before merge 1** (their Terraform outputs do not survive the merges):

| Value | Captured |
|---|---|
| `cognito_identity_pool_id` → `$POOL_ARN_ID` | `us-east-1:b937244c-1632-420d-81af-49838df20233` (2026-08-30) |
| `cloudfront_distribution_id` → `$DIST_ID` | `E63PRJKNACLDP` (2026-08-30) |

| Date | Section | Merge state | Browser | Result | Notes |
|---|---|---|---|---|---|
| 2026-08-30 | §0 — SPEC-193's three additive changes | pre-merge-1 | CLI | **PASS** | All three live. Callback and logout lists each carry `http://localhost:5173`, the CloudFront domain and `https://portal.dataquarry.app`. CloudFront's `connect-src` names `https://api.dataquarry.app`. The API's CORS lists both origins. Nothing was added — verification only. |
| 2026-08-30 | §0 — the deployed trust policy | pre-merge-1 | CLI | **PASS** | `get-role` on `dat-portal-user-role` returns **two** statements: the federated one, and `TheApiMayActAsAUser` admitting `arn:aws:iam::696000197480:role/dat-prod-api-role` with `sts:AssumeRole` + `sts:TagSession` and the eleven-key `sts:TagKeys` ceiling. SPEC-196's statement is applied, so merge 1 leaves the role assumable. |
| 2026-08-30 | §0 — the two ids | pre-merge-1 | CLI | **PASS** | Both recorded above. |
| 2026-08-30 | FR-002 AC3 — the container's `appUrl` | pre-merge-1 | CLI | **PASS** | Task definition `dat-prod-spa:48` sets `CONFIG_appUrl=https://portal.dataquarry.app`, which is `spa_origin`. A container naming CloudFront here would send every sign-in to the other origin. |
| 2026-08-30 | FR-008 — the `connect-src` before-state | pre-merge-1 | CLI | recorded | `spa_origin` serves ten terms, including `cognito-identity.`, `athena.`, `glue.` and `sqs.`. Merge 1 takes those four. |
| 2026-08-30 | FR-008 AC4 — `Server` absent | pre-merge-1 | CLI | **contradiction, not a failure** | `spa_origin` returns `server: nginx`. That is SPEC-194's **first recorded divergence**, not a defect: the distribution stripped the S3 banner and nginx cannot without the third-party `headers-more` module. FR-008's clause was written before SPEC-194 measured it; the spec is corrected rather than the deployment. See `decisions/infrastructure.md` → *The nginx configuration reproduces CloudFront's jobs, and three are divergences*. |
| 2026-08-31 | §11 — `describe-identity-pool` on `$POOL_ARN_ID` | post-merge-1 | CLI | **PASS** | `ResourceNotFoundException`. A positive absence, not "gone from the plan". |
| 2026-08-31 | §11 — `get-role`, one trust statement | post-merge-1 | CLI | **PASS** | Exactly one: `TheApiMayActAsAUser`, principal `arn:aws:iam::696000197480:role/dat-prod-api-role`, `sts:AssumeRole` + `sts:TagSession`. No `Federated` principal remains. |
| 2026-08-31 | §11 — FR-010, the portal role | post-merge-1 | CLI | **PASS** | `s3:GetObject` and `s3:PutObject` on `alice/` → **allowed**; the same two on `bob/` → **implicitDeny**. Every denial paired with an allowed control on the same bucket, so an ungranted action is distinguishable from a mistyped ARN. The retired browser grants stay retired: `sqs:SendMessage` and `athena:StartQueryExecution` both `implicitDeny`. **No row changed from SPEC-196's pre-retirement table.** |
| 2026-08-31 | §11 — FR-010, the API execution role | post-merge-1 | CLI | **PASS** | `sts:AssumeRole` on the portal role → **allowed** (the control). `s3:GetObject` on a user-space key → **implicitDeny** — the one worth the trouble: a stray direct grant would make every route work while silently bypassing the tag. |
| 2026-08-31 | §11 — FR-010, the SPA task role | post-merge-1 | CLI | **PASS** | `list-attached-role-policies` and `list-role-policies` both `[]`. Asserted by absence, **not** by simulation: a role with no policies returns `implicitDeny` for everything with no control available, and an unpaired `implicitDeny` presented as a pass is the failure the rest of FR-010 exists to avoid. |
| 2026-08-31 | FR-008 — the deployed `connect-src` | post-merge-1 | CLI | **PASS** | Exactly `'self'`, `cognito-idp`, the Hosted UI host, both S3 endpoints, `api_origin`. `athena.`, `glue.`, `sqs.` and **`cognito-identity.`** are gone; both Cognito hosts remain, which is its own criterion. |
| 2026-08-31 | FR-008 — the header set, enforcing | post-merge-1 | CLI | **PASS (headers)** | `Content-Security-Policy` (never `-Report-Only`), HSTS `max-age=31536000; includeSubDomains`, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` all present. `server: nginx` present — SPEC-194's recorded divergence, not a defect. **The enforcement half is §7 and is still owed:** a header name is not evidence a policy is enforced. |
| 2026-08-31 | FR-004 — the runtime document | post-merge-1 | CLI | **PASS** | `/config.json` serves **ten** keys and no `cognitoIdentityPoolId`. The running image tag is `85ea5457…`, which is `main`. |
| 2026-08-31 | **§7 — CSP enforcing, with a negative control** | post-merge-1 | Chromium | **PASS** | A `fetch` to `athena.us-east-1.amazonaws.com` raised a **positive** `securitypolicyviolation` with `effectiveDirective: "connect-src"` and `disposition: "enforce"`. The negative control (`/config.json`, same origin) returned **200 in the same run**, so this is enforcement and not a broken network. **The method is now measured, not assumed:** CDP evaluation is exempt from `script-src`, NOT from `connect-src` — SPEC-140's prescription over-generalised from a `script-src` measurement, and this is the correction. Safari re-run owed (§9). |
| 2026-08-31 | **FR-008 — the four absences and the two presences** | post-merge-1 | Chromium | **PASS** | Probed all six hosts in one run. **Blocked:** `cognito-identity.`, `athena.`, `glue.`, `sqs.` — four violations, no more and no fewer, every one `connect-src`/`enforce`. **Allowed:** `cognito-idp.`, the Hosted UI host, `api.dataquarry.app`, the user-space S3 endpoint. The two Cognito presences are the criterion whose omission broke fresh sign-in for a day. |
| 2026-08-31 | **§10 — the rollback rehearsal** | post-merge-1, pre-merge-2 | Chromium | **PASS** | `https://d1kbh4bnvh1je8.cloudfront.net/` loads the app and completes a **real cross-origin API call**: `GET /healthz` → 200, `version` = `85ea5457…` = `main`. Its `/config.json` carries the same ten keys and **no** `cognitoIdentityPoolId`, and its `appUrl` is its own origin. **This is a CloudFront-served HEAD bundle talking to the API — it does NOT restore browser-direct AWS**, because that code is gone from HEAD and so is the pool that backed it. Run in the only window where it is both meaningful and possible. |
| 2026-08-31 | §3, §4, §5, §6, §8 | post-merge-1 | — | **NOT RUN — blocking, and merge 2 is held on them** | Every one needs a signed-in session. Sign-in requires entering a password, which the agent does not do, so these are Andrew's to start: sign in at `portal.dataquarry.app`, then the session can be driven. §8 additionally needs the `arcb_owner` / `arcb_member` fixtures of §2. **§4 is the load-bearing negative and is satisfiable for the first time now** — the pool it was blocked on is gone. |
| 2026-08-31 | §9 — Safari | post-merge-1 | — | **NOT RUN — blocking** | Safari is the discharging pass and the tooling here is Chromium. §7 above corroborates without discharging. |
| | | pre-merge-1 / post-merge-1 / post-merge-2 | | | |
