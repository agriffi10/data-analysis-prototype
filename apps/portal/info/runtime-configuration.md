# The runtime configuration document

The SPA reads its configuration at **runtime**, from a same-origin `/config.json` fetched once before
the first render. A `VITE_*` variable is inlined into the bundle at build time, so an artifact built
that way carries one environment's bucket names, queue URLs and Cognito ids everywhere it is
promoted. The document is what makes `dev → prod` a repoint rather than a rebuild, and a rollback a
repoint back.

The loader is `lib/runtimeConfig.ts`; the shape and its key classification are
`types/runtimeConfig.types.ts`. Both are listed in the component inventory
([`foundations.md`](component-inventory/foundations.md),
[`shared-types.md`](component-inventory/shared-types.md)).

## The contract

- A JSON object with a numeric `version` (currently `1`) and **string** values for every classified
  key. A wrong version is refused **whole**.
- **An empty string reads as unset.** An empty `TF_VAR_`/repo variable satisfies a required variable
  *and* overrides a default, so the emptiness has to be the thing that is checked.
- **A key the build does not classify is ignored**, so a task definition running ahead of an image
  cannot break the boot.

## The rules that hold it up

- **Same-origin, never proxied.** The SPA has to render its own error states while the API is down,
  so the document is served by the SPA's own server.
- **`Cache-Control: no-store`.** A document answered from a cache populated in the previous
  environment renders a working, fully functional portal pointed at the wrong account, and nothing
  on screen distinguishes it. The container sets the header on `/config.json` in its own `location`
  block, and the container matrix asserts it **on a response** rather than in the config text.
  There is no second delivery path to keep in step: the distribution that needed its own
  per-behaviour cache policy and its own re-attached header policy is retired, and with it the
  shape where two paths could serve the same document under different headers.
- **A production boot with bad configuration fails hard.** Unreachable, unparseable, an unsupported
  version, or a missing required key each render `BootFailure` and mount no route. One `console.error`
  carries the reason and the missing key **names** — never a value.
- **A dev build falls back to `import.meta.env`; a production build must not.** The fallback's key
  tables are eliminated from the production bundle, asserted on the built output by
  `npm run check:bundle`.
- **The container refuses to start** when a required key is unset or empty.

## A key is wired in five places

Adding one means touching all five, and a test compares them:

1. the classification in `types/runtimeConfig.types.ts`, and its `VITE_` name in `lib/env.ts`
2. `apps/portal/.env.example`
3. **its source**, which is one of two things and never both — `.github/config-outputs.json`, the
   one map from Terraform output name to configuration key, for a value Terraform computes; a
   GitHub repository variable for a genuine **input** Terraform is *given*. Today only
   `maxUploadBytes` is an input, through `VITE_MAX_UPLOAD_BYTES`. `environment` is neither: the
   task definition renders it from Terraform's `var.environment`, which no workflow hands over, so
   it is always the default `prod` — Step 3 of `.github/workflows/README.md` says why
4. the ECS task definition — `local.spa_runtime_config` at root, which `modules/spa` renders one
   `CONFIG_<key>` entry per map entry from
5. the container entrypoint's own `KEYS`/`REQUIRED` lists in
   `apps/portal/docker/docker-entrypoint.d/40-render-portal-config.sh` — the leg that actually
   renders the served document, compared against the classification in `lambdas/test_spa_image.py`

It was six until the CloudFront delivery path was retired: `deploy-app.yml` carried a build env
and a render step, each its own site. **The count went DOWN by a deletion, which is the direction
that hides a gap** — so the entrypoint's two lists gained a real comparison in merge 1 of the same spec,
rather than inheriting a claim that a deleted workflow's tests had been covering them.

Site 3 survives the retirement and had to be **edited** by it. The map named `cloudfront_domain`
as the source of `appUrl`; that output is deleted here, and `resolve-config.sh` refuses an output
it cannot resolve — so leaving the entry would have failed `Publish Config` on every run, with the
flag document silently stuck at its last value. It names `spa_origin` now, which is what root's
own `spa_runtime_config` has always given the container.

**Site 3 was "the GitHub repository variable" for every key until the deploy learned to read state.**
That arrangement made a person the transport between `tofu output` and a settings page: a value that
moved in infrastructure stayed wrong in the browser until somebody re-copied it, and an unset
variable interpolated to the empty string, which satisfies a required Terraform variable *and*
overrides its default. `.github/scripts/resolve-config.sh` reads the outputs once per job and fails
the deploy on an absent or empty one, naming the key and the output. What decides which half of site
3 a key belongs to is not convenience: **an input cannot be read from the thing it configures.**
`appUrl` no longer has two halves. `TF_VAR_app_url` is deleted along with `variable "app_url"`, and
Cognito's callback and logout lists are built from `local.spa_origin` directly — so there is nothing
left for a deploy to compare, and nothing left to drift. `.github/config-outputs.json` resolves
`appUrl` from the `spa_origin` output, which is the same local.

`infra/main.tf`'s `spa_runtime_config` states the same relation in Terraform's own terms, and the
two now agree on every value including this one. They diverged on `appUrl` only while a second
delivery path existed: a container serving the other origin sends a sign-in started on the container
to an address that never receives the `?code=`.

## What is deliberately not in it

The API's **verifier** configuration — issuer, audience, JWKS URI, username claim — is server-side
and is not part of the browser's document at all
([`infra/modules/api/README.md`](../../../infra/modules/api/README.md)).

**The exclusion cuts one way only.** The browser's four Cognito values belong to Amplify, they are
legitimately browser-side, and a rule written to forbid "anything that smells of identity" would
delete them and break sign-in — `cognitoUserPoolClientId` survives an exact-match rule and dies under
a substring one. `cognitoDomain` is not a verifier field either: Amplify POSTs the code exchange to
it. The forbidden set is about *the API's trust anchors*, not about the word Cognito.

## The feature-flag document, and why its guards are worth their weight

A feature flag is presentation-only and its browser read falls back to all-on when anything goes
wrong, so **a document nobody can fetch and a healthy environment with every feature enabled look
identical from the app**. Nothing in the SPA can tell them apart, and no user would report it.

`lambdas/test_feature_flags_config.py` therefore holds the validator's own behaviour: a document it
must reject, and a workflow parse that must not go trivial. It also holds the coupling between the
publish workflow's matrix and this document — every declared environment has a flag block and every
block an environment, and each matrix entry names a `bucket_key` that
[`config-outputs.json`](../../../.github/config-outputs.json) can actually resolve. That last check
replaced the workflow's own empty-bucket guard when the destination became a Terraform output: a
`bucket_key` naming nothing resolves to the empty string and targets `s3:///_config/…`, and nothing
else would have caught it.

> **Superseded, and worth stating rather than quietly dropping.** This section used to say the same
> suite asserted the *reachability* of infra the flag spec does not change — CORS, the CSP
> `connect-src` entry, the bucket-policy allowlist and the deploy-role grant. Those assertions were
> removed and the paragraph was not, so it described tests that no longer existed. The deploy-role
> half is asserted again, in `lambdas/test_config_outputs.py`, because this spec's whole claim to
> needing no new IAM rests on it.

If a reachability assertion fails it is a finding to raise, **not** a licence to widen infra.

The flag key set is re-stated in that suite rather than imported from the validator, so a test
cannot pass by agreeing with a mistake it imported. A key is added in eight places — the list is in
[`feature-flags-feature.md`](component-inventory/feature-flags-feature.md) — and that restatement is
the one that fails if the validator was not among them.

**Throwing a switch.** To turn a key off in an environment — `archive` to withdraw archive and
restore, `asyncFileOperations` to stop folder and multi-item file operations, or any area — set it
`false` under that environment's block in `config/feature-flags.json`
(`"environments": {"prod": {"archive": false}}`), merge, and `deploy-config.yml` publishes it. No app
build is involved, and turning it back on is the same edit reversed.

**When it takes effect.** A session that starts after the publish reads the new document at once. A
session already open keeps the copy it last read until that copy is **an hour old** (`STALE_TIME_MS`
in `useFeatureFlags.ts`), and after that re-reads it only when something mounts a flag reader —
moving to another page (a header tab, or a link into another feature), or opening a dialog, drawer
or panel that reads one; opening a folder inside Files is neither — when the network reconnects, or
on a reload. There is no refetch on window focus (`refetchOnWindowFocus: false` in
`lib/queryClient.ts`) and no interval, so a session that sits on one screen and opens nothing keeps
the controls until one of those happens. A dialog already open can still submit, and a session
whose read of the document failed runs all-on and ignores the switch, as above.

**What it does not do.** A flag is presentation, never authorization: the API routes behind a
withdrawn control stay live, and a hand-built request still goes through. An execution already
running finishes and notifies as it would have. It works only on an image that knows the key: a
service pointed back at an image built before the key existed shows the controls whatever the
document says. Stopping a plane itself is an operator action on the infrastructure, not a flag, and
no plane has a documented stop procedure.
