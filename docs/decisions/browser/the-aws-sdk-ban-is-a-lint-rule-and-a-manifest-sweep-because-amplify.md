---
type: Decision
title: "The `@aws-sdk/*` ban is a lint rule AND a manifest sweep, because Amplify vendors the SDK (SPEC-202)"
description: "**The `@aws-sdk/*` ban is a lint rule AND a `package.json` sweep.** The rule is declared in **every** clause governing `src/` because flat config REPLACES rather than merges, and the sweep reads the **manifest, never `node_modules`** — a dependency may vendor the SDK, as Amplify did, so a tree assertion fails for what nobody imports and gets deleted. A dependency nobody imports is invisible to an import rule, and that leftover is how the next import arrives. **Narrowed by 257 to one exception:** `src/server/` may import `@aws-sdk/client-dynamodb` and nothing else, by a clause declared LAST so it replaces the `src/**` one; the manifest names exactly that package; and `check:bundle` fails on `DynamoDB_20120810` in any static chunk, because a lint rule reads import paths, not what shipped. **Amplify is gone (262)**: `check:bundle` also fails on `AWSCognitoIdentityProviderService`, and the manifest guard-the-guard is anchored on `next`."
---

Six specs each deleted a browser-side AWS client. What none of them could see is that **a dependency
nobody imports is invisible to every import rule** — the `package.json` entry outlived its last
importer every time, and nothing went red. That leftover is how the next `@aws-sdk` import arrives:
already installed, already resolvable, one autocomplete away. So the fence is two mechanisms, and
each catches what the other cannot.

**The lint rule is declared four times, and that is the hazard.** ESLint flat config **replaces** a
rule's value at the last entry matching a file rather than merging it, so the layering clause, the
exemption clause and the sibling-feature clause each override the `src/**` clause for the files they
match. Written once, the ban is silently off for `src/lib/**`, `src/components/**`, every test in
those trees and four feature directories — while the config reads as though it holds. The guard
therefore **enumerates** every entry governing `src/` that declares `no-restricted-imports` and
requires the group in each, rather than sampling one. And its scoping question is **inverted** on
purpose: an entry is out of scope only if every glob it names is demonstrably not under `src/`,
because an entry with no `files` at all governs everything, and filtering on a `src/` prefix let
exactly that shape declare the rule without the group while an `@aws-sdk` import in `features/`
linted clean. Tests are **in** scope: a test mocking `@aws-sdk/client-s3` is a test of a call the
app no longer makes.

**The sweep reads `package.json`, never `node_modules`.** `aws-amplify` vendored `@aws-sdk/*`
packages transitively, and any dependency may, so an assertion over the installed tree fails for what
nobody imports, is deleted inside a week, and a deleted guard is indistinguishable from a passing one
in CI. It carries a guard-the-guard — the manifest must name `next` (it named `aws-amplify` until
SPEC-262 removed it) — because a parse that read nothing agrees with an empty manifest.

**One exception, on the server only** (rewritten 2026-11-13 for SPEC-257). The portal's Next.js
server keeps its session store in DynamoDB, so `src/server/` may import `@aws-sdk/client-dynamodb`.
Three mechanisms hold the line around it, each catching what the others miss. A clause for
`src/server/**`, declared **last** in the flat config so that it replaces the `src/**` clause for
those files rather than being replaced by it, bans every other `@aws-sdk` package there. The
manifest sweep now requires `@aws-sdk/*` entries to be exactly `@aws-sdk/client-dynamodb`, so a
second client arriving as a dependency fails before anyone imports it. And `npm run check:bundle`
fails naming the chunk when any file under `.next/static/` carries `DynamoDB_20120810`, the target
every DynamoDB request names. The lint rules fence `src/server/` off from the browser's layers by
import path, and `server-only` stops only a module that remembered to import it; the bundle check
reads what actually shipped. Every `.ts` file under
`src/server/` beginning with `import 'server-only'` is itself asserted by a test.

**Amplify left with SPEC-262**, when the browser began signing in through the portal server. A sweep
holds every source and test file under `src/`, and the manifest, free of the package's name, and
`check:bundle` fails naming the chunk when any file under `.next/static/` carries
`AWSCognitoIdentityProviderService`, the protocol target every Cognito user-pool request names. That
marker was measured in a built bundle while Amplify was still in it, so its absence is positive proof.

## History

### 2026-11-15

- **Changed:** SPEC-262 removed Amplify: the manifest guard-the-guard moved to `next`, a sweep keeps
  the package's name out of `src/` and the manifest, and `check:bundle` gained Amplify's Cognito
  marker.

### 2026-11-13

- **Changed:** SPEC-257 admitted `@aws-sdk/client-dynamodb` under `src/server/` only, narrowed the
  manifest sweep to exactly that package, and added the bundle check.

### 2026-09-02

- **Settled:** SPEC-202.
