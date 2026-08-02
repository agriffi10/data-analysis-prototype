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
| SPA deps | `npm audit` (full) | 6 |
| Lambda deps | `pip-audit`, 13 packages | 0 |
| Repo | `gitleaks`, 357 commits / 9.5 MB | **0** |
| `infra/` | `checkov`, 224 resources | 305 failed / 439 passed / 0 parse errors |
| Deployed portal | OWASP ZAP baseline | not yet run — first execution is the weekly schedule |

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
| high | `react-router` | **runtime** | GHSA-chx6-hx7r-mcp5 — DoS via inefficient route matching | **fix** |
| high | `react-router` | runtime | GHSA-qwww-vcr4-c8h2 — RSC-mode CSRF bypass | **accept** — no RSC |
| medium | `react-router` | runtime | GHSA-337j-9hxr-rhxg — SSR hydration constructor injection | **accept** — no SSR |
| medium | `react-router` | runtime | GHSA-h8fp-f39c-q6mh — RSCErrorHandler XSS | **accept** — no RSC |
| medium | `react-router` | **runtime** | GHSA-wrjc-x8rr-h8h6 — open redirect via backslash in `<Link>`/`useNavigate` | **fix**, see below |
| medium | `dompurify` | runtime (via monaco) | GHSA-cmwh-pvxp-8882 — `ALLOWED_ATTR` pollution | **defer** |
| low | `dompurify` | runtime (via monaco) | GHSA-c2j3-45gr-mqc4, GHSA-vxr8-fq34-vvx9 | **defer** |
| high | `postcss` | build | GHSA-r28c-9q8g-f849 — path traversal via `sourceMappingURL` | **fix** (cheap) |
| high | `brace-expansion` | build | GHSA-mh99-v99m-4gvg — OOM via unbounded expansion | **fix** (cheap) |

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
- **`dompurify` is transitive through `monaco-editor`**, and npm's proposed fix is
  `monaco-editor@0.53.0` — a **downgrade**, flagged breaking. Deferred: the advisories concern
  `setConfig`/`clearConfig` poisoning APIs the portal never calls, and monaco is lazy-loaded on the
  Query route only (SPEC-035). Revisit when monaco ships a forward fix.
- **`postcss` and `brace-expansion` are build-time.** Both exploits need untrusted input — a
  hostile stylesheet, a hostile glob — and both inputs are this repo's own source. Real supply-chain
  hygiene, no runtime exposure. Both have non-breaking fixes, so they are cheap to clear.

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
| 5 | CKV_AWS_21 | S3 versioning | **FIX** — the strongest finding here. S3 has no atomic move, so rename/move is `CopyObject` + `DeleteObject` (architecture.md, Known Constraints). Without versioning a failure between those two steps is unrecoverable user data loss. |
| 5 | CKV_AWS_144 | Cross-region replication | **accept** — single-region system by design. |
| 5 | CKV_AWS_145 | S3 KMS CMK | **defer** — SSE-S3 today. |
| 5 | CKV_AWS_18 | S3 access logging | **defer** — cost vs. value; `logs/` already narrates control-plane activity. |
| 5 | CKV2_AWS_62 | S3 event notifications | **accept** — not applicable; the control planes are queue-driven. |
| 4 | CKV_AWS_284 | Step Functions X-Ray | **accept** — same reasoning as CKV_AWS_50. |
| 2 | CKV_AWS_300 | Abort incomplete multipart uploads | **FIX** — cheap lifecycle rule. Multipart upload is SPEC-020; an abandoned upload leaves orphaned parts that are billed and invisible. |
| 1 | CKV2_AWS_32 | CloudFront response headers policy | **FIX** — this is the CSP / HSTS / `X-Frame-Options` gap, and the one finding ZAP is most likely to report independently. Two scanners, one cause. |
| 1 | CKV_AWS_82 | Athena workgroup enforces configuration | **FIX** — cheap, and it stops a client overriding the result location or its encryption (SPEC-032/034). |
| 1 | CKV_AWS_68 | CloudFront WAF | **defer** — real cost, and this is a pre-production system. |
| 1 | CKV2_AWS_47 | WAF managed rules for Log4Shell | **accept** — follows from CKV_AWS_68; also no Java anywhere. |
| 1 | CKV_AWS_86 | CloudFront access logging | **defer** |
| 1 | CKV_AWS_174 | Viewer certificate TLS ≥ 1.2 | **accept** — the default CloudFront certificate already enforces this; the check fires because no custom cert is configured. |
| 1 | CKV2_AWS_42 | Custom SSL certificate | **accept** — no custom domain yet. |
| 1 | CKV_AWS_310 | Origin failover | **accept** — single S3 origin by design. |
| 1 | CKV_AWS_374 | Geo restriction | **accept** — no geographic access policy. |
| 1 | CKV2_AWS_61 | S3 lifecycle configuration | **defer** — subsumed by the CKV_AWS_300 work. |

**Five fixes fall out of this:** S3 versioning, the multipart-abort lifecycle rule, the CloudFront
response-headers policy, the Athena workgroup enforcement, and the two cheap npm bumps. None is
large; together they are a good first follow-up.

---

## Proposed blocking thresholds

What the follow-up spec should implement, per scanner.

| Scanner | Proposed gate | Rationale |
|---|---|---|
| `gitleaks` | **`block` immediately** | Already at zero. There is no cost to turning it on and no defensible reason to accept a committed secret. **Do this first.** |
| `pip-audit` | **`block` immediately** | Already at zero across 13 packages. Same argument. |
| Semgrep | `block` after excluding the Flask rule | One known false positive stands between here and zero. |
| `npm audit` (runtime) | `block` at **high** once `react-router` is bumped | The runtime scope is the one users are exposed to. Gate this scope only — never the combined count. |
| `npm audit` (full) | stay `report` | Build-time advisories should be visible, not blocking; they would gate PRs on unrelated toolchain churn. |
| Checkov | `block` only on an **explicit allow-list of check IDs** | 305 failures over 25 rules, most not applicable. Gating the total would mean suppressing 20 rules to enforce 5. Pick the five in the FIX rows, gate those by ID, leave the rest reporting. |
| ZAP | stay `report` | Unauthenticated surface only; findings are header hygiene, better fixed via CKV2_AWS_32 than gated on. |

Two of these — gitleaks and pip-audit — are at zero **today** and could be flipped in the same PR
that fixes the five Checkov items. That is the natural next change.


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

All six are one cause: the `lambda:*EventSourceMapping` statements use `Resource: "*"`.

**This is not a lazy wildcard.** `lambda:CreateEventSourceMapping` does not support resource-level
permissions — the mapping's UUID does not exist until it is created, so AWS requires `*`. It is an
instance of the "non-scopable actions" trap that `CLAUDE.md`'s infra rule already warns about, and
narrowing `Resource` is not available.

**The hardening that *is* available** is a condition key rather than a resource scope: constrain the
statements with `lambda:FunctionArn` so the deploy role can only attach event-source mappings to
this fleet's own functions. That is a small, well-scoped change, and it is the right follow-up —
but it touches the deploy role, so it wants its own PR and a careful plan review rather than being
bundled here.

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
