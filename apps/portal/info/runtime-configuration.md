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
- **`Cache-Control: no-store`, and the distribution enforces it independently.** A document answered
  from a cache populated in the previous environment renders a working, fully functional portal
  pointed at the wrong account, and nothing on screen distinguishes it. The upload sets the header and
  `/config.json` has its own `Managed-CachingDisabled` behaviour — with the response-headers policy
  re-attached, because it is per-behaviour and not inherited
  ([`infra/modules/app/README.md`](../../../infra/modules/app/README.md)).
- **A production boot with bad configuration fails hard.** Unreachable, unparseable, an unsupported
  version, or a missing required key each render `BootFailure` and mount no route. One `console.error`
  carries the reason and the missing key **names** — never a value.
- **A dev build falls back to `import.meta.env`; a production build must not.** The fallback's key
  tables are eliminated from the production bundle, asserted on the built output by
  `npm run check:bundle`.
- **The container refuses to start** when a required key is unset or empty.

## A key is wired in six places

Adding one means touching all six, and a test compares them:

1. the classification in `types/runtimeConfig.types.ts`, and its `VITE_` name in `lib/env.ts`
2. `apps/portal/.env.example`
3. **its source**, which is one of two things and never both — `.github/config-outputs.json`, the
   one map from Terraform output name to configuration key, for a value Terraform computes; a
   GitHub repository variable for a genuine **input** Terraform is *given*. Today only
   `environment` and `maxUploadBytes` are inputs
4. **both** the build env and the render step in `.github/workflows/deploy-app.yml`
5. the ECS task definition
6. the container entrypoint's own `KEYS`/`REQUIRED` lists in
   `apps/portal/docker/docker-entrypoint.d/40-render-portal-config.sh` — the leg that actually renders
   the served document

**Site 3 was "the GitHub repository variable" for every key until the deploy learned to read state.**
That arrangement made a person the transport between `tofu output` and a settings page: a value that
moved in infrastructure stayed wrong in the browser until somebody re-copied it, and an unset
variable interpolated to the empty string, which satisfies a required Terraform variable *and*
overrides its default. `.github/scripts/resolve-config.sh` reads the outputs once per job and fails
the deploy on an absent or empty one, naming the key and the output. What decides which half of site
3 a key belongs to is not convenience: **an input cannot be read from the thing it configures.**
`appUrl` shows both halves at once — the document resolves it from an output, while `TF_VAR_app_url`
stays a variable because Cognito's callback list is built *from* it, and `deploy-app.yml` compares
the two rather than letting them drift into a broken sign-in.

`infra/main.tf`'s `spa_runtime_config` is the same relation stated for the container path, in
Terraform's own terms. The two agree key for key, and diverge on exactly one value on purpose:
`appUrl` is the CloudFront origin for the bundle and `local.spa_origin` for the container, because a
container serving the CloudFront origin sends a sign-in started on the container to an address that
never receives the `?code=`.

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
cannot pass by agreeing with a mistake it imported. A key is added in six places, and that
restatement is the one that fails if the validator was not among them.
