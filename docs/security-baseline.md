# Security Scanning — Baseline

**Taken:** 2026-08-02, on the SPEC-138 branch, at `4a6fee8`.
**Status:** the 2026-08-02 snapshot, plus every disposition taken since. It was written as the
input to the spec that turns the gates on, and that spec landed *inside* it as the addenda below —
so this is now the standing disposition register for the scanner suite, not a frozen document.
`docs/process.md` already calls it one. Counts in Coverage carry their own dates; the npm table is
append-only.

Every scanner in `.github/workflows/security.yml` ships as `gate: report` — it runs, publishes,
and concludes green. This document is the reason that is a step rather than an omission: it records
what the first full run actually found, and what should happen to each finding.

Counts below were produced by running the pinned scanner versions locally against `4a6fee8`. The
CI run reproduces them.

---

## Coverage

| Surface | Scanner | Result |
|---|---|---|
| SPA + Lambdas | Semgrep `p/owasp-top-ten` + language rulesets | 1 finding, 5 partial parses |
| SPA | `eslint-plugin-security`, `no-unsanitized` (**blocking**) | clean — 10 pre-existing violations resolved in SPEC-138 |
| Lambdas | ruff `S` (bandit) — pre-existing, **blocking** | clean |
| SPA deps | `npm audit --omit=dev` (runtime) | 4 → **2** (2026-08-05, `react-router` pair cleared) |
| SPA deps | `npm audit` (full) | 6 → **4** (2026-08-03, `postcss` + `brace-expansion` cleared) → **2** (2026-08-05, `react-router`; see below) |
| Lambda deps | `pip-audit`, 13 packages | 0 |
| Repo | `gitleaks`, 357 commits / 9.5 MB | **0** |
| `infra/` | `checkov`, 224 resources | 305 failed / 439 passed / 0 parse errors |
| Deployed portal | OWASP ZAP baseline | **2026-08-03** — 20 alerts (2 Medium, 8 Low) → **13 after SPEC-140** (1 Medium, 2 Low, 10 Informational); 0 fail throughout |

## Coverage gaps — these are not findings, they are things nothing here checks

1. ~~**The IAM policies are unscanned.**~~ **CLOSED by SPEC-139** — `deploy-infra.yml` now scans
   the rendered `tofu show -json` plan, where the policies are real documents rather than
   `templatefile()` calls. 55 IAM resources, 431 IAM checks evaluated (previously zero). See the
   plan-scan section below. **Residual limitation:** the plan scan runs only on PRs touching
   `infra/**` or that workflow, so it is not part of the weekly sweep — correct, since IAM cannot
   change without an `infra/**` change and Checkov is version-pinned.
2. **ZAP is unauthenticated.** It reaches the pre-login shell and the CloudFront response headers.
   Nothing behind Cognito is exercised, so no ZAP result is evidence about the authenticated app.
3. **No GitHub code scanning.** The repo is private on a personal account, so CodeQL, SARIF upload
   and the Security tab are unavailable. There is no cross-run deduplication and no
   new-vs-existing diffing; each run is a fresh snapshot.
4. **Semgrep partial parses.** Five test files parse only partially on the `vi.fn<...>()`
   explicit-type-argument syntax, so regions of them were not scanned. Reported per-run.

---

## Findings

### Dependencies — npm (6 vulnerable packages at the snapshot, 4 reaching the browser; **2 and 2 today**)

The runtime/build split is the whole point of auditing at two scopes.

**Two numbers are in play here and they are easy to read as one.** Every count outside the table —
the heading, the Coverage rows, and the number `apply-gate.sh` is fed — is
`.metadata.vulnerabilities.total`, which counts vulnerable **packages**. The table is one row per
**advisory**, so it has always been the longer of the two. The `undici` note below is the clearest
check on this: five advisories arrived and moved the audit by exactly one, because they landed on
one package. A date in the Disposition column is when an advisory was **dealt with**, never when it
was published.

| Sev | Package | Scope | Advisory | Disposition |
|---|---|---|---|---|
| high | `react-router` | **runtime** | GHSA-chx6-hx7r-mcp5 — DoS via inefficient route matching | **FIXED** (7.18.2) |
| high | `react-router` | runtime | GHSA-qwww-vcr4-c8h2 — RSC-mode CSRF bypass | **FIXED** (8.3.0, 2026-08-05) — was `accept`; the v8 bump made accepting it unnecessary |
| medium | `react-router` | runtime | GHSA-337j-9hxr-rhxg — SSR hydration constructor injection | **FIXED** (7.18.2) |
| medium | `react-router` | runtime | GHSA-h8fp-f39c-q6mh — RSCErrorHandler XSS | **FIXED** (7.18.2) |
| medium | `react-router` | **runtime** | GHSA-wrjc-x8rr-h8h6 — open redirect via backslash in `<Link>`/`useNavigate` | **FIXED** (7.18.2) |
| medium | `dompurify` | runtime (via monaco) | GHSA-cmwh-pvxp-8882 — `ALLOWED_ATTR` pollution via `setConfig()` | **defer** |
| medium | `dompurify` | runtime (via monaco) | GHSA-55q2-fjhq-7xh7 — `IN_PLACE` hook removal leaves a detached subtree executable | **defer** |
| low | `dompurify` | runtime (via monaco) | GHSA-c2j3-45gr-mqc4 — `CUSTOM_ELEMENT_HANDLING` bypasses `afterSanitizeElements` | **defer** |
| low | `dompurify` | runtime (via monaco) | GHSA-vxr8-fq34-vvx9 — Trusted Types policy survives `clearConfig()` | **defer** |
| high | `postcss` | build | GHSA-r28c-9q8g-f849 — path traversal via `sourceMappingURL` | ~~fix~~ **DONE 2026-08-03** — 8.5.15 → 8.5.25 |
| high | `nanoid` | build | GHSA-2v37-7h3g-55p8 — custom generators loop indefinitely when `size` is zero | ~~fix~~ **DONE 2026-08-30** — 3.3.17 → 3.3.18 |
| high | `brace-expansion` | build | GHSA-mh99-v99m-4gvg — OOM via unbounded expansion | ~~fix~~ **DONE 2026-08-03** — 5.0.7 → 5.0.9 |

Notes that change the priority order:

- **The open-redirect vector is already closed at the app level.** GHSA-wrjc-x8rr-h8h6 is the
  backslash-in-path bypass. The only place external data reaches navigation in this app is a
  notification's `link`, and `notificationLink.ts` (SPEC-061) already rejects both `//` and `/\`
  explicitly, degrading to plain text. Every other `navigate()` call uses a literal prefix with
  `encodeURIComponent` on the variable part, so no external value can control the leading
  characters. The bump is still worth doing — a defence that depends on one function staying
  correct is thinner than one that also has a patched router — but this is not an open hole.
- **Four of the five `react-router` advisories do not apply**: they are RSC- and SSR-mode issues,
  and this is a client-only SPA. `react-router` and `react-router-dom` have a non-breaking fix
  available, so the bump is cheap regardless.

  **All five are cleared as of 2026-08-05 (v8.3.0).** The fifth — the RSC-mode CSRF bypass this
  file had dispositioned `accept` — needed a v8 major, and the v8 major turned out to be a
  **package rename and nothing else**: `react-router-dom` is removed, everything imports from
  `react-router`, and `RouterProvider`/`HydratedRouter` (which this app does not use — it is
  declarative-mode `BrowserRouter`) move to `react-router/dom`. Every component and hook this app
  uses is unchanged, so the diff was one import specifier across 40 files. The other v8 baselines
  were already met: Node 22.22+ (`.nvmrc` is 24), React 19.2.7+ (declared range raised from
  `^19.2.6`, which permitted an install that violated the new peer), Vite 7+ (on 8). **The
  `accept` disposition was correct when written and became obsolete, not wrong — worth
  re-testing an accepted advisory whenever its "needs a major" premise changes.**
- **`dompurify` is transitive through `monaco-editor`, and the npm package the alerts name is not
  the code that ships.** Monaco *vendors* DOMPurify: `esm/vs/base/browser/domSanitize.js` imports
  `./dompurify/dompurify.js`, a checked-in copy reporting `version = '3.4.8'`. Nothing in monaco's
  ESM tree imports the bare `dompurify` specifier, our own source never imports it, and the lockfile
  shows monaco as its only dependent — so npm installs the package, Dependabot alerts on it, and no
  bundle ever loads it. The vulnerable version does reach the browser; it reaches it through the
  vendored copy.

  **Reading the bundle cannot settle this, which is worth knowing before you try.** The vendored
  file is byte-identical to the npm package's `dist/purify.es.mjs` but for a trailing
  `sourceMappingURL` comment, so the two minify to the same output and no version or content string
  distinguishes them. What settles it is planting a marker: change the vendored file's `version`,
  rebuild, and the marker appears in `dist/`; do the same to all four npm entry points and nothing
  appears.

  **That is what makes the `overrides` route worse than blocked — it is a false fix.** Forcing the
  npm package to 3.4.13 would clear all four alerts and change nothing that ships, because the
  import is a relative path. Anyone tempted to take the mass dependency refresh described below as a
  security measure would get a green audit and byte-identical output — verified by resolving with the
  override applied and rebuilding.

  Monaco moving is the only thing that fixes this *through dependency resolution*. There is one
  alternative: overwrite the vendored file in a `postinstall` patch, which works precisely because
  3.4.13's ESM build is interface-identical to the copy it replaces. That forks a vendored
  dependency and has to be re-verified on every monaco bump, so it is not the recommendation — but
  it exists, and a reader weighing the risk should know the choice is not binary.

  Deferred, and the reachability holds for all four: three concern the `setConfig`/`clearConfig`
  and `CUSTOM_ELEMENT_HANDLING` configuration APIs, which the portal never calls; the fourth
  (`GHSA-55q2`, `IN_PLACE`) needs `IN_PLACE: true`, and no monaco caller can set it: `doSanitizeHtml`
  builds its config by spreading monaco's own defaults and then assigns only `ALLOWED_TAGS` and
  `ALLOWED_ATTR`, while the caller's config is monaco's typed shape and is never spread into the
  DOMPurify options. That structure is the argument, not the fact that the token is absent — a call
  site spreading a caller-supplied config would set `IN_PLACE` without the word ever appearing.
  Monaco is also lazy-loaded on the Query route only (SPEC-035). Revisit when monaco ships a forward
  fix.

  **npm's own proposed fix is worse than a downgrade.** `monaco-editor@0.53.0` declares no
  `dompurify` dependency at all (`{"@types/trusted-types": "^1.0.6"}` is the whole list) and vendors
  DOMPurify **3.1.7**. That is precisely why npm offers it: the copy is invisible to the audit.
  Taking it would ship an older DOMPurify to the browser and read clean.

  **Re-examined 2026-08-05, still deferred — and now with the reason the `overrides` route is
  closed.** `monaco-editor@0.56.0` (still the latest release; everything published after it is a
  `-dev-` prerelease) pins `dompurify: '3.4.8'` **exactly**, so Dependabot has no in-range update to
  open a PR with — which is why four alerts sit open with no PR rather than being ignored.
  `dompurify` 3.4.13 clears all four **alerts** — not the shipped code, per above — but **npm will
  not apply a newly-added `overrides` entry
  against an existing lockfile**: `npm install`, `npm install --package-lock-only`, `npm update`
  and a clean-room re-resolve seeded with the committed lock were all verified to leave 3.4.8 in
  place. Only a **from-scratch** resolution (no lockfile) honours the override — and that
  re-resolves every caret range at once, measured at **134 package version changes**, the whole AWS
  SDK and Amplify surface included. That is an unrelated mass dependency bump riding along with
  four advisories in code paths the app never calls, so it is not worth taking as a security fix.
  It also explains this file's earlier note that an `overrides` block "silently did nothing" —
  npm's behaviour, not a malformed entry. **Do the refresh on its own merits if ever; it is not a
  security fix, and monaco moving is the only thing that is.**
- **`postcss` and `brace-expansion` are build-time.** Both exploits need untrusted input — a
  hostile stylesheet, a hostile glob — and both inputs are this repo's own source. Real supply-chain
  hygiene, no runtime exposure. Both have non-breaking fixes, so they are cheap to clear.

  **Cleared 2026-08-03, and the mechanism is worth recording.** Neither needed a `package.json`
  edit or an `overrides` block: `apps/portal` already declared `vite ^8.0.12` and `eslint ^10.3.0`,
  caret ranges that *already permitted* the fixed transitives (vite 8.2.0 requires `postcss ^8.5.23`;
  minimatch 10.2.6 requires `brace-expansion ^5.0.8`, resolving 5.0.9). The lockfile was simply
  pinned to stale resolutions, so `npm update` inside the existing ranges was the whole fix —
  lockfile-only, no manifest change. **An `overrides` block was tried first and silently did
  nothing**, including for a deliberately invalid version string, so npm never re-resolved; reach
  for `npm update` before `overrides` when the declared range already allows the fix. npm audit
  6 → 4; the two remaining highs were the `react-router` pair, both cleared by v8.3.0 on 2026-08-05.
- **`undici` — appeared and was cleared the same day (2026-08-04, #341).** GHSA-4cwx-7wf7-3272
  (HIGH, Cache-Control `private` parsing → cross-user disclosure in a shared cache) plus four
  mediums, published after the snapshot above and taking full audit 4 → 5 for part of one day.
  Dev-only and transitive: `jsdom` (the vitest DOM environment) is the sole consumer, and a build
  of `apps/portal/dist/` contains no `undici`. Dependabot's 7.28.0 → 7.29.0 bump cleared it.
  **Full and runtime read the same number** — every remaining advisory is in a runtime dependency,
  so `--omit=dev` no longer subtracts anything. (That was 4 when written; the Coverage rows carry
  the current values.)

- **`nanoid` — build-time, and the recorded mechanism worked unchanged (2026-08-30).**
  GHSA-2v37-7h3g-55p8 is HIGH, and the severity is doing no work here. The advisory is specific:
  `customAlphabet` and `customRandom` spin forever when handed `size: 0`. `nanoid` resolves
  `dev: true` through vite's postcss, whose sole call site is
  `input.js:80` — `nanoid(6)` from `nanoid/non-secure`, a hard-coded literal into the plain
  generator. **It calls neither affected function**, so no version of this advisory was reachable;
  the bump is hygiene, not remediation.
  `postcss@8.5.25` declares `nanoid ^3.3.16`, so the patched 3.3.18 was already in range and
  `npm update nanoid` was the whole fix — a three-line, lockfile-only diff with no manifest edit,
  exactly as for `postcss` and `brace-expansion` above.

  **A grep afterwards looks like the fix did not land, twice over, so record why it did.** 3.3.18's
  only functional change is a `size <= 0` guard in `async/index.native.js`; `non-secure/index.js` is
  **byte-identical** across the bump and `index.js`'s `customRandom` already carried its guard in
  3.3.17, so the file postcss imports was never the vulnerable one. And `customAlphabet` survives in
  the tree regardless, inlined in the postcss that `prettier@3.8.5` vendors into both
  `plugins/postcss.js` and `plugins/postcss.mjs` — dev-only, no lockfile entry pointing at either,
  never alerted on, and the `size` never ours to pass.

### Dependencies — Python

**0 vulnerabilities across 13 packages.** Nothing owed.

### Secrets

**0 findings across all 357 commits.** No allowlist file was needed, so none was committed.

### SAST — Semgrep

| Sev | Rule | Location | Disposition |
|---|---|---|---|
| warning | `python.flask.security.audit.directly-returned-format-string.directly-returned-format-string` | `lambdas/table-share-common/tscommon/copy_plan.py:84` | **accept** — false positive |

The rule is a Flask template-injection check about returning a format string as an HTTP response.
There is no Flask and no HTTP response in this fleet; `p/owasp-top-ten` pulls the Flask rules in as
part of its Python set. If a second Flask false positive appears, exclude that rule rather than
narrowing the ruleset.

The SPA is clean under Semgrep.

### SAST — ESLint (blocking, resolved in SPEC-138)

Ten pre-existing violations, all resolved rather than carried into this baseline, because this
scanner blocks:

- **8 × `security/detect-non-literal-regexp`**, all in test files building a Testing Library matcher
  from an in-repo constant or from the test's own escaped fixture. No untrusted value reaches
  `RegExp`. Rule disabled for the test glob with the reason recorded.
- **2 × `security/detect-unsafe-regex`** in `query.sql.ts`, on regexes that parse user-typed SQL —
  the right place to be suspicious. `safe-regex` flags star height, not measured backtracking. Both
  were measured: 200k characters of pathological input match in under 0.3 ms, linear, because each
  optional group is anchored by a literal and the adjacent character classes are disjoint. Accepted
  with the measurement recorded at the disable.

### IaC — Checkov (305 failures / 25 rules)

Grouped by rule; the count is the number of resources.

| N | Check | Rule | Disposition |
|---|---|---|---|
| 36 | CKV_AWS_338 | Log group retention ≥ 1 year | **accept** — CloudWatch is the operational tail. The durable narrative store is `logs/` in S3, retained forever (SPEC-129). Paying to duplicate it in CloudWatch buys nothing. |
| 36 | CKV_AWS_158 | Log group encrypted by KMS | **defer** — encrypted at rest under the AWS-managed key today; a CMK is a cost and key-management decision. |
| 32 | CKV_AWS_117 | Lambda inside a VPC | **accept — and the reason CHANGED on 2026-08-26, when a VPC arrived.** It used to read "there are no VPC resources". There are now, and the API function is deliberately outside them: attaching it would need an interface endpoint per service it later calls, would put ENI attachment on the cold-start path, and — after the arc's provider swap — would leave a token-verification host with no AWS endpoint at all unreachable, with no code change to blame. The control-plane functions talk to AWS APIs only; a VPC would add cost and no isolation. |
| 32 | CKV_AWS_116 | Lambda dead-letter queue | **accept — wrong shape.** The check looks for the Lambda's own `dead_letter_config`, which covers async invoke. This fleet is SQS/Step-Functions driven and *does* have per-request DLQs with a drain (SPEC-126). |
| 32 | CKV_AWS_50 | Lambda X-Ray tracing | **accept** — SPEC-127→137 built structured logging as the observability answer, deliberately. X-Ray would be a second parallel system. |
| 32 | CKV_AWS_173 | Lambda env var encryption (CMK) | **defer** — env vars hold queue URLs and bucket names, not secrets. |
| 32 | CKV_AWS_115 | Lambda reserved concurrency | **defer** — genuinely worth considering for SQS-fronted control planes. Follow-up. |
| 32 | CKV_AWS_272 | Lambda code signing | **defer** — needs a signing profile and a deploy-pipeline change. |
| 5 | CKV_AWS_21 | S3 versioning | **DEFERRED (2026-08-03, user decision)** — pre-production, no real user data, so the exposure is theoretical today. The reasoning stands and does not expire: S3 has no atomic move, so rename/move is `CopyObject` + `DeleteObject` (architecture.md → *Constraints that shape the system*), and without versioning a failure between those two steps is **unrecoverable user data loss**. **Revisit before any real data lands.** |
| 5 | CKV_AWS_144 | Cross-region replication | **accept** — single-region system by design. |
| 5 | CKV_AWS_145 | S3 KMS CMK | **defer** — SSE-S3 today. |
| 5 | CKV_AWS_18 | S3 access logging | **defer** — cost vs. value; `logs/` already narrates control-plane activity. |
| 5 | CKV2_AWS_62 | S3 event notifications | **accept** — not applicable; the control planes are queue-driven. |
| 4 | CKV_AWS_284 | Step Functions X-Ray | **accept** — same reasoning as CKV_AWS_50. |
| 2 | CKV_AWS_300 | Abort incomplete multipart uploads | ~~**FIX**~~ **FIXED 2026-08-05.** Rules added to the artifacts and static buckets, and bucket-wide on the admin bucket. The admin one needed the `admin_lifecycle_rules_are_prefix_scoped` check narrowed to rules that actually EXPIRE something — an abort-MPU rule carries no expiration and so cannot reach `logs/`, which the guard exists to protect. The user-space and shared-space buckets already had the rule. |
| 1 | CKV2_AWS_32 | CloudFront response headers policy | ~~**FIX**~~ **CLEARED by SPEC-140** — was the CSP / HSTS / `X-Frame-Options` gap, and the one finding ZAP reported independently. Two scanners, one cause. |
| 1 | CKV_AWS_259 | Response header policy enforces HSTS | ~~accept~~ **FIXED 2026-08-03** — `preload` flipped to `true`, check passes. It is inert without a manual hstspreload.org submission, which we have not made; **do not submit this `*.cloudfront.net` domain**, since preload is near-irreversible and a custom domain will replace it. Original reasoning for declining, retained: **accept — introduced by SPEC-140, deliberately.** The check fails on **`preload` alone**; max-age, `include_subdomains` and `override` all satisfy it (verified against checkov 3.3.9, whose check returns FAILED at the `preload` branch and PASSED with it flipped). `preload` declares intent to be submitted to hstspreload.org — we are not submitting, the domain is a shared-suffix `*.cloudfront.net` that a custom domain will replace (see CKV2_AWS_42), and preload is near-irreversible once granted. Revisit with the custom domain. **Note the arithmetic:** this appearing and CKV2_AWS_32 clearing cancelled out, leaving the total at 305 — the total is not a useful signal across this change. |
| 1 | CKV_AWS_82 | Athena workgroup enforces configuration | ~~**FIX**~~ **ACCEPT — this disposition was WRONG (corrected 2026-08-05).** "It stops a client overriding the result location" describes the isolation MECHANISM, not a weakness: Athena has no per-user result location, so the app sets `s3://<user-space>/{username}/athenaresults/` on every `StartQueryExecution` and IAM confines each caller to its own prefix (SPEC-032 FR-006). Enforcing workgroup configuration would force every query to the workgroup default — the admin-only bucket — breaking per-user results and query history for every user. `analytics/athena.tf` already carries a comment predicting exactly this fix being attempted. Revisit only if Athena gains a per-user output location. |
| 1 | CKV_AWS_68 | CloudFront WAF | **defer** — real cost, and this is a pre-production system. |
| 1 | CKV2_AWS_47 | WAF managed rules for Log4Shell | **accept** — follows from CKV_AWS_68; also no Java anywhere. |
| 1 | CKV_AWS_86 | CloudFront access logging | **defer** |
| 1 | CKV_AWS_174 | Viewer certificate TLS ≥ 1.2 | **accept** — the default CloudFront certificate already enforces this; the check fires because no custom cert is configured. |
| 1 | CKV2_AWS_42 | Custom SSL certificate | **accept** — no custom domain yet. |
| 1 | CKV_AWS_310 | Origin failover | **accept** — single S3 origin by design. |
| 1 | CKV_AWS_374 | Geo restriction | **accept** — no geographic access policy. |
| 1 | CKV2_AWS_61 | S3 lifecycle configuration | **defer** — subsumed by the CKV_AWS_300 work. |

~~**Five fixes fall out of this:** S3 versioning, the multipart-abort lifecycle rule, the CloudFront
response-headers policy, the Athena workgroup enforcement, and the two cheap npm bumps.~~

**As resolved (2026-08-05):** the CloudFront response-headers policy shipped with SPEC-140, both npm
bumps landed, the multipart-abort rules are in, and **S3 versioning remains deferred by decision**
(pre-production, no real user data — revisit before any real data lands). **The Athena workgroup
enforcement was NOT a fix and has been re-dispositioned as accepted** — see the row above. Four of
five, and the fifth was the one that would have broken per-user query results.

### DAST — OWASP ZAP baseline (first live run, 2026-08-03)

**Run:** [30819001441](https://github.com/agriffi10/data-analysis-prototype/actions/runs/30819001441),
`workflow_dispatch` on `main` at `ea3ddc4`, target `https://d1kbh4bnvh1je8.cloudfront.net`.
`FAIL-NEW: 0  WARN-NEW: 15  PASS: 55` — 20 alerts in the JSON report.

The scheduled run earlier the same day produced identical findings but concluded `failure` for a
workflow reason with no security content: `cmd_options` passed a second `-J`, which redirected the
JSON output away from the filename `zaproxy/action-baseline` reads back, and that read failure is
`core.setFailed` *outside* the `fail_action` guard. Fixed in #327. **Recorded because it is the
failure mode this file warns about generally — a scanner that "did not run" must never read as
clean, and here a scanner that *did* run read as broken.**

| Risk | Alert | Instances | Disposition |
|---|---|---|---|
| **Medium** | Content Security Policy (CSP) Header Not Set | 3 | **FIX** — SPEC-140 |
| **Medium** | Missing Anti-clickjacking Header | 3 | **FIX** — SPEC-140 |
| Low | Strict-Transport-Security Header Not Set | 5 | **FIX** — SPEC-140 |
| Low | Server Leaks Version Information (`server: AmazonS3`) | 5 | **FIX** — SPEC-140, header removal |
| Low | X-Content-Type-Options Header Missing | 5 | **FIX** — SPEC-140 |
| Low | Permissions Policy Header Not Set | 5 | **FIX** — SPEC-140 |
| Low | Cross-Origin-Resource-Policy Missing or Invalid | 3 | **FIX** — SPEC-140 |
| Low | Cross-Origin-Opener-Policy Missing or Invalid | 3 | **FIX** — SPEC-140 |
| Low | Cross-Origin-Embedder-Policy Missing or Invalid | 3 | **accept** — `require-corp` buys cross-origin isolation this app has no use for (no `SharedArrayBuffer`, no high-resolution timers) and risks breaking subresource loads for it. Reasoned in SPEC-140. |
| Low | Timestamp Disclosure — Unix | 5 | **accept** — digit sequences inside the minified bundle matched as timestamps. Not a header, and not real. |
| Info | Storable and Cacheable Content · Retrieved from Cache · Re-examine Cache-control Directives | 8 | **defer** — the SPA shell is served with **no** `Cache-Control` at all under `Managed-CachingOptimized` (24h default TTL), so a deploy can be shadowed by a stale `index.html`. That is a correctness bug, not header hygiene, and it needs a second cache behavior splitting `/assets/*` (hashed, immutable) from `index.html` (no-cache). Explicitly **out of scope** for SPEC-140. |
| Info | Base64 Disclosure · Suspicious Comments | 10 | **accept** — inside the minified vendor bundle. |
| Info | Modern Web Application | 3 | **accept** — informational by design; fires on any SPA. |
| Info | Sec-Fetch-{Dest,Mode,Site,User} Header Missing | 12 | **accept — not a server finding.** These are *request* headers; the alert fires because ZAP's spider does not send them. Nothing on the origin can fix it. |

**Two scanners, one cause:** every Medium and six of the eight Lows were the CKV2_AWS_32 gap above.
SPEC-140 closed both rows at once. **A green ZAP run will never be zero-alert** — the Informational
rows stay, and three findings survive by decision.

### Post-SPEC-193 — the container platform (2026-08-26, checkov 3.3.9)

**The counts, measured rather than estimated.** The `.tf` scan over `infra/` reports **918 passed /
736 failed**, 474 resources, against 508/373 when this file was written. The enforce list went from
**52 IDs to 89**: 37 newly-passing IDs joined it, **none disappeared then**, and the gate script itself
reports `enforcing 79 check ID(s); 0 finding(s) on them`. It was 89 until the Identity Pool and then CloudFront were retired — the entries above record why, as this file is where an enforce-list removal has to be argued.

**Thirty-five of the 37 came with the new families. Two did not**, and the exception is the useful
part: `CKV_AWS_251` and `CKV_AWS_36` both evaluate
`module.verification.aws_cloudtrail.archive_audit`, which landed with the archive vault's audit
trail on 2026-08-14 — five days after the 52-ID baseline was measured. They have been passing, and
unenforced, ever since. **The list should be regenerated by any spec that adds a resource family,
not only by one that adds six**; two IDs sat outside the gate for twelve days because nothing did.

The other 35 are what the new VPC, ECS, ECR, ALB, ACM and API Gateway resources brought — among
them the ones the spec named as fixes rather than dispositions: ECR immutability and scan-on-push
(`CKV_AWS_51`, `CKV_AWS_163`), the ALB's TLS policy, dropped invalid headers, deletion protection
and access logging (`CKV_AWS_103`, `CKV_AWS_131`, `CKV_AWS_150`, `CKV_AWS_91`), the HTTP→HTTPS
redirect (`CKV2_AWS_20`), the read-only root filesystem (`CKV_AWS_336`), distinct task and execution
roles (`CKV_AWS_249`), no automatic public IP (`CKV_AWS_333`, `CKV_AWS_130`), the default security
group restricting all traffic (`CKV2_AWS_12`), VPC flow logging (`CKV2_AWS_11`) and Container
Insights (`CKV_AWS_65`).

**Every newly-enforced ID has a non-zero `passed_checks` count** — that is what the regeneration
recipe selects on, and it is the difference between "this check passed" and "this check never ran".
`--quiet` strips `passed_checks` and must never come back.

**The rendered-plan IAM scan added nothing, measured on the real run.** The `plan` job on the PR
that adds `modules/spa` reported `IAM resources in plan: 92; IAM checks evaluated: 716; IAM
findings: 2` and `accepted: 2; unaccepted: 0` under `GATE_CHECKOV_PLAN: block` — the two being the
same permanent rows on `github_actions_deploy`. The SPA's task-execution role holds
`ecr:GetAuthorizationToken` on `"*"`, and **checkov does not treat that action as restrictable**, so
it fired nothing. `.github/checkov-plan-accepted.txt` gained no row: writing the one the spec
predicted would have turned the gate red, because a line matching no finding is a hard error there.
Its "execution roles hold zero `Resource: "*"`" claim was **narrowed** instead, to the user-facing
isolation roles, which is what it always meant.

**The default network ACL stays undeclared, and the measurement is why.** The spec said to add
`aws_default_network_acl` *if the regenerated list turned one up*. It did not: checkov 3.3.9
evaluates **no network-ACL check at all** on this tree, passing or failing. Nothing was deferred
here — there was nothing to defer.

| N | Check | Rule | Disposition |
|---|---|---|---|
| 1 | CKV_AWS_332 | ECS service pins a platform version rather than LATEST | **accept — the check is backwards here.** `1.4.0` is pinned deliberately: on 1.3.0 the image pull used a separate Amazon-owned ENI to which VPC endpoints did not apply, so the whole no-NAT design silently would not hold. Following this check would undo the arc's central claim. |
| 1 | CKV_AWS_260 | Security group allows 0.0.0.0/0 on port 80 | **accept** — the port-80 listener's only action is a 301 to HTTPS, asserted by test. A public SPA that cannot be reached at `http://` is one that fails for every user who types the bare host. |
| 1 | CKV2_AWS_28 | ALB fronted by a WAF | **defer** — the same decision as CKV_AWS_68 for CloudFront, and the same reason: real cost, pre-production system. The API fires no WAF check today (`CKV2_AWS_77` passes vacuously, since it grades an attached WebACL's rules and there is none), but it is the same decision and is deferred with it. The client environment's edge is a later choice, and the two should be made together rather than separately. |
| 1 | CKV2_AWS_5 | Security group is attached to another resource | **accept — false positive across a module boundary.** It fires on `module.network.aws_security_group.task`, created in the network module with no rules and no consumer *there*: the ECS service that wears it, and every rule on it, live in `module.spa`. Checkov's graph does not follow that edge. The attachment is real and is asserted by test — the service's `network_configuration` names the group. |
| 2 | CKV_AWS_136 | ECR repository encrypted with a CMK | **defer** — AES256 on both repositories. **The count went from one to two with the Lambda fleet's image, and the original reason does not cover it**: the SPA's layers are a public bundle, while the Lambda image carries this project's own source and its dependencies. What carries the deferral there is different and worth stating rather than inheriting — the image holds no secret and no customer data (every credential the fleet uses is assumed at runtime, and an AST sweep is what keeps one out of the artefact), the repository is private, and a CMK buys a key policy to maintain rather than a secret to protect. **Revisit if the image ever carries a configuration document or a credential**, which is the change that would make the two repositories genuinely different. Consistent with the S3 and SQS no-CMK rows above. |
| 4 | CKV_AWS_158 | Log group encrypted by KMS | **defer** — the same row as the Lambda log groups above, for the same reason. The four are the API function's group, the API's access log group, the VPC flow logs and the ECS task group. |
| 4 | CKV_AWS_338 | Log group retention ≥ 1 year | **accept** — 14 days on all four, matching every other log group here. CloudWatch is the operational tail; the durable store is `logs/` in S3. |
| 1 | CKV_AWS_309 | API Gateway v2 route specifies an authorization type | **accept — authorization will live in the router, and an authorizer would be a SECOND reader of the same token.** *Today there is nothing to authorize:* the deployed API is a placeholder serving `GET /healthz` and a 404, with **no identity, no AWS call and no data** — an internet-facing exposure recorded in `docs/testing/owed.md` and accepted there as billing rather than disclosure. **SPEC-195 adds the verification**, and it goes in the router: the request will carry an `Authorization` bearer, the router will verify it, resolve it to a principal and deny by default before dispatch, and that principal is what SPEC-196 scopes the role assumption by. An API Gateway authorizer would verify the same token independently and could disagree with the router about the claim the scoping depends on — a disagreement with no single arbiter. The API also serves every path through **one `$default` route and one integration**, so a per-route authorizer would have to duplicate the route table before it could say anything at all. This disposition rests on the bearer token, **not** on a session cookie: the arc's re-scope removed the cookie, and any wording that depends on it is stale. **UPDATED (SPEC-195, 2026-08-27): the verification has shipped, and the "nothing to authorize" clause above is now past tense.** The API resolves a principal before dispatch, refuses any undeclared route, and answers an unidentified caller **401 rather than 404** whatever path they ask for. The disposition itself is unchanged and is now load-bearing rather than anticipatory: the verifier is a module the router calls, with no router dependency, so an authorizer would be a second reader of the same token. The exposure this API carries is no longer "none" — it is the unknown-`kid` JWKS refetch, bounded by a per-container cooldown and reasoned about in `decisions/`. |

**`CKV_AWS_65` (Container Insights) is deliberately absent from that table:** the spec's criterion
puts it among the things fixed rather than dispositioned while the resource is new, and the cluster
ships with insights enabled.

**One deviation from that criterion, named rather than left to be noticed.** It also lists ECR
*encryption* among the fixes. Immutability and scan-on-push shipped, but the only ECR encryption
check checkov has is `CKV_AWS_136`, which asks for a **CMK** — so "fixed" would have meant a
customer-managed key and a key policy to maintain, not merely encryption. The repository is
encrypted with AES256 and the check is **deferred** in the row above, consistent with every other
no-CMK row in this file.

### Post-SPEC-140 (run [30830319012](https://github.com/agriffi10/data-analysis-prototype/actions/runs/30830319012), enforcing CSP)

**20 alerts → 13.** Cleared: CSP-not-set, Missing Anti-clickjacking, HSTS, X-Content-Type-Options,
Permissions-Policy, COOP, CORP, and the `Server` banner — replacing `AmazonS3` with CloudFront's own
value is enough for rule 10036, which had been an open question.

What remains, and why:

| Risk | Alert | Disposition |
|---|---|---|
| **Medium** | `CSP: style-src unsafe-inline` | **accept — NEW, and introduced by the fix.** ZAP grades the CSP we added. `'unsafe-inline'` in `style-src` is monaco-editor's requirement (it injects `<style>` at runtime); removing it needs per-response nonces, impossible on a static S3+CloudFront origin without Lambda@Edge. **`script-src` carries no such allowance**, which is the one that matters — this is a CSS-injection weakening, not a script one, and it needs an existing HTML injection vector to exploit. SPEC-140 FR-009 was amended to name it rather than leave a criterion quietly unmet. |
| Low | Cross-Origin-Embedder-Policy | accept — unchanged, see above |
| Low | Timestamp Disclosure — Unix | accept — unchanged, bundle noise |
| Info | ×10 rows | unchanged; the cache rows are **SPEC-141** |

**The lesson worth keeping:** fixing a finding can create one. The total dropping 20 → 13 is the
real improvement, but "zero Medium" was never reachable once we shipped a CSP with a style
allowance — and the criterion that said so was written before we knew ZAP would grade our own work.

### Addendum — the container origin (SPEC-194), recorded ahead of its first scan

The table above is the **2026-08-03 run against the CloudFront origin** and enumerates that run's
twenty alerts. Neither disposition below belongs to it: the container origin has not been scanned
yet — that baseline is owed, non-blocking, and carried in `docs/testing/owed.md`. They are recorded
now so the first scan has something to diff **per alert ID** rather than a judgement to make.

| Alert | Disposition |
|---|---|
| **`Server: nginx` on the container origin (SPEC-194)** | **ACCEPT — a divergence from the CloudFront path, stated rather than assumed.** The distribution strips `Server` outright; nginx cannot. `server_tokens off` hides the **version** and nothing more, and removing the header needs the third-party `headers-more` module, which the official images do not ship. Compiling it against the runtime base's exact source, in lockstep with every base bump and with an ABI mismatch stopping nginx from starting, is real maintenance coupling bought for a banner that now discloses only "nginx". **This alert fires on a VERSION, so it does not regress** — the Phase 5 ZAP diff is read per alert ID to confirm no new *Server Leaks Version Information* row appears. Re-open if a client security review objects to the banner; `headers-more` is the path, and the brotli decision moves with it, both being the same "no third-party module compile stage" call. |
| **HSTS `preload` dropped on the container origin (SPEC-194)** | **ACCEPT, and it costs no finding.** **`CKV_AWS_259` is a CloudFront check**, evaluated against `aws_cloudfront_response_headers_policy.portal` — which still carries HSTS with `preload` and still passes it. nginx's header is invisible to that check, so dropping `preload` on the container origin regresses nothing. **When the distribution is deleted, `CKV_AWS_259` must come off `.github/checkov-enforced.txt` in the same change**: an enforced check ID matching no finding is a hard error, which is the gate working as designed. Three reasons in order of weight: emitting `preload` claims a submission this deployment has not made and does not intend, which is the class of silent divergence the container work exists to catch; the grant is against the **registrable domain** and is close to irreversible, and the SPA and API are subdomains of a parent this repository does not own, so the claim commits sibling services nobody asked; and the cost of dropping it is zero. `max-age=31536000; includeSubDomains` is kept. **Do not re-flip this to satisfy `CKV_AWS_259`** — that check does not read this header, and after the distribution goes it reads nothing at all. |


### Enforce-list removal — CKV_AWS_366, with the Identity Pool (2026-08-30)

`CKV_AWS_366` (*Ensure AWS Cognito identity pool does not allow unauthenticated guest access*) is
removed from `.github/checkov-enforced.txt`. It is **not a suppression**: its only subject,
`aws_cognito_identity_pool.portal`, was retired when the browser stopped needing AWS credentials,
so the check now evaluates against nothing — and an enforced ID with no subject is a hard error
by design, which is `checkov-enforced.sh`'s way of holding *"did not run is never clean"*.

The property the check asserted is not lost, it is unreachable: there is no pool to allow
unauthenticated identities into. The portal role's trust policy has one statement, admitting the
API's execution role and nothing else, so no browser can assume it at all.

**The removal is scheduled to repeat once more.** Retiring CloudFront takes `CKV2_AWS_32`, `46`,
`54`, `72` and `CKV_AWS_34`, `216`, `259`, `305` with it, for the same reason. `CKV_AWS_70` is the
one to measure rather than reason about — the distribution's bucket policy is one of five, and
whether it is that ID's only subject cannot be settled by reading.

### Enforce-list removal — nine IDs, with CloudFront (2026-08-31)

Retiring the distribution, its origin access control, its response-headers policy and its static
bucket leaves nine enforced check IDs with nothing to evaluate: `CKV2_AWS_32`, `CKV2_AWS_46`,
`CKV2_AWS_54`, `CKV2_AWS_72`, `CKV_AWS_34`, `CKV_AWS_216`, `CKV_AWS_259`, `CKV_AWS_305` and
`CKV_AWS_70`. Not suppressions — an enforced ID with no subject is a hard error by design, which
is how `checkov-enforced.sh` holds *"did not run is never clean"*.

**The ninth is the finding worth keeping.** The enforce file predicted eight, and reasoned
`CKV_AWS_70` (*Ensure S3 bucket does not allow an action with any Principal*) would survive because
the distribution's bucket policy is one of five in the tree. It was that ID's only subject: the
other four bucket policies all *do* name a principal, so they fail the check and were never
enforced. Measured with the file's own regeneration command against the post-deletion tree —
**79 passing IDs, nine fewer, nothing newly passing left unenforced**. Reasoning about which IDs a
deletion takes was wrong by one, and that one would have failed the very apply that removed the
resource.

### Design finding — notifications `create` spoofing (not scanner-derived)

Found in the SPEC-115→122 design review (2026-07-12), previously recorded only inside the cancelled
file-converter narrative in `docs/specs/ARCS.md`; rehomed here 2026-08-03. **The shipped notifications
pipeline is not a safe model to copy:** `notifications_writer.py::_resolve_username` takes `username`
straight from the body for `create` messages, and the portal role could `sqs:SendMessage` to that
queue — so a browser could inject a notification into any other user's inbox. User-action messages
(`markRead`/`markAllRead`) are safe (target derived from the verified ID-token claim); only
trusted-producer `create` trusts the body, and the queue's write access is what makes that trust wrong.
**The premise changed again on 2026-08-29:** the portal role's `sqs:SendMessage` is gone, so no
browser credential can write that queue at all, and the API — which now can — reaches it only
through a route whose declared action vocabulary is `markRead`/`markAllRead`. The runtime
`SenderId` boundary that SPEC-206 built therefore names a role that can no longer write, and does
not name the one that can; **that is a gap to close deliberately in the trust-boundary spec, not a
live exposure**, since `create` cannot be reached through any declared route.

**Disposition: CLOSED by SPEC-206 (2026-08-24).** It was *accepted for now — real, shipped,
low-severity* (message injection into an inbox; no data access, no privilege change) and tracked here;
that acceptance no longer stands, because the hole no longer does. The writer now refuses a `create`
whose SQS-stamped `SenderId` names the portal role, comparing the role-id half against the role's IAM
unique ID which Terraform sets on the function. That is the "infrastructure-set marker a body cannot
smuggle" this entry called for, obtained from the service rather than added to the message: `SenderId`
is a message *system* attribute, so a `SendMessage` cannot set it. A refusal **logs and drops** — it
does not raise — because this queue's DLQ is deliberately undrained and dead-lettering every forged
request would hand any signed-in user a way to drown the plane's only operator-facing signal.

The second fix shape this entry proposed — splitting `create` onto its own queue — was **rejected with
reasons** rather than merely not chosen: two queues means two event-source mappings and two concurrent
invocations read-modify-writing one `notifications.json`, trading a spoofing bug for a data-loss bug.
See `docs/decisions/control-planes.md` → *The notifications `create` boundary*.

**Two limits, stated so they are not read as closed.** The grant itself is still unconditioned and
must be — no SQS condition key reaches a field inside a message body — so this is a runtime control,
not an IAM one; Arc B removes the browser's grant entirely (SPEC-200) and the check stays regardless.
And this decides *who may send a `create`*, not who may reach the queue: a body that is not valid JSON,
or that names an unknown action, still dead-letters. No scanner in this baseline can see this class of
finding — it is a design-review artifact.

---

## Proposed blocking thresholds

What the follow-up spec should implement, per scanner.

| Scanner | Proposed gate | Rationale |
|---|---|---|
| `gitleaks` | ~~`block` immediately~~ **DONE 2026-08-02** | Was at zero across 357 commits; flipped to `block`. No remediation was needed. |
| `pip-audit` | ~~`block` immediately~~ **DONE 2026-08-02** | Was at zero across 13 packages; flipped to `block`. |
| Semgrep | ~~`block` after excluding the Flask rule~~ **DONE 2026-08-09** | The one false positive is excluded by rule ID (`--exclude-rule`) on the Lambdas scan, and `GATE_SEMGREP` is `block`. The ruleset is otherwise unnarrowed — dropping `p/owasp-top-ten` to silence one rule would have dropped everything else it brings. A test asserts there is exactly **one** exclusion, so a second needs its own disposition here. |
| `npm audit` (runtime) | stay `report` — **and it cannot be `block` today** | **The earlier note in this row was wrong twice over and is corrected here.** There is no `GATE_NPM_AUDIT_RUNTIME` variable — the gate is `GATE_NPM_AUDIT`, fed the runtime **total** — and `apply-gate.sh` has **no severity threshold**: it fails on `findings > 0`. So "block at `high` would pass today" was not available; flipping it would go red immediately on the accepted `dompurify` advisories — four of them as of 2026-08-30, which `.metadata.vulnerabilities.total` (the number the gate is actually fed) collapses to **2**. The two counts are easy to conflate; the gate reads the collapsed one. It becomes available when dompurify clears, which needs **monaco** to move: monaco vendors its own copy, so no override of the npm package clears the shipped code even though it would clear the gate. Adding a severity threshold to `apply-gate.sh` is the alternative, and is a change to every scanner's gate rather than this row's. |
| `npm audit` (full) | stay `report` | Build-time advisories should be visible, not blocking; they would gate PRs on unrelated toolchain churn. |
| Checkov | ~~`block` only on an explicit allow-list of check IDs~~ **DONE 2026-08-09** | Implemented as an **enforce list**, `.github/checkov-enforced.txt` — 52 check IDs, every one measured at **zero failures** (checkov 3.3.9, 508 passed / 373 failed overall). `GATE_CHECKOV` is `block` and reads that narrowed count; the other 373 are still published and still do not block. The criterion is deliberately "passes today", not "matters most": picking the five that matter is an argument to re-litigate on every infra change, and holding everything already clean costs nothing to turn on. An enforced ID that gets evaluated against **nothing** is a hard error — a typo or a renamed check must not read as enforcement. |
| ZAP | stay `report` | Unauthenticated surface only; findings are header hygiene, better fixed via CKV2_AWS_32 than gated on. **Measured 2026-08-03:** 0 fail, 2 Medium, 8 Low. After SPEC-140 two Lows survive by decision, so a total-count gate is wrong here — gate by **risk level** (`riskcode >= 2`) if at all. |

> **Status, 2026-08-09.** Four of six scanners now block: gitleaks, pip-audit, Semgrep and
> Checkov (narrowed), plus `GATE_CHECKOV_PLAN` on the rendered-plan IAM scan. The two that
> remain on `report` are there for stated reasons, not inertia — `npm audit` needs either
> dompurify to clear or a severity threshold in `apply-gate.sh`, and ZAP needs gating by risk
> level rather than by count. Neither is a fix waiting to be written; both are decisions.


---

# Addendum — Rendered-Plan IAM Scan (SPEC-139)

**Taken:** 2026-08-02, from the `deploy-infra.yml` `plan` job on PR #319 (run 30758960179).

Checkov over `tofu show -json`, `--framework terraform_plan`. This is the scan that reads the
isolation model; the `.tf` scan above cannot.

| | |
|---|---|
| Resources scanned | 226 |
| Failed / passed | 239 / 733 |
| Parsing errors | 0 |
| **IAM resources in plan** | **55** |
| **IAM checks evaluated** | **431** (the `.tf` scan evaluates **0**) |
| **IAM findings** | **6** |

## The headline: the isolation model is clean

All 6 IAM findings are on **deploy roles**. Every policy implementing per-user isolation — the
portal role, the shared-space grants, the analytics scoping — passed all 431 IAM checks.
`portal-role-permissions` has three statements and **zero** `Resource: "*"`.

That is the result this scan existed to produce, and it could not have been stated before SPEC-139.

## The 6 findings

| Check | Resource | Disposition |
|---|---|---|
| CKV_AWS_290 — write access without constraints | `module.base.aws_iam_policy.deploy_control_plane_dlq_drain` | **fix via condition key** |
| CKV_AWS_355 — `*` resource for restrictable actions | `module.base.aws_iam_policy.deploy_control_plane_dlq_drain` | as above |
| CKV_AWS_290 | `module.base.aws_iam_policy.deploy_notifications` | as above |
| CKV_AWS_355 | `module.base.aws_iam_policy.deploy_notifications` | as above |
| CKV_AWS_290 | `module.base.aws_iam_role_policy.github_actions_deploy` | as above |
| CKV_AWS_355 | `module.base.aws_iam_role_policy.github_actions_deploy` | as above |

**Correction (2026-08-02): these are NOT one cause.** The original triage said all six were the
`lambda:*EventSourceMapping` wildcard. Reading the policies showed two distinct causes:

- **4 findings** (2 checks × 2 policies) — the `lambda:*EventSourceMapping` statements on
  `deploy_notifications` and `deploy_control_plane_dlq_drain`. **Fixed**, see the addendum below.
- **2 findings** on `github_actions_deploy` — a different set of wildcards entirely:
  `cloudfront:CreateDistribution`, `cognito-idp:CreateUserPool`, `cognito-identity:CreateIdentityPool`,
  `logs:DescribeLogGroups` and the Lake Formation account-level actions. These are **genuinely
  non-scopable**: there is no resource ARN to name before the resource exists, and Lake Formation's
  settings/permissions actions are account-scoped by design. **Accepted** — no condition key exists
  for them either.
  > **Superseded 2026-09-02 (SPEC-202).** Both were `cloudfront:*` alone, and both are gone with
  > the grant — see *What remains, and why it is not fixable* below, which carries the measurement
  > and why the other actions in this bullet never raised a finding.

Scope note: these are **CI deploy** permissions, not runtime user permissions. The blast radius is
"a compromised GitHub Actions OIDC session could manage event-source mappings on any Lambda in the
account", which matters, but is a different and smaller thing than a user-facing isolation hole.

## The two scans are complementary, not redundant

Neither subsumes the other, so both stay:

- Only the **`.tf` scan** reports CKV_AWS_50 (Lambda X-Ray), CKV_AWS_115, CKV_AWS_18, CKV_AWS_82,
  CKV_AWS_86, CKV2_AWS_40/42/61 — and it runs on every PR and on the weekly sweep.
- Only the **plan scan** evaluates IAM policy documents at all, and it resolves interpolated values,
  so some `.tf` findings correctly disappear here.

## Proposed gate

`GATE_CHECKOV_PLAN`: **`block` on IAM findings only**, once the `lambda:FunctionArn` condition lands.
Gating the 239 total would mean suppressing the same mostly-inapplicable rules already triaged above.
The IAM subset is the part worth defending, it is already down to one fixable cause, and the
summary already counts it separately.


---

# Addendum — Remediation, 2026-08-02

## Gates flipped

`GATE_GITLEAKS` and `GATE_PIP_AUDIT` are now **`block`**. Both measured zero — no secret in any of
357 commits, no advisory across 13 Python packages — so this cost no remediation and closes the two
classes where a first finding should never be merged.

The rest remain `report` pending the fixes named above.

## `react-router` 7.17.0 → 7.18.2

**Four of the five advisories cleared.** The declared floor in `apps/portal/package.json` moved to
`^7.18.2` so a lockfile regeneration cannot resolve back below the fix.

| Advisory | Status |
|---|---|
| GHSA-wrjc-x8rr-h8h6 — open redirect via backslash in `<Link>`/`useNavigate` | **cleared** |
| GHSA-chx6-hx7r-mcp5 — DoS via inefficient route matching | **cleared** |
| GHSA-h8fp-f39c-q6mh — RSCErrorHandler XSS | **cleared** |
| GHSA-337j-9hxr-rhxg — SSR hydration constructor injection | **cleared** |
| GHSA-qwww-vcr4-c8h2 — RSC-mode CSRF bypass | **remains** — accepted |

The one that cleared and mattered is the **open redirect**: it was the only react-router advisory
with a plausible path in this app, and the app-level defence in `notificationLink.ts` is no longer
the single thing standing in front of it.

**The survivor needs react-router v8** (`>8.2.0`); `react-router-dom@7.18.2` still depends on
`react-router@7.18.2`, so no 7.x release can clear it. Accepted rather than migrated: the advisory is
an **RSC-mode** issue, and this is a client-only SPA with no React Server Components and no server
at all. A v8 major upgrade to fix an inapplicable finding is not a good trade.

Correction to the original triage above, which called this bump a straightforward fix: it clears
what matters, not everything. The residual is real, inapplicable, and needs a major.

Verified: lint (`--max-warnings 0`), format, build, and 161 files / 1186 tests green on 7.18.2.

---

# Addendum — `lambda:FunctionArn` Condition, 2026-08-02

The 4 event-source-mapping findings are fixed. Reading the policies first changed the fix twice.

## The DLQ drain statement was dead permission

`DlqDrainEventSourceMappingManage` granted the four mapping actions on `Resource: "*"` — for a
control plane that **has no event-source mapping**. SPEC-126 replaced the four SQS mappings with a
single 10-minute EventBridge schedule, and the grant was never removed; the resource description
still said "four SQS event-source mappings".

**Deleted rather than conditioned.** Least privilege by removal beats least privilege by condition.
Its `lambda:ListTags` was redundant — already granted, function-scoped, in `DlqDrainLambdaManage`.

That policy now has **zero** wildcard statements.

## The notifications statement is split, because only part of it can be narrowed

One real mapping exists (`aws_lambda_event_source_mapping.writer`). AWS's own service reference
settles what is possible:

| Action | Resource types | Condition keys |
|---|---|---|
| `CreateEventSourceMapping` | none | **`lambda:FunctionArn`** |
| `Get`/`Update`/`DeleteEventSourceMapping` | `eventSourceMapping` | **`lambda:FunctionArn`** |
| `ListEventSourceMappings` | **none** | **none** |

So the statement became two:

- `NotificationsEventSourceMappingManage` — the four scopable actions, `Resource: "*"` with
  `ArnLike lambda:FunctionArn = arn:aws:lambda:${aws_region}:*:function:${project_name}-*-notifications-writer`.
  The deploy role can no longer attach a mapping to an arbitrary Lambda in the account.
- `NotificationsEventSourceMappingList` — `ListEventSourceMappings` alone, bare `"*"`, **deliberately
  unconditioned**. AWS defines no resource types and no condition keys for it, so a condition would
  deny the call outright — the "unknown-ARN-in-list" trap from `infra/info/deploy-role-iam.md`. This one is a
  documented accept, not an oversight.

`lambda:ListTags` was dropped here too, for the same redundancy reason.

## What remains, and why it is not fixable

> **Superseded 2026-09-02 — nothing remains.** SPEC-202 destroyed the distribution and the deploy
> role's `cloudfront:*` statement came off one apply later; with it gone the rendered policy reports
> **zero** CKV_AWS_290 and CKV_AWS_355, so `.github/checkov-plan-accepted.txt` is empty and every IAM
> finding on the plan now blocks. Measured against the pinned checkov's own scanner, not argued —
> and the measurement corrects **both paragraphs below**, the triage and the gate proposal that
> says a blanket block is unavailable. The other actions named there were **not** co-causes: both
> checks wrap cloudsplaining, which does not count an action it already classifies as taking no
> resource type, so an unscopable action alone raises nothing. What raised these two was an action
> that **could have been scoped and was not** — CKV_AWS_355 counts every such action, CKV_AWS_290
> the write subset — and every one of them was CloudFront's.
> `cognito-identity:CreateIdentityPool` went with the Identity Pool in the same spec.

The 2 findings on `github_actions_deploy` are a different cause and stay: `cloudfront:CreateDistribution`,
`cognito-idp:CreateUserPool`, `cognito-identity:CreateIdentityPool`, `logs:DescribeLogGroups` and the
Lake Formation account-level actions. None has a resource ARN to name before the resource exists, and
none has an applicable condition key.

**Revised gate proposal.** `GATE_CHECKOV_PLAN` cannot go to a blanket `block` — 2 permanent,
unfixable findings remain. Gate by **check ID plus resource**, or accept a documented suppression for
`github_actions_deploy` on CKV_AWS_290/355 and block on everything else.

---

# Addendum — Outcome and the Lockout It Caused, 2026-08-02

**IAM findings 6 → 2, applied and verified on `main`** (`Apply complete! Resources: 0 added,
0 changed, 0 destroyed` on a normal, refresh-enabled run). IAM checks evaluated rose 431 → 432.

## What shipped

- **DLQ drain:** `DlqDrainEventSourceMappingManage` deleted — dead permission for a control plane
  that has had no event-source mapping since SPEC-126. That policy now has **zero** wildcards.
- **Notifications:** the four scopable actions are condition-scoped on `lambda:FunctionArn`;
  `ListEventSourceMappings` keeps a bare `"*"` because AWS defines no resource types or condition
  keys for it; `lambda:ListTags` sits in its own statement scoped to
  `arn:aws:lambda:${aws_region}:*:event-source-mapping:*`.

## The lockout, recorded because it will happen again

The first attempt removed `lambda:ListTags` from the mapping statement, reasoning it was redundant
with the function-scoped grant in `NotificationsWriterLambdaManage`. **It is not — a mapping ARN and
a function ARN are different resource types**, and AWS's service reference lists both under
`ListTags`. That broke `main`: the next refresh needed the permission the pending fix restored, so
plan, apply *and revert* all failed on the same `AccessDenied`.

Recovered with the new `skip_refresh` dispatch lever (`docs/decisions/infrastructure.md`), then confirmed with an
ordinary refresh-enabled run.

Two things worth carrying forward:

- **Tightening a grant deadlocks exactly like widening one.** Least-privilege edits to the deploy
  role's own policies need the same care as new grants.
- **A green `plan` proved nothing.** `plan` passed twice while `apply` failed on the identical call
  with no policy change between — IAM is eventually consistent, so the deadlock can look
  intermittent. Only a normal, refresh-enabled **apply** settles it.

## Revised gate proposal (supersedes the one above)

`GATE_CHECKOV_PLAN` **cannot** become a blanket `block`: 2 permanent findings remain on
`github_actions_deploy`, and neither has a resource ARN to name or a condition key to apply. Gate by
**check ID + resource**, or carry a documented suppression for those two and block on everything else.

---

# Addendum — The Gates Went On, 2026-08-09

Four scanners block as of this change: gitleaks and pip-audit (since 2026-08-02), plus **Semgrep**
and **Checkov**, and `GATE_CHECKOV_PLAN` on the rendered-plan IAM scan. What each one needed:

## Semgrep — one exclusion, by rule ID

`--exclude-rule=python.flask.security.audit.directly-returned-format-string.directly-returned-format-string` on the Lambdas scan.
That was the entire finding set. The ruleset is otherwise unnarrowed, because dropping
`p/owasp-top-ten` to silence one rule would drop everything else it brings. A test asserts there is
**exactly one** exclusion, so a second one cannot be added without landing a disposition here.

## Checkov (`.tf`) — an enforce list, not a suppression list

`.github/checkov-enforced.txt` names **52 check IDs**, every one measured at zero failures. The gate
reads the number of failures on those IDs; the other 373 findings publish and do not block.

The direction matters. Suppressing 22 accepted rules to enforce the rest would produce a file nobody
reads and a gate whose meaning drifts every time a rule is added upstream. Enforcing what already
passes costs no remediation, states exactly what it holds, and fails on the thing worth failing on —
a regression.

**The criterion is "passes today", not "matters most."** Two of the 52 are merely operational
(`CKV_AWS_216` distribution-enabled, `CKV_AWS_305` default-root-object). Deciding which checks
deserve enforcement is an argument that has to be had again on every infra change; "everything
currently clean" does not.

Two traps the implementation had to handle:

- **`--quiet` strips `passed_checks`**, and without them every enforced ID looks *unevaluated*. The
  flag is gone from the scan, and a test pins its absence — `deploy-infra.yml`'s plan scan had
  already learned this and said so in a comment.
- **An enforced ID evaluated against nothing is a hard error**, not a pass — and so is a plan-scan
  acceptance matching no finding. A typo, a check renamed by a version bump, or a resource class
  leaving the repo all produce a line that enforces nothing while reading as enforcement. Same rule
  as "did not run is never clean", turned on the gate's own configuration.

## Checkov (rendered plan) — accepted by check ID **and resource**

`.github/checkov-plan-accepted.txt` carries the two permanent deploy-role findings — `CKV_AWS_290`
and `CKV_AWS_355` on `module.base.aws_iam_role_policy.github_actions_deploy` — and nothing else. The
gate counts IAM findings not on that list; today that is **0** of 2 (454 IAM checks passed).

Accepting by ID *and* resource is the point: the same two rules firing on any other policy still
fail the job. The isolation policies have zero `Resource: "*"` and this is what keeps it that way.

**A stale acceptance is a hard error, same as the enforced list.** An earlier draft made it a
warning, reasoning that this job "applies production infrastructure". It does not: `plan` is
`pull_request`-only and `apply` has no `needs: plan`, so **neither Checkov gate can redden a deploy**
— both block PRs and nothing else. The reasoning was wrong; the strict behaviour it was arguing
against is the right one.

**The accept list covers only the rules firing today.** Adding a new non-scopable wildcard action to
`github_actions_deploy` — the recurring case CLAUDE.md's "Infra rule" mandates — can fire
`CKV_AWS_356`/`CKV_AWS_111`/`CKV_AWS_49` on that resource, none of them accepted. Such a change is a
two-part edit: the grant, and its acceptance. Designed friction, recorded so it is not a surprise.

## Two shell facts are what make every hard error above reachable

The first draft of this change had neither, and every hard error it so carefully raised arrived at
the gate as a **silent green**. Both are worth knowing before writing another gate step.

- **`echo "VAR=$(script)"` does not fail the step when `script` fails.** `echo` exits 0 whatever its
  argument's substitution did, `set -e` sees success, and the empty string it writes to `GITHUB_ENV`
  wins over anything recorded earlier. Only an **assignment**'s failed substitution trips `set -e`.
  Measured: the `echo` form leaves `CHECKOV_FINDINGS=` and a step exit of 0; the assignment form
  exits 2.
- **`${VAR:-0}` substitutes on EMPTY as well as unset.** So the empty value above becomes `0`, and
  `apply-gate.sh` — which does reject a non-numeric count — never sees one. Both gates now default to
  the non-numeric sentinel `no-count`. ZAP's step already used `no-report` for exactly this reason,
  with a comment saying so; it was there to be copied and wasn't.

Each workflow still records the full count before narrowing. That is belt to the sentinel's braces,
not the primary defence — the claim in an earlier draft that it made the gate "fail closed" was
wrong, since the failure mode it named is the one it did not cover.

## What still does not block, and why it is not an oversight

- **`npm audit`** — the gate has no severity threshold (`apply-gate.sh` fails on `> 0`), and the
  runtime scope still carries accepted `dompurify` advisories. Needs monaco to move, or a threshold in
  the shared script.
- **ZAP** — a count gate is wrong here; two Lows survive by decision. Gate by `riskcode >= 2` if at
  all.

## One exposure accepted with the Semgrep flip

`SEMGREP_VERSION` pins the binary; `--config p/owasp-top-ten` and the language sets are fetched from
the registry at scan time and are **not pinned**. Blocking on an unpinned rule source means an
upstream rule addition can redden every PR and the weekly `main` run with no code change — the shape
#311 made this repo pin everything to avoid, and CLAUDE.md's "every scanner version-pinned" is
therefore true of the binaries and not of Semgrep's rule content.

Accepted, for two reasons. `pip-audit` already blocks against a live advisory database with the
identical property, so this is not a new class of exposure. And the alternative — vendoring the ~157
rules — trades a rare interruption for permanent staleness in the one scanner whose value is that its
rules keep up. If a second false positive arrives, the answer is another `--exclude-rule` with a
disposition in this file, not a narrowed count.

**The first attempt at the exclusion was wrong and the gate caught it.** Semgrep's rule ID doubles
its last component — `python.flask.security.audit.directly-returned-format-string.directly-returned-format-string`
— and this file's findings table had transcribed the short form, which the workflow, the comment and
the guard test all inherited. The guard test passed (it asserts the string is present, not that
Semgrep matches it); the CI run failed. Worth noting as the general case: **a test that a scanner is
configured is not a test that the configuration works.** Only the blocking run is.

---

# SPEC-186 FR-004 — the archive-audit trail (2026-08-14)

`modules/verification` introduces two resource kinds the `.tf` scan has never seen — an
`aws_cloudtrail` and its delivery bucket. Neither reddens anything: none of the checks below is on
`.github/checkov-enforced.txt`, so they are report-only rows. They are dispositioned here because
this file, not the enforce list, is where the project has decided dispositions live — and a
report-only row with no written reason is the thing that later reads as an oversight.

| Check | Resource | Disposition |
|---|---|---|
| `CKV_AWS_67` — multi-region trail | `module.verification.aws_cloudtrail.archive_audit` | **Accept.** Single-region ON PURPOSE. The archive plane lives in one region; a multi-region trail would record calls this trail exists to have no opinion about, and would widen a targeted audit record into a general-purpose one. Reasoning is in `cloudtrail.tf`. |
| `CKV_AWS_35` — trail encrypted with a CMK | same | **Accept.** The bucket is SSE-S3 (`AES256`, `s3.tf`), matching every other bucket in this account. A CMK adds key management and cost to a record whose contents are already only "which object key was called, by whom, when" — no user data, no file contents. Revisit if the account ever adopts CMKs generally. |
| `CKV_AWS_252` — trail notifies an SNS topic | same | **Accept.** Nothing consumes this record continuously; it is read by a human running a live check, days or hours after the fact. An SNS topic would be a subscriber-less notification path. |
| `CKV_AWS_18` — access logging on the trail bucket | `module.verification.aws_s3_bucket.trail` | **Accept**, on the same grounds the other buckets in this account take it: access logs on an audit bucket need their own bucket, and the regress is unbounded. The bucket is private, PAB-blocked, and its policy grants only CloudTrail. |
| `CKV_AWS_144` — cross-region replication | same | **Accept.** A verification aid, not a compliance vault. The 400-day expiry (`trail_retention_days`) already says how long this record is meant to matter. |

**Log-file validation IS on** (`enable_log_file_validation = true`), which is the property that
matters most for a record whose whole job is to be believed.

**What is deliberately NOT here: a bucket-policy Deny on writes.** The obvious one — deny
`s3:PutObject` where `aws:PrincipalServiceName != cloudtrail.amazonaws.com` — rests on a condition
key CloudTrail's own delivery must populate for its Allow to survive it. If it does not, delivery
fails and the trail is **silently empty**, which is this spec's own "did not run is never clean"
failure with the evidence rather than with a scanner. The residual is that an account principal with
identity-based S3 write could tamper with the record; that is acceptable for an operator's
verification aid and would not be for a compliance vault.

## The plan scan rejected the role's trust, and the accept list did not grow

`CKV_AWS_61` fired on `module.verification.aws_iam_role.verification` for a trust policy delegating
to `arn:aws:iam::{account}:root`. **Not accepted.** The rule for
`.github/checkov-plan-accepted.txt` is that it holds findings with **no scopable alternative** —
CloudFront and Cognito creation have no ARN before the resource exists and no applicable condition
key. Naming the principal IS a scopable alternative, so accepting would have been suppressing a
fixable finding, which that file's own header warns against. `verification_principal_arns` is now a
root variable, empty by default, and the role is not created until it is set. IAM findings on the
rendered plan stay at **2 accepted, 0 unaccepted**.

## Checkov (`Dockerfile`) — a second framework, one file, two dispositions

Until the Lambda fleet's container image landed, **no scanner in this repository looked at any
Dockerfile**. Checkov parsed `.tf` only, Semgrep's Lambda scan found no Dockerfile under `lambdas/`
because there was none, and its SPA scan is scoped to `apps/portal/src`. The image adds one, so the
already-pinned Checkov is now asked a second question about it. **No scanner is added, removed or
re-pinned** — `CHECKOV_VERSION` installs one binary and `--framework dockerfile` is a second
invocation of it.

The gate is the same shape as the `.tf` one and shares its script: an **enforce list** measured at
zero (`.github/checkov-dockerfile-enforced.txt`, 21 IDs against checkov 3.3.9 on 2026-09-01,
38 passed / 2 failed), narrowed rather than totalled, with an ID that evaluates against nothing
treated as a hard error. Its findings are **added to** the Checkov numerator rather than gated
separately, so one number still decides the job.

| Count | Check | Disposition |
|---|---|---|
| 1 | `CKV_DOCKER_2` | **Accept — the check does not apply to this runtime.** Lambda never runs a Docker `HEALTHCHECK`; the Runtime API contract is the health signal, and the service decides an execution environment is unhealthy by the runtime failing to respond, not by an instruction in the image. Declaring one would declare something nothing reads, which is worse than declaring nothing. The SPA image has **no** disposition for this check because it is not scanned at all (see below); its health is read by the load balancer's target group rather than by a Docker instruction, so the two images would reach the same answer by different routes. |
| 1 | `CKV_DOCKER_3` | **Accept for now, and it is a real gap rather than an inapplicable check.** The AWS-published `public.ecr.aws/lambda/python` base image sets no `USER`, `/var/task` and `/opt` are root-owned, and Lambda's isolation boundary is the per-execution environment rather than the container user — the process is not network-reachable and the root filesystem is read-only in the deployed runtime (asserted: the behaviour matrix runs the container `--read-only`). Adding a `USER` means re-owning both trees and is a change to how the runtime starts, which is not something to do inside a packaging spec and prove nowhere. **Revisit if AWS's base image adopts one**, or with any change that already touches the image's startup. |

**`apps/portal/Dockerfile` is still scanned by nothing, and that is recorded rather than closed.**
It **passes** `CKV_DOCKER_3` (it sets `USER 101`) where the Lambda image cannot, so a single shared
enforce list would have to drop that check — and the SPA would then be unable to enforce a check it
currently satisfies. Covering both wants an enforce list per Dockerfile, which is a widening the
packaging spec deliberately declined mid-review rather than adding late and unexamined. The cost of
the gap is that the SPA image is where it already was: unscanned. Closing it is a small change and
wants its own.

**Semgrep was checked against the new file rather than assumed clean**, because `security.yml`
scans the path `lambdas` with `p/owasp-top-ten` + `p/python` and `GATE_SEMGREP` is `block` — so the
first Dockerfile under that path could have reddened a blocking gate. Measured with the pinned
1.172.0: **1 path scanned, 0 findings, 0 errors.**

# Addendum — The Container Cutover Did Not Change the Fleet's Posture, 2026-09-02

SPEC-213 moved all 86 Lambdas from zip packaging to one container image. Every function is now a
call to `infra/modules/docker-lambda`, so the `.tf` scan sees **one** `aws_lambda_function` resource
instead of seventeen. The enforce list was regenerated with the command in its own header, at the
pinned checkov 3.3.9, and diffed rather than pasted over.

**`.github/checkov-enforced.txt` is unchanged, and that is the measured result, not an omission.**
Before: 955 passed / 763 failed. After: 1119 passed / 585 failed. No enforced ID became
unevaluated — the hard error `checkov-enforced.sh` raises when a resource family leaves the repo —
and no enforced ID started failing. `CKV_AWS_363` (deprecated runtime) was the one to watch, since a
container function declares no `runtime` at all; it evaluates and passes.

## Two IDs newly qualify and are deliberately NOT enforced

`CKV_AWS_115` (reserved concurrency) and `CKV_AWS_117` (Lambda inside a VPC) went from 86 failures
and one pass to 86 passes and zero failures. **Nothing about the fleet's posture changed.** Both
already passed on `aws_lambda_function.this` — the container module's own resource, scanned
standalone — and the cutover simply made every function that resource:

- `CKV_AWS_117` passes because the module declares `dynamic "vpc_config"`. The block yields **no**
  configuration at all: every caller passes `vpc_config = null`, and the API function is
  deliberately outside the VPC (row 32 above, and `modules/api/README.md`).
- `CKV_AWS_115` passes because the module always declares `reserved_concurrent_executions`. Its
  value is `-1`, which is the provider's spelling of **unreserved** — no limit.

Enforcing either would hold at zero a check that passes for a structural reason and contradicts a
written disposition on this page: `CKV_AWS_117` is an **accept** ("no VPC, deliberately") and
`CKV_AWS_115` is a **defer**. A gate asserting the opposite of the register beside it is worse than
no gate, and it would fire the day somebody removed the `dynamic` block for a reason unrelated to
VPC posture.

This is a deliberate deviation from the list's own rule — *"they are here because they pass, which
is the whole rule"* — and it is recorded here because that header says a decision about the list's
contents belongs on this page. **The rule still holds for a check that passes because the thing it
checks is true.** These two pass because of how the configuration is SHAPED, and the distinction is
what a regeneration cannot see: re-measure, then ask what made each new arrival pass before adding
it.
