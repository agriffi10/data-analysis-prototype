# Infrastructure, IAM and delivery

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries the one-line digest of each entry. This file holds the reasoning, the constraints and the
explicit "do NOT build" fences for one area. **Read the entry you need, not the file.**

## Contents

- [IaC](#iac)
- [Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)](#deploy-role-refresh-deadlock-has-an-in-repo-lever-skip_refresh)
- [Response headers / CSP (SPEC-140)](#response-headers--csp-spec-140)
- [Static-asset caching = three prefix-scoped sync passes (SPEC-141)](#static-asset-caching--three-prefix-scoped-sync-passes-spec-141)
- [A build stamp belongs to the artefact; an environment name belongs to the environment](#a-build-stamp-belongs-to-the-artefact-an-environment-name-belongs-to-the-environment)
- [Consolidation is worth doing against a SWEEP, not against a list](#consolidation-is-worth-doing-against-a-sweep-not-against-a-list)
- [Configuration is a runtime document, and a production build has no fallback (SPEC-192)](#configuration-is-a-runtime-document-and-a-production-build-has-no-fallback-spec-192)
- [There is no NAT gateway, and the endpoints are the whole outbound story (SPEC-193)](#there-is-no-nat-gateway-and-the-endpoints-are-the-whole-outbound-story-spec-193)
- [The API function is not in the VPC (SPEC-193)](#the-api-function-is-not-in-the-vpc-spec-193)
- [The image tag is the commit sha, and `:latest` does not exist (SPEC-193)](#the-image-tag-is-the-commit-sha-and-latest-does-not-exist-spec-193)
- [The origins are admitted additively, and narrowed only at the cutover (SPEC-193)](#the-origins-are-admitted-additively-and-narrowed-only-at-the-cutover-spec-193)
- [A Fargate task volume cannot give a non-root container a writable path (SPEC-193)](#a-fargate-task-volume-cannot-give-a-non-root-container-a-writable-path-spec-193)
- [The nginx configuration reproduces CloudFront's jobs, and three are divergences (SPEC-194)](#the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are-divergences-spec-194)
- [The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)](#the-image-is-the-file-set-which-retires-a-reconciliation-pass-and-an-orphan-class-spec-194)
- [`connect-src` comes from the task definition; every other CSP directive is a property of the bundle (SPEC-194)](#connect-src-comes-from-the-task-definition-every-other-csp-directive-is-a-property-of-the-bundle-spec-194)
- [A role that cannot list a bucket cannot be told an object is absent](#a-role-that-cannot-list-a-bucket-cannot-be-told-an-object-is-absent)
- [A value Terraform computes is read from state, never copied into a settings page (SPEC-215)](#a-value-terraform-computes-is-read-from-state-never-copied-into-a-settings-page-spec-215)
- [One image for the whole Lambda fleet, and the sweep that pays for it (SPEC-212)](#one-image-for-the-whole-lambda-fleet-and-the-sweep-that-pays-for-it-spec-212)
- [A cutover is two merges, and only the second one destroys the rollback (SPEC-202)](#a-cutover-is-two-merges-and-only-the-second-one-destroys-the-rollback-spec-202)

## IaC

OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.

## Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)

`deploy-infra.yml`'s `workflow_dispatch` takes an off-by-default `skip_refresh` boolean that adds `-refresh=false` to the apply. It exists because **the deploy role can lock itself out**: tighten (or widen) one of its own grants and the next refresh needs the permission the pending change would restore, so plan, apply **and revert** all fail on the same `AccessDenied`. Applying from cached state installs the fix and unblocks normal runs. **Deliberately unreachable from `push`** — skipping refresh means drift is not detected, so it must be a conscious act; the step emits a warning telling the operator to follow up with an ordinary run, and that follow-up is not optional (an apply that skipped refresh has proved nothing about drift). It replaces the out-of-band `aws iam put-role-policy` break-glass as the *preferred* escape, because it needs no AWS access outside CI — that break-glass stays as the fallback. First use: 2026-08-02, recovering from the SPEC-139 follow-up (`lambda:ListTags` removed from an event-source-mapping statement on the false assumption that the function-scoped grant covered it — a mapping ARN and a function ARN are different resource types). **Caveat worth knowing before trusting any single run:** during that incident `plan` passed twice while `apply` failed on the identical call with no policy change between them, so IAM's eventual consistency can make the deadlock look intermittent — a green plan is not evidence the permission problem is fixed. Full trap list: `infra/info/deploy-role-iam.md`.

## Response headers / CSP (SPEC-140)

> **Superseded in part by SPEC-194 (2026-08-27), on two points.** *Where the policy lives:* both
> CSP locals are at **root** now, not in `modules/app` — a check at root cannot read a local inside
> a module, and that module is deleted when the distribution is retired. The four-input shape
> described below is gone; `connect-src` is assembled at root from the same variables plus the API
> origin, and the module takes the assembled policy as an input. *Who emits it:* the container
> serves the same policy from nginx, with `connect-src` supplied by the task definition and every
> other directive baked in the image. The rules below are unchanged and inherited — enumerate from
> the hosts the app **fetches**, verify with a positive violation event and a negative control (see
> the correction below), diff per alert ID. HSTS `preload` is dropped for the container's domain,
> re-decided.

> **Superseded and CORRECTED by SPEC-202 (2026-09-02), on two further points.** *Where it runs:* the
> distribution, its response-headers policy, its OAC and `modules/app` are destroyed. nginx serves
> the only policy now, and `CKV_AWS_259` — the check the `preload` decision was argued against —
> came off `.github/checkov-enforced.txt` in the same change, because an enforced check ID matching
> no finding is a hard error.
>
> *How to verify one, which is the part that was wrong rather than merely stale.* This entry
> prescribed "a same-origin page script plus a negative control, because CDP evaluation bypasses
> page CSP". What was measured to reach that rule was **`script-src`** (`new Function` reported as
> allowed) — the debugger's script-evaluation exemption — and the prescription generalised from it
> is **unsatisfiable** against a policy carrying `script-src 'self'`: an inline script is blocked and
> an Elements-panel `<script>` is parser-marked non-executable, so the arc's one enforcement check
> had no runnable method and its failure read as a broken snippet rather than as a finding. The
> corrected rule, measured 2026-08-31 against the deployed container: **CDP evaluation is exempt
> from `script-src`, NOT from `connect-src`.** So assert a **positive** `securitypolicyviolation`
> event with `effectiveDirective: "connect-src"` and `disposition: "enforce"`, from an evaluated
> `fetch` to a host the policy excludes, **plus a same-origin negative control in the same run** —
> without the control, a blocked request and a broken network are the same observation.


One `aws_cloudfront_response_headers_policy` on the distribution's default cache behavior carries the browser-facing security posture — **enforcing** CSP, HSTS (`includeSubDomains`, **no `preload`**), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP — and strips `Server` and `x-amz-server-side-encryption`. Four decisions carry the weight. **(1) The CSP is assembled from variables, never literals.** `connect-src` *is* the app's network surface — there is no backend, so anything missing from it is a broken feature — and it is built from `var.aws_region`, the two bucket names and the Hosted UI domain, passed as **constructed strings from root locals** because `modules/app` is upstream of `base → data` and a module reference would be a dependency cycle. A hardcoded region or bucket would have to be hunted down during the client-environment transition. (**Correction 2026-08-04:** the Hosted UI domain was missing from the shipped list, and it broke sign-in outright once the policy went enforcing — Amplify's authorization-code exchange POSTs to `https://<hosted-ui-domain>/oauth2/token`, which is **not** `cognito-idp`, so the returning `?code=` was never redeemed and the app sat signed-out over a live Cognito session. Enumerate `connect-src` from the **hosts the app actually fetches**, not from the AWS services it uses.) **(2) Report-only first is not ceremony.** A CSP wrong about `worker-src` or `style-src` breaks the Monaco editor in production and nowhere else, because no unit test observes a CSP. It earned its keep twice: it caught that `src/index.css:1` `@import`s Inter from `fonts.googleapis.com` (Vite leaves remote `@import`s in built CSS, so an enforcing CSP would have stripped the typeface site-wide), and it exposed that **Safari refuses to evaluate a report-only policy naming no reporting endpoint** — logging "the policy will have no effect" and applying nothing, so a verification pass reports zero violations whether or not any occurred. Chrome and Firefox honour report-only without one, which is exactly why a Chromium-based harness cannot surface it; the same reason CDP `Runtime.evaluate` is useless for CSP probing, since it bypasses page CSP entirely (it reported `new Function` as *allowed* under `script-src 'self'`). Verify a CSP with a **same-origin page script**, and always include a negative control that proves enforcement is live. (**Correction 2026-08-04:** report-only also has a blind spot the promotion to enforcing walked straight into. Report-only **never blocks**, so the sign-in pass that "reported no violations" succeeded *because* the policy was inert, and the one violation it did raise was reported to an endpoint nobody read. A report-only pass proves a flow still works; it proves nothing about whether the flow would survive enforcement. **Read the violation reports, or re-run the flow against the enforcing policy before calling it verified.**) **(3) Three findings are accepted, not silenced.** `Cross-Origin-Embedder-Policy` is absent because `require-corp` buys cross-origin isolation this app cannot use (no `SharedArrayBuffer`, no high-resolution timers) at real risk to subresource loads. `preload` is absent because it declares an intent to submit to hstspreload.org that we do not have, on a shared-suffix `*.cloudfront.net` name a custom domain will replace, and it is near-irreversible once granted — this **fails Checkov `CKV_AWS_259`, whose sole objection is that flag**. (**Update 2026-08-03:** `preload` was flipped on, clearing `CKV_AWS_259` — it is inert without an hstspreload.org submission, so **never submit this `*.cloudfront.net` domain** to hstspreload.org.) `style-src 'unsafe-inline'` stays because Monaco injects `<style>` at runtime — this is a **new ZAP Medium introduced by the fix itself**, and removing it needs per-response nonces, impossible on a static S3+CloudFront origin without Lambda@Edge; `script-src` carries no such allowance, which is the one that matters. **(4) A finding total is not a signal.** `CKV2_AWS_32` clearing and `CKV_AWS_259` appearing cancelled at 305, so the Checkov total looked untouched; ZAP went 20 → 13 while gaining a Medium. Diff **per check ID and per resource**, never by count. Full account: `docs/spec-delivery/SPEC-140-cloudfront-response-headers.md`.

## Static-asset caching = three prefix-scoped sync passes (SPEC-141)

> **RETIRED by SPEC-202 (2026-09-02).** Nothing below runs any more: `deploy-app.yml`, the three
> sync passes, the `/*` invalidation and the static bucket are all deleted, and the image IS the
> file set — no reconciliation, no orphan class, and an honest 404 under `/assets/` instead of a
> stale chunk. The entry stays because two of its findings outlived their mechanism and are the
> reason it is worth reading: **`--exclude` PROTECTS destination keys from `--delete`** (so a pass
> excluding a prefix can never reconcile it — read against the CLI's own `dst_patterns`, after this
> repo stated it backwards in three places at once), and **the bug was the browser cache, not the
> CDN** (reach for the origin object's headers, not an invalidation, when some users see a broken
> app after a deploy). *(Its predecessor marker, SPEC-194's, said the two paths would "retire
> outright with the distribution" — this is that.)*


`deploy-app.yml` uploads `dist/` in **three passes**: hashed assets under `assets/` as `public, max-age=31536000, immutable`, then the shell and root files as `no-cache`, then a repeat of the assets pass carrying the **one** `--delete`. Four things make that shape non-negotiable. **(1) The bug was the BROWSER cache, not the CDN.** The deploy already invalidates `/*`, so CloudFront never served a stale shell; with no `Cache-Control` anywhere, browsers applied **heuristic freshness** to `index.html`, and `--delete` had already removed the hashed bundle that shell referenced — **a white screen, not stale content**, on exactly the users whose cache was warm, and unreproducible with devtools caching disabled. Reach for the origin object's headers, not an invalidation, when the symptom is "some users see a broken app after a deploy." **(2) `--exclude` PROTECTS destination keys from `--delete` — it does not endanger them.** The CLI filters the reverse (destination) generator with the same patterns re-rooted at the destination (`awscli/customizations/s3/filters.py` builds `dst_patterns` beside `patterns`; `subcommands.py` gives `rev_generator` its own filter), so an excluded object is never a deletion candidate. The consequence: **a pass that excludes a prefix can never reconcile it** — `--delete --exclude 'assets/*'` keeps every stale chunk forever. Scope passes by **prefix** (`dist/assets/` → `s3://…/assets/`) so each owns a disjoint key set. (*Corrected 2026-08-04 by the SPEC-141 review, which read the CLI source: the original entry, the workflow comment, and SPEC-141:108-109 itself all stated this backwards — claiming an excluded `index.html` would be deleted. The implementation was never affected; only the reason was wrong.*) **(3) No file may be uploaded by two passes.** `sync` compares size and mtime, and a fresh CI checkout makes every local mtime newer than the bucket's — the first deploy re-uploaded all 108 assets on a byte-identical build, confirming a second pass over the same files would overwrite the immutable header with that pass's `--cache-control`. **(4) Deletions therefore live on their own pass, and the surviving orphan class is a SPEC CHOICE rather than a CLI constraint.** `--delete` scoped to `assets/` leaves stale **root-level** objects behind (harmless, unreferenced, removable by hand). Adding `--delete` to the shell pass **would** reconcile those — `--exclude` protects every asset key from that same deletion (verified against the CLI's `dst_patterns`), and the assets pass still reconciles chunks, so nothing would be retained. What forbids it is SPEC-141's AC "exactly one sync pass carries `--delete`", **written on the same mistaken reading of `--exclude` corrected in (2)**. Revisit the AC deliberately if the manual cleanup becomes annoying; the cost to weigh is that a root-scoped `--delete` removes anything in the bucket not produced by `dist/` (nothing else writes it today). `icons.svg` is the first such orphan. The residual race is **accepted and documented**: a tab already open that lazy-imports after the delete pass still 404s inside `Suspense` — **both** lazy routes are exposed, `/query` (which loads Monaco beneath it) and `/connections`, so a fix must not be scoped to Monaco; closing it needs retained bundles behind an S3 lifecycle rule. Rule of thumb for the whole area: **a content-hashed URL is immutable, a stable URL must revalidate**, and prefer a path prefix over an extension list — `dist/assets/` carries a `.ttf` that a js/css rule would miss. Full account: `docs/spec-delivery/SPEC-141-cache-control-headers.md`.

## A build stamp belongs to the artefact; an environment name belongs to the environment

Every structured log record shipped `"version": "0.0.0"` and `"env": ""` — fields that exist to
correlate a record to a deploy and filter by environment, both inert.

`ENV_NAME` is Tofu's to set and now ships on **every** Lambda from `var.environment`, the same
source of truth as the feature-flag document's `environments` keys. `BUILD_VERSION` is **not**:
Tofu owns the environment map, `update-function-configuration --environment` REPLACES it whole (so
a workflow write would race an apply or be reverted by the next one), and Deploy Infrastructure is
path-filtered to `infra/**` — so a Tofu-set sha would name the last *infra* commit rather than the
code that is running. The stamp travels **in the package** instead, written into every zip by
Deploy Lambdas and read once at import. A missing or unreadable stamp degrades to the sentinel and
**never raises**: this module is on the layer every control-plane verb attaches, and PR #196 is what
an import-time failure there costs.

## Consolidation is worth doing against a SWEEP, not against a list

The reuse pass found that the problem is not missing components — it is existing components being
bypassed and then drifting. Three chip lists were byte-identical until one grew an `h-6 w-6` remove
target and the other two stayed at `h-5 w-5`; `Badge` shipped and
was used by two files while three others hand-rolled it, each differing by a token or two.

That drift was recorded here for years as "24x24" against "20x20", and **neither figure was ever
real**: the spacing scale is rem-derived against a 14px root, so those classes draw 21px and 17.5px
and *none* of the three met WCAG 2.2 SC 2.5.8's 24px minimum — including the one this entry called
correct. The chip's target is now pinned absolutely at `h-[24px] w-[24px]`, because 24 is a
threshold rather than a step on a scale that tracks the root.

The spec enumerated six status-pill sites; the sweep found **seven** (`LandingPage`, whose own
comment said "Mirrors UploadList's StatusChip"). It counted eleven caption sites; the sweep found
**22 files** across three spellings. A `?raw` glob guard now holds each shape to one home, with a
guard-the-guard asserting every needle still matches its owner — because "found nowhere" reads
exactly like "consolidated".

Two deliberate visual changes, on SPEC-155 FR-007's precedent: neutral pills gain a border, and
`QueryHistoryRow`'s neutral dot brightens from `text-text-3` to `text-text-2` now that every dot is
`bg-current`. **Chip width is bounded** for the first time — a 63-character username
(`^[a-z][a-z0-9_]{2,62}$`) extrapolated to a ~610px chip inside a 448px dialog.

**`components/` may export only components** (react-refresh), which is why the shared class strings
live in `fieldStyles.ts` / `dialogChrome.ts` and `displayedMemberStatus` in `memberStatus.ts`.

## Configuration is a runtime document, and a production build has no fallback (SPEC-192)

The SPA reads `/config.json` at startup instead of the `VITE_*` values Vite inlines at build time.
The whole point is promotion: an artifact carrying one environment's bucket names, queue URLs and
Cognito ids can only reach the next environment through a rebuild, and a rollback through a rebuild
of an older commit. Every value is a **string** — the task environment that renders the document is
strings, and a JSON number would add a second parse path with its own failure mode for one key. The
key set was twenty when this was written and is **ten** now: Arc B moved the browser's control-plane
enqueues behind the API, so the eight queue URLs became the API function's configuration and left the
document entirely.

> **Superseded in part by SPEC-215 (2026-09-01):** the third wiring site was "the GitHub repository
> variable" and is now `.github/config-outputs.json`, the one map from Terraform output name to
> configuration key, for every value Terraform computes. Only a genuine *input* is still a variable.
> Full entry: *A value Terraform computes is read from state, never copied into a settings page*,
> below.

**A production build has NO fallback, and `configValue` THROWS before the load resolves.** Returning
`undefined` is the failure the classification exists to prevent — a generic SDK error about a bucket
named "undefined", surfacing far from its cause — so re-introducing it here would make the mechanism
decorative. A **dev** build falls back to `import.meta.env`, including when no load has happened at
all: that is what lets the existing suite read configuration with no bootstrap and without changing a
single `vi.stubEnv` call site. The consequence is that **the entire test suite exercises the arm that
will not exist in production**, which is why the production arm is tested by stubbing `DEV` false and
why the live checks are not optional.

**The fallback is ELIMINATED from the production bundle, and that is asserted on the built output.**
Guarding it is not enough: `readEnv`'s table and the key→variable map are tables of `VITE_` names as
*strings*, and they only disappear if every reference to them sits syntactically inside an
`import.meta.env.DEV` branch. `npm run check:bundle` fails if any `VITE_` name survives in
`dist/assets/*.js`, and it hard-fails on a missing bundle, because "did not run" is never "clean". It
detects the *table*, not an unported call site — Vite substitutes the variable's **value**, leaving no
name behind — so the call sites are pinned separately by a `?raw` sweep to exactly five files.

**A 200 carrying HTML is `unparseable`, not a success.** The distribution answers a missing object
with its own `index.html` under a **200**, so a deployment that never published the document gets a
successful response full of markup. A loader keyed on `response.ok` passes every other test and fails
that one; the fixture is the real `index.html`.

**The document and the feature-flag document look alike and their failure semantics are OPPOSITE.**
The flag document's degraded path is total and silent by design — an unusable one resolves the
compiled-in defaults and still reports ready. This one is a **hard boot failure**: `BootFailure`
renders, no route mounts, and one `console.error` carries the reason and, for a missing required key,
the key **NAMES** — never a value. That narrows the "production stays silent" rule deliberately: the
rule exists so a deployed app does not print its configuration, and a key name is not configuration,
it is the only diagnostic an operator staring at a failed task has.

**`no-store` is not left to the upload's flag.** A document answered from a cache populated in the
previous environment renders a working, fully-functional portal pointed at the wrong account, and
nothing on screen distinguishes it. CloudFront's `Managed-CachingOptimized` applies its **1 s MinTTL
even against an origin `no-store`**, and an object that ever reaches the edge without the header takes
the **24-hour DefaultTTL** — so `/config.json` has its own `Managed-CachingDisabled` behaviour, with
`response_headers_policy_id` re-attached because it is per-behaviour and **not inherited** (omitting
it would serve the document with no CSP or HSTS and stop stripping `Server: AmazonS3`). The
consequence, recorded rather than glossed: after that behaviour lands **no live check can distinguish
a present from a missing origin header**, so the `no-store` negative control was withdrawn and the
header is verified by direct read.

**The bootstrap is a DYNAMIC import, and awaiting the load is not enough on its own.** A module's
static imports are evaluated before its first statement runs, so `import App from './App.tsx'` would
evaluate the whole application graph before the document is fetched, and any module-scope read in it
would throw before the app could render its own failure — in production only, because the fallback
answers in dev and in CI. `main.tsx` therefore keeps five static imports, pinned by a sweep that fails
if the set **grows**, and reaches the app through `await import('./AppRoot')`. The three module-scope
reads that existed are converted as well (`isAmplifyConfigured`, `devS3Client()`, `maxUploadBytes()`),
belt and braces: the dynamic import also protects a read a later spec adds without thinking about boot
order. A **deadline** on the fetch ships with it, because nothing renders until the load settles and
an origin that accepts the connection and never answers would otherwise be a blank page with an empty
console.

Detail: `spec-delivery/SPEC-192`.

## There is no NAT gateway, and the endpoints are the whole outbound story (SPEC-193)

The private subnets carry no default route of any kind. A Fargate task reaches ECR through
`ecr.api`, `ecr.dkr` and `logs` interface endpoints with `private_dns_enabled`, and reaches the image
layers through an S3 **gateway** endpoint whose prefix-list route is what makes it reachable without
a default route at all. A NAT gateway would cost about $32/month per AZ before a byte moves, and —
the part that matters more — it would silently widen the blast radius of every future task from "the
AWS services we enumerated" to "the internet".

**The residual is a connect timeout, and it is the reason flow logs are on.** A destination nobody
added an endpoint for does not fail fast; it hangs, and a hang leaves nothing behind. Flow logs are
the only record of a rejected packet in a design whose premise is that certain traffic cannot leave.

**The no-NAT assertion is repo-wide rather than module-scoped**, because scoped to the network module
it would be satisfied by adding the gateway somewhere else — which is exactly what a quick fix for a
mysterious timeout looks like.

**Verified live, and only live.** `runningCount == 1` with no `CannotPullContainerError`, read
**beside** `describe-route-tables` showing local + prefix-list and no `0.0.0.0/0`. Without that
pairing, a pull that succeeded through a route somebody added reads as proof of the endpoints.

Detail: `spec-delivery/SPEC-193`.

## The API function is not in the VPC (SPEC-193)

The VPC exists for the container. Attaching the API function would need an interface endpoint per
service it later calls and would put ENI attachment on the cold-start path — and after the arc's
provider swap the token-verification host is a third party with **no AWS endpoint at all**, so a
function inside those subnets would stop verifying with no code change to blame.

Asserted as an **absence** (`vpc_config`, `aws_security_group`, `subnet_ids` forbidden in the module),
because a `vpc_config` added later shows up only as latency until the day it shows up as a timeout.

Detail: `spec-delivery/SPEC-193`.

## The image tag is the commit sha, and `:latest` does not exist (SPEC-193)

The ECR repository is `IMMUTABLE`. An image is therefore what its tag says it is for as long as the
revision referencing it exists, and a re-push under an existing sha cannot silently change what a
rolled-back task definition starts.

> **Extended by SPEC-212 (2026-09-01).** There are now **two** registries on this rule — the SPA's
> and the Lambda fleet's — and everything below still holds for both. What differs is the
> retention bound: the SPA's is thirty images, a rollback window measured in deploys, while the
> fleet's is computed from the merge rate against a window measured in days, because the failure it
> rolls back from surfaces at a cold start rather than at a deploy. Full entry: *One image for the
> whole Lambda fleet*.

**The consequences are not cosmetic.** There is no `:latest` to point a task definition at, so the tag
is a **variable** (`spa_image_tag`) rather than a constant — a fixed placeholder tag could be pushed
exactly once, ever, and a bad first push would burn it. And a tag cannot be re-pushed after a bad
build: the fix is a new commit, not a retry.

**The service's `task_definition` is in `ignore_changes` and its `desired_count` is NOT**, which is a
division of ownership with teeth. CI owns which revision runs — so **CI must point the service**, and
a pipeline that only registers a revision leaves the service on the old one, failing with a
`CannotPullContainerError` that reads exactly like the endpoint failure this platform is tested for.
Terraform owns the count, because raising it from 0 to 1 is a verification step and an ignored
attribute would make that step a silent no-op.

Detail: `spec-delivery/SPEC-193`.

## The origins are admitted additively, and narrowed only at the cutover (SPEC-193)

The Cognito app client's callback and logout lists, CloudFront's `connect-src`, and the API's CORS
list each gained the new origin **beside** the existing one. Nothing was removed.

An allowlist naming one origin makes the other a rollback that cannot be exercised. The narrowing
belonged to the spec that retired the distribution, deliberately last, and **SPEC-202 did it in the
same merge as the destroy** — after the rollback had been rehearsed against the container origin
while both were still admitted. Each addition was verified to have removed nothing, because a
"replace" where an "add" was intended applies green and is invisible until the day it is needed.

**The three lists are now one origin each** (plus `localhost:5173` on the callback list and both
bucket CORS rules, which is dev, not a second deployed origin): Cognito's callback and logout lists,
the API's CORS `allow_origins`, and both buckets' CORS. The container's `connect-src` is the fourth
list of the same kind and narrowed in the merge before, since it is served from the image rather
than from an allowlist.

Detail: `spec-delivery/SPEC-193`.

## A Fargate task volume cannot give a non-root container a writable path (SPEC-193)

`readonlyRootFilesystem: true` and a non-root `user` need writable mounts, and the mechanism is
**`linuxParameters.tmpfs`**, whose `mountOptions` take `uid`, `gid` and `mode`. It is measured, and it
reverses two earlier statements of the opposite.

**A task-level volume arrives as a fresh, EMPTY, root-owned directory and does not initialise from the
image.** The container printed `uid=101(nginx)` beside `drwxr-xr-x root root /var/cache/nginx` — a
path the base image ships owned by 101. nginx then died on `mkdir() "/tmp/proxy_temp" failed (13:
Permission denied)`, which reads as a container bug and is not one. `volumes` + `mountPoints`,
`readonlyRootFilesystem` and a non-root user are **any two of the three**.

**The uid is ONE value** feeding both the container's `user` and every mount option. Split, the mount
is silently unwritable by the process that needs it — which is this entire failure in one line — and a
test pins them together.

**Do not "fix" a permission error here by seeding the image or by widening the user.** Seeding `/tmp`
with an owned directory was tried and changed nothing, because nothing is copied.

Detail: `spec-delivery/SPEC-193`.

## The nginx configuration reproduces CloudFront's jobs, and three are divergences (SPEC-194)

The SPA moved from a distribution over an S3 origin to a container behind a load balancer. Producing the image is trivial — a Vite build served by nginx — and **that triviality is the trap**: the distribution was doing five other jobs, each configured once and then invisible, and **every one fails silently when it is wrong**. A missing fallback breaks only deep links and only on reload. A wrong cache header runs last week's bundle intermittently, on exactly the users whose cache is warm. A CSP missing one host breaks one flow days later. A health check that falls through to the shell makes the balancer call a broken container healthy and keep it in rotation forever. So each job is either reproduced or named as a divergence out loud, and the whole set is asserted **on responses** by a CI matrix — grepping the config passes on a config nginx never loaded, on a server block that lost to another on the same port, and on a header wiped by the inheritance rule below.

**`add_header` inheritance is what makes this configuration fragile in a way no review catches.** nginx inherits `add_header` from the enclosing level **only when the current level defines none of its own**. Each location sets its own `Cache-Control`, which on its own **wipes every security header from that location's responses** while the rest of the site looks perfect. Every location therefore `include`s one shared snippet, and every directive carries `always` — measured: without `always`, the `/assets/` 404 carried **no** `Cache-Control` and **not one** security header while the 200 beside it carried all of them. Two further shapes were measured rather than reasoned: `return 404;` with **no body string** emits nginx's stock HTML page and ignores `default_type` entirely; and a 404's content-type follows the **request's extension**, because nginx fixes it before `error_page` runs — so the criterion is "not HTML", never "is `text/plain`", which would redden truthfully and be "fixed" by weakening it.

**Responses generated before a location is resolved reach none of that.** A malformed request line, a malformed header field and an over-long URI are answered by nginx before it picks a location — measured, they came back as HTML with no `Cache-Control` and no security header at all, which is precisely the shape the per-location discipline exists to prevent, arriving by the one route it cannot reach. The set is declared at the **server** level as a floor, where the same inheritance rule works in our favour: a location setting its own header still overrides it, so every cache class is unchanged.

**The three divergences, each with its cost and its re-open trigger.**

1. **`Server: nginx` remains.** The distribution stripped the S3 origin's banner. nginx cannot: `server_tokens off` hides the *version* and nothing more, and removing the header needs the third-party `headers-more` module, which the official images do not ship. The alternative is a build stage compiling it against the runtime base's exact source, recompiled in lockstep with every base bump, where an ABI mismatch stops nginx starting — real maintenance coupling for a banner that now discloses only "nginx". The scanner alert that motivated the strip fires on a **version**, so it does not regress. Re-open trigger: a client security review objecting to the banner.
2. **gzip only, no brotli.** `gzip_static` over `.gz` siblings produced at build time gives every asset a maximum-ratio artefact at no per-request CPU. Brotli needs the same third-party compile stage, and accepting it there while refusing it above would be incoherent. **The residual is real and not papered over:** brotli-capable browsers — effectively all of them — receive gzip, so the bundle transfers roughly 15–20% larger than through the distribution. Moves with the trigger above.
3. **HSTS drops `preload`.** It was flipped on to clear a scanner check and is recorded as inert — browsers act on the preload list and entry needs a manual submission. Emitting it claims a submission this deployment has not made and does not intend; the grant is against the **registrable domain** and close to irreversible, and these are subdomains of a parent this repository does not own, so the claim would commit sibling services nobody asked. It costs no finding, though not for the reason it first appears: **`CKV_AWS_259` is a CloudFront check**, evaluated against `aws_cloudfront_response_headers_policy.portal` — which still carries HSTS with `preload` and still passes it. nginx's header is invisible to that check, so dropping `preload` on the container origin regresses nothing. **When the distribution is deleted, `CKV_AWS_259` must come off `.github/checkov-enforced.txt` in the same change**: an enforced check ID matching no finding is a hard error, which is the gate working as designed.

`x-amz-server-side-encryption` needed no decision and gets no criterion: it was the S3 origin's banner, there is no S3 origin, and there is no route by which nginx could emit it. An assertion about it could not fail, and stating it as evidence would misrepresent a consequence as a control.

## The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)

The S3 delivery path needs three prefix-scoped sync passes because one pass cannot both write a single `--cache-control` and reconcile deletions, and its single `--delete` is scoped to `assets/` — leaving an accepted orphan class of stale **root-level** objects removable only by hand. **A container has neither problem.** The image *is* the file set: nothing to reconcile, no key surviving a build, no pass ordering. Both the `--delete` pass and the orphan class cease to exist for that path — a settled decision retired by shipping rather than by argument.

**One improvement, and one residual that changes shape for the worse.** Under `/assets/` the container answers an **honest 404** for a missing hashed chunk, where the distribution returned `index.html` as `text/html` to a `<script type="module">` request — which failed the MIME check anyway, more confusingly, and with no way to tell "removed" from "never existed". At the root the 200-with-`text/html` trap is **preserved deliberately and pinned by a test**, so a later change to the fallback is visible rather than silent; it remains the reason a removal is never verifiable by status code here. The residual: on the S3 origin the bucket held the union of old and new until the delete pass ran, so an open tab lazy-importing a removed chunk had a window. A task serves exactly one image's file set, so during a rolling deployment a browser holding the **old** shell routed to a **new** task 404s immediately and deterministically. The `no-cache` shell means a reload recovers, as before. Accepted, and recorded so it is not rediscovered as a container defect.

## `connect-src` comes from the task definition; every other CSP directive is a property of the bundle (SPEC-194)

**The seam.** `connect-src` **is** the app's network surface and the only environment-shaped directive, so it arrives as one environment variable the task definition supplies. `default-src`, `script-src`, `style-src`, `img-src`, `font-src`, `worker-src`, `object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` all describe the **bundle** — what it may execute, style, fetch a font from, spawn a worker as — and ship baked in the image. Baking the whole policy would carry one environment's hosts everywhere, which is exactly the build-time-configuration failure the runtime-configuration document exists to end; supplying the whole policy from the task definition would put the bundle's own properties in the hands of whoever edits an environment map.

**Both CSP locals live at root, and that placement is load-bearing three ways.** A check at root **cannot read a local declared inside a module**, so the byte-identity and agreement assertions would have had no readable referent. `modules/app` was **deleted outright** with the distribution (SPEC-202), which would have orphaned the computation the container depends on. And one computation feeding both delivery paths is what stopped them drifting into enforcing different policies while both were live — there is one path now, and the placement is what survived the deletion intact. The move was proved to be a move: the directive list was compared term by term, in order, against a recorded copy of the **pre-move** string — a comparison re-derived from the new source would only assert that the file equals itself — and the plan against real state reported **no changes**. Two mutations initially escaped that guard and are worth keeping in mind for any similar check: an element regex reading **quoted strings only** was blind to `local.api_origin,` appended to the list, and nothing asserted the **join separator**, without which a policy joined on a space is one malformed directive with every other directive dropped by the browser and all twelve elements still present.

**Anything interpolated into nginx configuration must be validated, because nginx has no escaping mechanism.** Measured: a `connect-src` value carrying a `"` closes the directive it sits in — `object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` all silently gone — while a trailing `;` appends a directive of the attacker's choosing, on a container that **starts, reports healthy and enters the target group**. A value that does not parse is barely better: nginx dies with `[emerg]` naming no variable, which is the generic essential-container exit this image is otherwise written to avoid producing. Both interpolated values are validated against what they may contain rather than scanned for what they may not — an allowlist cannot be outflanked by a character nobody thought of. The same reasoning already governed the configuration document, which is rendered with `jq -n --arg` and never a heredoc.

**The removal-owner table matters as much as the list.** On the day the container shipped, `connect-src` was every host the response-headers policy enumerated **plus the API host**, because nothing had been ported. It shrank one entry at a time as the porting specs landed and reached its end state at SPEC-202 — `'self'`, `cognito-idp`, the Hosted UI host, both buckets, the API — and **it did not lose the Cognito hosts**: Amplify keeps running in the browser, so the User Pool endpoint and the Hosted UI domain are still fetched from. That is the highest-consequence mistake available here, and the reason a test names those two entries separately from any set comparison — a reader holding the arc's end state in mind deletes them on purpose, and would then update a whole-list assertion to match the mistake. The failure is **invisible to an already-signed-in session**: the authorization-code exchange is the only fetch to the Hosted UI host, a warm tab never makes it, so the portal looks perfect to whoever is testing while every new sign-in sits signed-out over a live session.

## A role that cannot list a bucket cannot be told an object is absent

S3 answers `NoSuchKey` for a missing object only to a caller holding `s3:ListBucket` on that
bucket. To a caller without it, the same missing object is `AccessDenied`. So any code shaped
`except NoSuchKey: return None` has a branch that is reachable only if the execution role behind
it can list — and where it cannot, the absence path fails as a fault, at exactly the moment the
absence is the answer the caller wanted.

**Found in production.** On 2026-08-17 a file send naming an unregistered space raised
`AccessDenied` out of `cpcommon/registry.py:30` under `dat-prod-file-send-execution-role`. That
function returns None for "no such space" and every plane's authorize step is written around the
None; the role held no `s3:ListBucket` statement on the admin bucket at all, so instead of the
`unknown_space` refusal the user got a failed run. Archive, data-quality, table-builder and
table-share had the identical gap, and file-ops hit the same rule on its plan read.

**A conditioned grant is sufficient; having no statement is what breaks.** This is the part worth
writing down, because the intuition runs the other way and an IAM simulate appears to confirm the
wrong answer: `simulate-principal-policy` returns `implicitDeny` for a prefix-conditioned
`ListBucket` when no `s3:prefix` is supplied, which reads as "a `GetObject` carries no prefix, so
the condition fails closed." Production says otherwise. `dat-prod-notifications-writer-role` holds
exactly one list grant, conditioned on `*/user_settings/notifications.json`, and no unconditioned
list anywhere; `load_inbox` returns `[]` only through its `NoSuchKey` branch, and the structured
logs carried, when this was measured on 2026-08-30, thirteen writes at `notifications=1` across
eleven recipients, with the cap at 200 and
every other user's inbox climbing 1→64. Those are eleven first-ever inboxes read as absent. The
one other path to an empty list is a document that exists and is corrupt, and it is ruled out in
the right place: that warning is a **stdlib** logger call, so it reaches CloudWatch rather than the
structured-log corpus, and CloudWatch for that function carries neither it nor an `AccessDenied`
for the life of the grant, which has been conditioned since the day it was written. **A simulate answers what IAM
decides given the context you supply; it cannot tell you what the service supplies**, and that
gap is the same shape as the two traps `deploy-role-iam.md` already records.

So the rule is about the statement, not the condition: **every role must hold a `ListBucket`
statement on each bucket whose absence it reads, scoped by condition to the keys it actually
reads.** Do **NOT** widen to an unconditioned list to be safe — on the admin bucket that hands a
plane every shared space's name and then every roster, which is the disclosure the project
declines by publishing no shared-space directory; the space name is the only thing gating that
read. And do **NOT** fix this by treating `AccessDenied` as absence in code: that makes a real
denial look like a fresh request, and on a create-and-copy path it plans over work already in
flight. Where a denial genuinely must be tolerated it is because the write that follows is
create-only, and `shared-space-common/cache.py` is the one site that earns it.

The population is derived, not listed. `lambdas/test_absence_is_answerable.py` walks the AST of
every production module to find each read whose handler decides absence — resolving codes hidden
behind module constants, behind predicate helpers, and behind a reader one call below the `try`,
each of which hid a real site while the sweep was being written — and requires every one to carry
a disposition. The planes held to the registry grant are derived from their imports, counting
`from cpcommon import registry as reg` as well as the submodule path, so a new plane joins the
population by existing.

Two holes in that claim were found by review and closed, and both are worth knowing because they
are the shape this kind of guard fails in. **A derived population still needs a total mapping:**
the first version resolved a directory to a policy through a list of the six control planes, so
adding a registry read to the DLQ drain — whose policy has no `ListBucket` at all — left the suite
green. An unmapped directory is now a hard failure, which is what makes "cannot be added without
meeting it" true rather than aspirational. **And the plane that OWNS the data was pinned by
nothing:** shared-spaces reads the registry back through its own module rather than through
`cpcommon`, so the import sweep could not see it, and deleting its `AdminRegistryList` left the
whole suite green. It has its own assertion now.

## A value Terraform computes is read from state, never copied into a settings page (SPEC-215)

The publishing workflows init the same backend `deploy-infra.yml` uses and read
**one** `tofu output -json` per job, mapping output names to configuration keys through
`.github/config-outputs.json`. The values had been repository variables a person read out of `tofu
output` once and typed into a settings page, which made a human the transport between the thing that
computes a value and the thing that serves it.

**The failure that arrangement has, this repo had already met twice.** An unset repository variable
interpolates to the **empty string**, which satisfies a required Terraform variable *and* overrides
its default — `deploy-config.yml` carried a hand-written guard for exactly that, because the symptom
was an `s3:///_config/…` copy failing far from its cause. And a value that moved in infrastructure
stayed wrong in the browser until somebody re-copied it, which is precisely what the runtime
configuration document exists to prevent: a repoint should not be a rebuild, and it should not be a
settings page either.

**What decides whether a key belongs in the map or stays a variable is not convenience — an input
cannot be read from the thing it configures.** `AWS_REGION` names where the state lives, so it is
needed to assume the role *before* an output can be resolved. `VITE_APP_URL` feeds `TF_VAR_app_url`,
from which Cognito's callback list is built. `environment` and `maxUploadBytes` are policy, not
resource attributes. Everything else is derived, and a derived value in the settings page is a second
copy that nothing reconciles. **A surviving variable with no such reason is one that should have been
retired**, which is why the reasons are written per-variable in `.github/workflows/README.md` rather
than asserted collectively.

**The refusal is loud and it is one refusal.** `resolve-config.sh` fails the job on an output that is
absent **or empty**, naming both the configuration key and the output, and reporting every fault at
once rather than one per deploy cycle. Emptiness is the thing checked because it is what satisfies
every presence test there is. It is deliberately stricter than the served document's own `REQUIRED`
list: every mapped output is a value Terraform always computes, so an empty one means the state is
not what the deploy assumes, whatever the browser's degraded path for that key would be. The
document's `REQUIRED` guard stays, unchanged, answering the different question of what may be
published. The hand-written empty-variable guard in `deploy-config.yml` was **replaced**, not kept
beside it.

**Do NOT introduce a second copy of the values** — SSM Parameter Store, a generated tfvars, a cached
outputs artifact. State already holds them; writing them somewhere else to read them back adds a
resource type, its deploy-role IAM, and a second thing that can be stale. **No new grant was needed
and none was added:** the deploy role has held `s3:GetObject` and `s3:ListBucket` on the state bucket
since the backend existed, and `lambdas/test_config_outputs.py` asserts that rather than assuming it.

**Two couplings the change creates, both guarded because both fail silently.** Resolving `appUrl`
from `cloudfront_domain` while `TF_VAR_app_url` stays a variable makes them two independent
statements of one origin; before, they could not disagree. A divergence sends a sign-in started on
the portal back to an origin Cognito does not allow — a broken sign-in with nothing red anywhere — so
the app deploy compared them and refused. The comparison lived there rather than in a
Terraform `precondition` on purpose: being wrong there costs a skipped deploy with the live document
untouched, where a precondition would put the same claim in front of every infrastructure apply.
**(SPEC-202, 2026-09-02: the coupling is gone with `cloudfront_domain`, `var.app_url` and
`deploy-app.yml`. `appUrl` resolves from the `spa_origin` output and the Cognito callback and logout
lists are built from `var.spa_origin` — one statement of one origin, so there is nothing left to
compare. The reasoning is kept because the next two-statements-of-one-origin will look exactly like
this one.)**
Second, `deploy-config.yml`'s matrix names a configuration **key** rather than a variable, and
nothing checked that the key was resolvable — a typo would resolve to the empty string and target
`s3:///_config/…`, the exact failure the old guard existed to catch. `validate_feature_flags.py`
cross-checks it against the map, before any AWS call.

**The version agreement is derived on "declares an OpenTofu version", not on "runs `tofu init`".**
A workflow can read an output through the resolver without an init of its own — SPEC-214 does exactly
that — so an init-based predicate would exclude the consumer the derivation was widened for. The
assertion compares the constraint strings **as declared**, because `~1.8` is a constraint and not a
version, and "they resolve to one version" is not something a workflow file can state.
## One image for the whole Lambda fleet, and the sweep that pays for it (SPEC-212)

Eighty-six functions ship as zips with ten shared layers attached in a literal order. Everything
hard about that arrangement is hard for one reason: **what a function can import is decided at
deploy time, by a join between two JSON tables, and is observable nowhere else.** A missing layer is
a `ModuleNotFoundError` at the next cold start, in production, behind a green suite — which
happened, and lasted nine days.

The image replaces the join with an artefact. Dependencies installed once, shared code copied once,
every function running the same image with a different command. What a function can import becomes
a property of something you can pull and run.

**The layout reproduces the zip and the layer exactly, and that is measurable rather than hopeful.**
Shared code lands on `/opt/python`, function modules at `${LAMBDA_TASK_ROOT}` with the function
directory's own level stripped. Measured against the base image through its bundled Runtime
Interface Emulator: the container runtime's bootstrap puts `/var/task`,
`/opt/python/lib/python3.12/site-packages` and `/opt/python` on `sys.path` **with no `PYTHONPATH`
involved**, so both a package and a flat module resolve and no import statement changes.

**Dependencies are NOT on `/opt/python`, and that is the one deliberate divergence.** A layer today
mixes its package with its pip-installed dependencies in one directory; reproducing that would make
"the set of packages under `/opt/python` equals the set the layer table declares" false by
construction, and the guard would decay into a hand-maintained dependency list. The cost is that
repository code now sits **ahead** of the dependencies on the search path, which a layer never did —
so a third guard asserts no repository module shadows an installed one.

**One task root for eighty-six functions is a hazard no zip had.** Every function's modules share
`/var/task`, and the runtime searches it before `/opt/python`. Two directories contributing the same
path do not collide — one silently wins, for the whole fleet. A module named `config.py` would
shadow the shared-space layer's `config` for eleven verbs. Both are measured empty today and both
are asserted **against the built image**: an absence asserted against a source tree proves nothing
about an artefact, which is the same reason the arc exists at all.

**The image is strictly wider than the zip, and the sweep is what pays for it — not the packaging.**
Stated rather than glossed: every function can now import every shared-space flat module. An AST
sweep over the **function** directories forbids it outside that plane, counting attribute-style
usage as well as `from x import y`, with an exemption list of exact paths. The population is
function directories rather than every directory under `lambdas/`, because the layer's own source
imports its own modules and sweeping it invites the wrong repair.

**Two things the matrix had to get right, both measured rather than reasoned.**

**It runs the imports through the runtime's own bootstrap.** `docker run --entrypoint python` gives
a `sys.path` with neither `/opt/python` nor its site-packages on it, so a sweep taken that way must
rebuild the path — and a rebuilt path that is a **superset** of the real one passes an import that
production fails. That is this arc's own failure mode, rebuilt by the tool meant to prevent it. The
sweep is instead invoked as a handler through the emulator, reads its own live `sys.path`, and hands
it to one subprocess per module; the subprocess path comes back **identical**, so there is nothing
to reconstruct and nothing to police.

**A count compared with itself is not a guard.** The first version derived the expected number of
handlers the same way the image-side sweep did — a module defining a top-level `handler`. Renaming
one removed it from **both** sides, the two numbers agreed at 85, and a planted mutation that broke
a function's entry point passed the whole matrix. The expectation now comes from the deploy table,
which is maintained separately. SPEC-214 deletes that table; when it does, this expectation
repoints at whatever replaces it and does **not** fall back to the sweep.

**The fences.**

- **The container runs `--read-only` with a tmpfs `/tmp`**, which is the filesystem Lambda gives it.
  Not only fidelity: importing eighty-six modules writes bytecode beside every one of them, so on a
  writable root the sweep manufactures the `__pycache__` offenders it then reports.
- **The emulator serves one invocation at a time.** A readiness probe that posts to the invocation
  endpoint starts the real sweep and the retry collides with it — `ReserveFailed`, and the emulator
  panics. Wait for any HTTP response on any path instead.
- **The base image has no `find` and no `xargs`.** A `RUN find … -delete` prune exits 127. The
  assembler is Python, which is the one tool a Python runtime image is guaranteed to have — and
  being a module rather than a shell line is what lets the layout tests import the same definition
  the build uses.
- **The build context is the repository root with `lambdas/Dockerfile.dockerignore`.** BuildKit
  reads a Dockerfile-specific ignore file in preference to the context root's; the root file
  excludes `lambdas` on purpose, so that the SPA's build — which asserts its absence — keeps working.

## A cutover is two merges, and only the second one destroys the rollback (SPEC-202)

Every spec in the API-and-container arc was **additive** — two front doors, two credential paths,
each step revertible because the thing it replaced was still running. The retirement is the
subtraction, and subtraction is where this repo's characteristic failure lives: nothing goes red when
a dead distribution keeps answering, nothing goes red when the browser holds credentials it no longer
uses, and nothing goes red when a `connect-src` still names four AWS hosts no request goes to. **A
half-finished retirement looks exactly like a finished one.**

So the shape is two merges whose difference is whether they can be undone.

- **Merge 1 retires, and touches nothing that serves the app.** The Identity Pool, the browser's last
  credential modules, the lint rule, the container's narrowed `connect-src`. CloudFront still ran,
  its `connect-src` still named the API, the callback and logout lists still named both origins and
  both buckets' CORS still allowed both — so the front door could still be moved back and the app
  would work.
- **Then the live checks run, with that rollback intact.** This is the whole reason for the split:
  the arc's load-bearing negative cannot be observed while the Identity Pool exists (see the identity
  register), and the rollback rehearsal is only meaningful in the window where the old origin still
  serves.
- **Merge 2 narrows the three allowlists and destroys the distribution.** After it there is no
  rollback at all: no origin serves the old front door and no allowlist admits it.

**What the rollback actually was, stated because it is easy to overstate.** The rehearsal loaded the
app from the CloudFront domain and completed a real cross-origin API call — a CloudFront-served
**HEAD** bundle talking to the API. It did **not** restore browser-direct AWS, because that code was
already gone from HEAD and so was the pool that backed it. A rollback of the front door is not a
rollback of the arc.

**A grant outlives the resource it covers by one apply, deliberately.** The deploy role's
`cloudfront:*` and static-bucket statements were left standing through the destroy and removed in the
next change, because removing a grant in the same apply that destroys what it covers is the refresh
deadlock [`deploy-role-iam.md`](../../infra/info/deploy-role-iam.md) records. The follow-up found
the trap that ordering hides: **the accept list was holding the grant's own findings open.** Both
accepted Checkov plan findings on the deploy role were that `cloudfront:*` statement, so removing it
made both acceptances match nothing — and a stale accept is a hard error, which would have failed
the grant-removal PR on its own gate. Measured with the pinned scanner rather than argued, which
also corrected the accept list's stated reason: an action AWS defines no resource type for raises
neither check (cloudsplaining strips it first), so `cognito-idp:CreateUserPool` and the Lake
Formation account actions were never co-causes. **What raises them is an action that could have been
scoped and was not.** The list is empty now and every IAM finding on the plan blocks.

**The waiver is part of the record.** Merge 2 was taken with four checks open — a fresh sign-in from
a clean profile, the deep-link return path, the archive plane's row and 400px — recorded as *waived,
not passed*. The one that gates that merge specifically is the fresh sign-in, because merge 2
narrows the Cognito lists and **a broken fresh sign-in is invisible to every signed-in session**; the
arc's own §12 re-runs it after the irreversible step instead of before it, which is the risk that was
accepted. Whether it has been run is [`owed.md`](../testing/owed.md)'s to say, not this entry's.
