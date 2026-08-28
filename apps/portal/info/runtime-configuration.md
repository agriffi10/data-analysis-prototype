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
3. the GitHub repository variable
4. **both** the build env and the render step in `.github/workflows/deploy-app.yml`
5. the ECS task definition
6. the container entrypoint's own `KEYS`/`REQUIRED` lists in
   `apps/portal/docker/docker-entrypoint.d/40-render-portal-config.sh` — the leg that actually renders
   the served document

## What is deliberately not in it

The API's **verifier** configuration — issuer, audience, JWKS URI, username claim — is server-side
and is not part of the browser's document at all
([`infra/modules/api/README.md`](../../../infra/modules/api/README.md)).

**The exclusion cuts one way only.** The browser's four Cognito values belong to Amplify, they are
legitimately browser-side, and a rule written to forbid "anything that smells of identity" would
delete them and break sign-in — `cognitoUserPoolClientId` survives an exact-match rule and dies under
a substring one. `cognitoDomain` is not a verifier field either: Amplify POSTs the code exchange to
it. The forbidden set is about *the API's trust anchors*, not about the word Cognito.
