---
type: Decision
title: "Configuration is a runtime document, and a production build has no fallback (SPEC-192)"
description: "**Configuration is a RUNTIME document** (`/config.json`, `no-store`, refused whole on version) with **no production fallback**. Its key set is wired in five places, asserted across all, and the container **refuses to start** on a required one unset or empty. **The deploy READS the values from Terraform state**, one `tofu output -json` through `.github/config-outputs.json`, refusing an absent *or empty* output by name; only a genuine **input** is still a repository variable, because an input cannot be read from the thing it configures — so retiring an origin means **re-pointing that map**, not just deleting the output. The API's **verifier** config is server-side, never in the browser's document — and the exclusion cuts one way: a rule forbidding \"anything identity-shaped\" takes Amplify's own Cognito keys with it."
---

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

> **Superseded in part by SPEC-194 and SPEC-202 (marked 2026-09-14):** the distribution is gone, and
> nginx answers `/config.json` with the rendered document or a 404, never the shell, so a missing
> document reads as `unreachable` in the loader. The rule stands for any 2xx body that does not
> parse, and its fixture is now a markup string, not the real `index.html`. What production can
> still produce, and the check still owed, are recorded in the runtime-config boot-failure row of
> `docs/testing/owed.md`.

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

> **Superseded in part by SPEC-194 and SPEC-202 (marked 2026-09-14):** the CloudFront behaviours
> above went with the distribution. `no-store` is now nginx's own header on `location = /config.json`,
> and the SPA image's behaviour matrix reads it off a response.

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

`/config.json` is refused whole on version. Its key set is wired in five places, asserted across all, and the container refuses to start on a required one unset or empty. Retiring an origin means re-pointing the `.github/config-outputs.json` map, not just deleting the output. The API's verifier config is server-side, never in the browser's document, and the exclusion cuts one way: a rule forbidding "anything identity-shaped" takes Amplify's own Cognito keys with it.

## History

### 2026-09-14

- **Changed:** Marked for SPEC-194 and SPEC-202: nginx answers `/config.json` with the document or a 404, so a missing document reads as `unreachable`, not `unparseable`.
- **Changed:** Marked for SPEC-194 and SPEC-202: the CloudFront behaviours went with the distribution, and `no-store` is now nginx's own header on `location = /config.json`.

### 2026-09-01

- **Changed:** SPEC-215 replaced the repository-variable wiring site with `.github/config-outputs.json`; only a genuine input is still a variable.

### 2026-08-24

- **Settled:** SPEC-192.
