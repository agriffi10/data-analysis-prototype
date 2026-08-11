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

**FR-007's runtime half is discharged by the SPEC-163 pass below**, not by anything above. No step
in the 162 pass proves `VITE_ENVIRONMENT` reached the production bundle, and none can: every one of
them passes identically with the variable unset, because an unset environment resolves the
document's own `defaults` and still reports `ready`. Only an override that visibly HIDES something
settles it.

---

## SPEC-163 — a flag actually hides things

Browser: **Safari**. Do this in one sitting; step 4 restores the environment.

### Step 1 — publish two features off

Edit `config/feature-flags.json` → `environments.prod` to `{"query": false, "dataQuality": false}`.
Merge, and wait for **Publish Config** to go green. **Do not redeploy the app** — that is the point.

### Step 2 — desktop

Hard-reload the portal, signed in. Confirm all of:

| Where | Expect |
|---|---|
| Topbar | **Files** and **Connections** only. No Query tab, no Data quality tab — *absent*, not greyed out |
| `/query` typed into the address bar | The **"Query isn't available"** page, with a working **Go to Files** link — **not** "Page not found" |
| `/data-quality` | Same, naming Data quality |
| Files, in a folder | **No "Create table" button** on the toolbar |
| Files, with one item selected | **No "Check quality"** in the selection toolbar |
| `/help` | Neither the **Query** nor the **Tables** section in the rail; open **Files** and confirm **"Check data quality"** and **"Find a past quality check"** are gone from its guides while **"Upload files"** remains |

### Step 3 — 400px

Narrow the window to 400px (or use the responsive design mode) and reload. Open the **hamburger**:

- The drawer lists **Files**, **Connections**, **Notifications**, **Help** — and *not* Query or
  Data quality. A tab hidden in the topbar and present here is the feature still being one tap
  away, which is the whole reason both take the same predicate.
- The reduced nav still lays out correctly — no gap where a tab was, no wrapped row.

### Step 4 — flip them back on, and watch it happen without a deploy

Set `environments.prod` back to `{}`, merge, wait for **Publish Config**, hard-reload.

Everything in steps 2 and 3 returns. **Confirm no Deploy App run was involved** — `gh run list
--limit 5` should show `Publish Config` and no `Deploy App`.

**This step is what discharges SPEC-162 FR-007's runtime half**: an override took effect, so
`VITE_ENVIRONMENT` demonstrably reached the bundle and resolved the `prod` block. If the tabs had
stayed put in step 2, the variable is unset in the build — check the repo variable and
`deploy-app.yml`.
