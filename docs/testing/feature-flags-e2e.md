# Feature flags — live check

Manual verification for SPEC-162's document, publish pipeline and browser read.

**The whole point of this check is that the app cannot tell you the answer.** Every compiled-in
default is `true`, so a permanently-blocked read renders *exactly* like a healthy all-on
environment. "It looks fine" is not a pass. What has to be observed is the **200** on the network
request and the hook reporting **`ready`**.

| What | Where |
|---|---|
| Document (in git) | `config/feature-flags.json` |
| Published to | `s3://{user-space bucket}/_config/feature-flags.json` |
| Publish workflow | `Publish Config` (`.github/workflows/deploy-config.yml`) |
| Build variable | GitHub Actions repo variable `VITE_ENVIRONMENT` = `prod` |
| Portal-role grant | `ReadTheFeatureFlags` — `s3:GetObject` on `{bucket}/_config/*` |

Browser: **Safari** (there is nothing browser-specific here, but the check is a network-panel read,
so use the one you actually sign in with).

---

## SPEC-162 — the document is READ, not merely defaulted

### Step 0 — publish

The workflow runs on merge (`config/**` changed). Confirm it went green:

```bash
gh run list --workflow "Publish Config" --limit 3
```

Then confirm the object is really there, with the right cache header:

```bash
aws s3api head-object --bucket "$(gh variable get VITE_S3_USER_SPACE_BUCKET --json value -q .value)" --key _config/feature-flags.json
```

Expect `"CacheControl": "no-cache"` and `"ContentType": "application/json"`.

> **A laptop `get-object` on this bucket returns `AccessDenied` and that is correct** — the local CLI
> identity is an IAM *user* and is not on the bucket-policy allowlist (only the deploy role and the
> portal role are). `head-object` above runs as whichever identity you have; if it denies, read the
> workflow's own upload step output instead. The browser check below is the authoritative one.

### Step 1 — the browser actually fetched it

1. Sign in to the deployed portal.
2. Open the network panel **before** the app settles, filter on `feature-flags`.

**Expect exactly one request**, and all three of:

- URL host = the user-space bucket's S3 host (the one in `csp_connect_src`)
- Path `/_config/feature-flags.json`
- Status **200**

**Any of these is a FAILURE of this spec, not a curiosity:**

| Observed | What it means |
|---|---|
| **403** | The `ReadTheFeatureFlags` grant or the bucket-policy allowlist is not doing what it should |
| **404** | The publish workflow has never reached this bucket |
| **CSP error in the console** | The bucket host left `csp_connect_src` |
| **CORS error** | The user-space CORS rule changed |
| **No request at all** | The hook is not mounted, or `useAuth` never produced a user |

### Step 2 — the hook says `ready`, not `fallback`

The diagnostic is **dev-only** and stripped from the production bundle, so there are two routes.
Either is sufficient:

- **Against a dev build** (`npm run dev` pointed at the deployed config): the console carries
  `[feature-flags] ready — environment prod`. A line reading `fallback` — and it will say so, with
  `the compiled-in defaults are in force, so a deliberate "off" is NOT applied` — is a failure.
- **Against production**: step 1's 200 plus a non-empty JSON response body *is* the evidence, since
  the only paths from a 200-with-valid-body to `fallback` are a version bump or a corrupt object,
  both visible in the body you are already looking at.

### Step 3 — a flag change is a publish, not a redeploy

**What this step proves, exactly:** the document can be republished and the browser picks the new
body up without an app build. It does **not** prove `VITE_ENVIRONMENT` reached the bundle — see the
note under "What this check discharges".

1. Edit `config/feature-flags.json` → `environments.prod` → `{"dataQuality": false}`. Merge.
2. Wait for `Publish Config` to go green. **Do not redeploy the app** — that is the point.
3. Hard-reload the portal. In the network panel, confirm the response body now carries
   `"dataQuality": false` under `environments.prod`.
4. Nothing user-visible changes yet — SPEC-163 is what hides things. What is being confirmed here is
   that a flag change is one workflow, not a rebuild.
5. **Revert the override** and confirm the next publish restores `{}`.

### Step 4 — `_config/` is not browsable

In the portal's file browser, at your own space root: **`_config` must not appear.** Neither must it
appear as a destination in a move/copy picker.

Both lists name it, but neither is the mechanism — `_config/` is at the **bucket root**, outside
every user prefix, and the portal role's `ListBucket` is prefix-conditioned. So this step is
confirming the IAM condition, not the SPA lists.

---

## What this check discharges

- SPEC-162 FR-009 (the read is real, not a silent fallback) — record the observed status in the
  delivery doc. `ProtectedLayout` mounts `useFeatureFlags()` and discards the result precisely so
  this request exists to be observed; without it the feature is tree-shaken out of the bundle.
- SPEC-162 FR-003 AC2 (the document lands with `no-cache`).
- SPEC-162 FR-003 AC1/AC6 (the publish runs on a `config/**` push and is watched to completion).

**NOT discharged: FR-007's runtime half.** No step here proves `VITE_ENVIRONMENT` reached the
production bundle, and none can. Every step passes identically with the variable unset, because an
unset environment resolves the document's own `defaults` and still reports `ready` — and nothing
reads the resolved set until SPEC-163, so no observable behaviour depends on it either way. The
static half is met (`.env.example`, `deploy-app.yml`, the repo variable set to `prod`). **Settle the
runtime half in SPEC-163's live check**, where a per-environment override that hides a surface is
finally visible: publish `environments.prod = {"query": false}`, confirm the Query tab disappears
without an app redeploy, and revert.
