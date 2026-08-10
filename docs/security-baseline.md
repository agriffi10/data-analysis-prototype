# Security Scanning — Baseline

**Taken:** 2026-08-02, on the SPEC-138 branch, at `4a6fee8`.
**Status:** snapshot. This is the input to the spec that turns the gates on; that spec
supersedes this file rather than editing it forever.

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
| SPA deps | `npm audit --omit=dev` (runtime) | 4 |
| SPA deps | `npm audit` (full) | 6 → **4** (2026-08-03, `postcss` + `brace-expansion` cleared; see below) |
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

### Dependencies — npm (6 advisories, 4 reaching the browser)

The runtime/build split is the whole point of auditing at two scopes.

| Sev | Package | Scope | Advisory | Disposition |
|---|---|---|---|---|
| high | `react-router` | **runtime** | GHSA-chx6-hx7r-mcp5 — DoS via inefficient route matching | **FIXED** (7.18.2) |
| high | `react-router` | runtime | GHSA-qwww-vcr4-c8h2 — RSC-mode CSRF bypass | **FIXED** (8.3.0, 2026-08-05) — was `accept`; the v8 bump made accepting it unnecessary |
| medium | `react-router` | runtime | GHSA-337j-9hxr-rhxg — SSR hydration constructor injection | **FIXED** (7.18.2) |
| medium | `react-router` | runtime | GHSA-h8fp-f39c-q6mh — RSCErrorHandler XSS | **FIXED** (7.18.2) |
| medium | `react-router` | **runtime** | GHSA-wrjc-x8rr-h8h6 — open redirect via backslash in `<Link>`/`useNavigate` | **FIXED** (7.18.2) |
| medium | `dompurify` | runtime (via monaco) | GHSA-cmwh-pvxp-8882 — `ALLOWED_ATTR` pollution | **defer** |
| low | `dompurify` | runtime (via monaco) | GHSA-c2j3-45gr-mqc4, GHSA-vxr8-fq34-vvx9 | **defer** |
| high | `postcss` | build | GHSA-r28c-9q8g-f849 — path traversal via `sourceMappingURL` | ~~fix~~ **DONE 2026-08-03** — 8.5.15 → 8.5.25 |
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
- **`dompurify` is transitive through `monaco-editor`**, and npm's proposed fix is
  `monaco-editor@0.53.0` — a **downgrade**, flagged breaking. Deferred: the advisories concern
  `setConfig`/`clearConfig` poisoning APIs the portal never calls, and monaco is lazy-loaded on the
  Query route only (SPEC-035). Revisit when monaco ships a forward fix.

  **Re-examined 2026-08-05, still deferred — and now with the reason the `overrides` route is
  closed.** `monaco-editor@0.56.0` (still the latest release; everything published after it is a
  `-dev-` prerelease) pins `dompurify: '3.4.8'` **exactly**, so Dependabot has no in-range update to
  open a PR with — which is why three alerts sit open with no PR rather than being ignored.
  `dompurify` 3.4.13 clears all three, but **npm will not apply a newly-added `overrides` entry
  against an existing lockfile**: `npm install`, `npm install --package-lock-only`, `npm update`
  and a clean-room re-resolve seeded with the committed lock were all verified to leave 3.4.8 in
  place. Only a **from-scratch** resolution (no lockfile) honours the override — and that
  re-resolves every caret range at once, measured at **134 package version changes**, the whole AWS
  SDK and Amplify surface included. That is an unrelated mass dependency bump riding along with
  three advisories in code paths the app never calls, so it is not worth taking as a security fix.
  It also explains this file's earlier note that an `overrides` block "silently did nothing" —
  npm's behaviour, not a malformed entry. **Take it when monaco moves, or as a deliberate
  dependency-refresh of its own.**
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
  **Full and runtime now read the same 4** — every remaining advisory is in a runtime dependency,
  so `--omit=dev` no longer subtracts anything.

### Dependencies — Python

**0 vulnerabilities across 13 packages.** Nothing owed.

### Secrets

**0 findings across all 357 commits.** No allowlist file was needed, so none was committed.

### SAST — Semgrep

| Sev | Rule | Location | Disposition |
|---|---|---|---|
| warning | `python.flask.security.audit.directly-returned-format-string` | `lambdas/table-share-common/tscommon/copy_plan.py:84` | **accept** — false positive |

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
| 32 | CKV_AWS_117 | Lambda inside a VPC | **accept** — there are no VPC resources. Every function talks to AWS APIs only; a VPC would add NAT cost and no isolation. |
| 32 | CKV_AWS_116 | Lambda dead-letter queue | **accept — wrong shape.** The check looks for the Lambda's own `dead_letter_config`, which covers async invoke. This fleet is SQS/Step-Functions driven and *does* have per-request DLQs with a drain (SPEC-126). |
| 32 | CKV_AWS_50 | Lambda X-Ray tracing | **accept** — SPEC-127→137 built structured logging as the observability answer, deliberately. X-Ray would be a second parallel system. |
| 32 | CKV_AWS_173 | Lambda env var encryption (CMK) | **defer** — env vars hold queue URLs and bucket names, not secrets. |
| 32 | CKV_AWS_115 | Lambda reserved concurrency | **defer** — genuinely worth considering for SQS-fronted control planes. Follow-up. |
| 32 | CKV_AWS_272 | Lambda code signing | **defer** — needs a signing profile and a deploy-pipeline change. |
| 5 | CKV_AWS_21 | S3 versioning | **DEFERRED (2026-08-03, user decision)** — pre-production, no real user data, so the exposure is theoretical today. The reasoning stands and does not expire: S3 has no atomic move, so rename/move is `CopyObject` + `DeleteObject` (architecture.md, Known Constraints), and without versioning a failure between those two steps is **unrecoverable user data loss**. **Revisit before any real data lands.** |
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

### Design finding — notifications `create` spoofing (not scanner-derived)

Found in the SPEC-115→122 design review (2026-07-12), previously recorded only inside the cancelled
file-converter narrative in `docs/specs/ARCS.md`; rehomed here 2026-08-03. **The shipped notifications
pipeline is not a safe model to copy:** `notifications_writer.py::_resolve_username` takes `username`
straight from the body for `create` messages while the portal role can `sqs:SendMessage` to that queue —
so a browser can inject a notification into any other user's inbox today. User-action messages
(`markRead`/`markAllRead`) are safe (target derived from the verified ID-token claim); only
trusted-producer `create` trusts the body, and the queue's write access is what makes that trust wrong.
**Disposition: accepted for now — real, shipped, low-severity** (message injection into an inbox; no
data access, no privilege change), **tracked separately.** The fix shape is known: derive or verify the
`create` recipient the way SPEC-122's trust-marker design does for Table Builder (infrastructure-set
marker a body cannot smuggle), or split trusted-producer `create` onto a queue the portal role cannot
write to. No scanner in this baseline can see this class of finding — it is a design-review artifact.

---

## Proposed blocking thresholds

What the follow-up spec should implement, per scanner.

| Scanner | Proposed gate | Rationale |
|---|---|---|
| `gitleaks` | ~~`block` immediately~~ **DONE 2026-08-02** | Was at zero across 357 commits; flipped to `block`. No remediation was needed. |
| `pip-audit` | ~~`block` immediately~~ **DONE 2026-08-02** | Was at zero across 13 packages; flipped to `block`. |
| Semgrep | ~~`block` after excluding the Flask rule~~ **DONE 2026-08-09** | The one false positive is excluded by rule ID (`--exclude-rule`) on the Lambdas scan, and `GATE_SEMGREP` is `block`. The ruleset is otherwise unnarrowed — dropping `p/owasp-top-ten` to silence one rule would have dropped everything else it brings. A test asserts there is exactly **one** exclusion, so a second needs its own disposition here. |
| `npm audit` (runtime) | stay `report` — **and it cannot be `block` today** | **The earlier note in this row was wrong twice over and is corrected here.** There is no `GATE_NPM_AUDIT_RUNTIME` variable — the gate is `GATE_NPM_AUDIT`, fed the runtime **total** — and `apply-gate.sh` has **no severity threshold**: it fails on `findings > 0`. So "block at `high` would pass today" was not available; flipping it would go red immediately on the two accepted `dompurify` rows. It becomes available when dompurify clears, which needs monaco to move (it pins the version exactly). Adding a severity threshold to `apply-gate.sh` is the alternative, and is a change to every scanner's gate rather than this row's. |
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
  deny the call outright — the "unknown-ARN-in-list" trap from architecture.md. This one is a
  documented accept, not an oversight.

`lambda:ListTags` was dropped here too, for the same redundancy reason.

## What remains, and why it is not fixable

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

Recovered with the new `skip_refresh` dispatch lever (`decisions.md`), then confirmed with an
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

`--exclude-rule=python.flask.security.audit.directly-returned-format-string` on the Lambdas scan.
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
- **An enforced ID evaluated against nothing is a hard error**, not a pass. A typo, a check renamed
  by a version bump, or a resource class leaving the repo all produce a line that enforces nothing
  while reading as enforcement. Same rule as "did not run is never clean", turned on the gate's own
  configuration.

## Checkov (rendered plan) — accepted by check ID **and resource**

`.github/checkov-plan-accepted.txt` carries the two permanent deploy-role findings — `CKV_AWS_290`
and `CKV_AWS_355` on `module.base.aws_iam_role_policy.github_actions_deploy` — and nothing else. The
gate counts IAM findings not on that list; today that is **0** of 2 (454 IAM checks passed).

Accepting by ID *and* resource is the point: the same two rules firing on any other policy still
fail the job. The isolation policies have zero `Resource: "*"` and this is what keeps it that way.

**A stale acceptance warns; it does not fail.** This runs in the workflow that applies production
infrastructure, and blocking a deploy over gate bookkeeping is the wrong trade. The `.tf` enforce
list takes the opposite choice and can afford to — it runs on PRs and a weekly schedule, and blocks
nothing that ships.

## Both counts narrow *after* a pessimistic record

Each workflow records the **full** finding count into the gate's variable first, then overwrites it
with the narrowed one. It reads like a redundant write and is not: any path that skips the narrowing
step leaves the gate holding the full count, so it fails closed. The alternative — recording only
the narrowed count — turns a broken narrowing step into a comfortable zero.

## What still does not block, and why it is not an oversight

- **`npm audit`** — the gate has no severity threshold (`apply-gate.sh` fails on `> 0`), and the
  runtime scope carries two accepted `dompurify` advisories. Needs monaco to move, or a threshold in
  the shared script.
- **ZAP** — a count gate is wrong here; two Lows survive by decision. Gate by `riskcode >= 2` if at
  all.
