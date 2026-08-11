# S3 File Portal — Project Memory

Loaded every session — keep it lean. Deep docs live in `docs/` and are pulled **on demand**:
- `@docs/process.md` — how we work: spec lifecycle, session rhythm, completion ritual (read once)
- `@docs/architecture.md` — system design + Known Constraints (read the section you need, never in full)
- `@docs/decisions.md` — the Key Decisions register in full (the digest below is one line each)
- `@docs/specs/INDEX.md` — the spec index + status (one row per spec)
- `@docs/specs/ARCS.md` — why an arc exists / how its specs compose (only for the arc you're in)
- `@docs/specs/SPEC-XXX-*.md` — the spec you're implementing
- `@docs/component-inventory.md` — **router** to the per-area inventories; read only the area(s) you need
- `@docs/spec-delivery/SPEC-XXX-*.md` — what a past spec delivered (pull only when a dependency points to one)
- `@docs/best-practices/INDEX.md` — domain coding rulebooks (React, accessibility, …); route here, then load only the section(s) you need
- `@docs/transition_plan.md` — **single source of truth** for the client-environment transition (IdC federation, de-provisioning, Lake Formation re-keying); read before touching auth, provisioning or LF
- `@docs/lambda-rationale.md` — the long-form *why* behind `lambdas/` (sizing evidence, rejected designs, the traps); read the one entry for the area you're changing, never in full

**Context discipline:** these are pointers, not a reading list. Pull a doc when a task needs it.

---

## Project Overview

A web portal where authenticated users upload/download files to/from their own S3 prefix.
Auth is AWS Cognito (standalone User Pool + Identity Pool). **No backend** — the SPA calls
AWS directly with scoped credentials. Status: greenfield, no production users yet.

## Monorepo (npm workspaces)

- `apps/portal/` — React SPA (**all app code lives here**; paths below are relative to it)
- `infra/` — OpenTofu IaC (**all IaC paths relative to here**); bounded-context modules under `infra/modules/`
- `packages/` — reserved, currently empty
- `docs/` — architecture, specs, spec-delivery, templates

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite, TypeScript (strict), TailwindCSS; `focus-trap-react` (focus trapping for Modal/Drawer) |
| AWS | `@aws-sdk/client-s3` v3 (modular), `s3-request-presigner`, `lib-storage`; `aws-amplify` v6 for Cognito; `@aws-sdk/client-athena` + `@aws-sdk/client-glue` (analytics, SPEC-034); `@aws-sdk/client-sqs` (shared-space control plane, SPEC-051) |
| Editor | `@monaco-editor/react` + `monaco-editor` (self-hosted workers; lazy-loaded on the Query route only, SPEC-035) |
| Routing / state | `react-router` v8 (**not** `react-router-dom` — that package is gone in v8; import everything from `react-router`); TanStack Query (server state) + Context/`useReducer` (UI state); no Redux |
| Testing / lint | Vitest + React Testing Library + `@testing-library/user-event`; `@vitest/coverage-v8` (`npm run test:coverage`); `vitest-axe` (axe-core a11y assertions, SPEC-045); ESLint + Prettier. Tests are **integration-style** — render real hooks/children, mock only the AWS service boundary; shared harness `src/test/renderWithProviders.tsx`. Rules: `best-practices/react/react.md` §21 |
| IaC | OpenTofu (HCL, S3 remote state) |
| Security | `eslint-plugin-security` + `eslint-plugin-no-unsanitized` (in `npm run lint`, **blocking**); Semgrep / `npm audit` / `pip-audit` / gitleaks / Checkov / OWASP ZAP in `security.yml` (**report-only**, SPEC-138). Every scanner version-pinned — see the VERSIONS block and #311 |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS SDK: v3 modular only; instantiate clients in `src/lib/` (never in components); all S3 ops go through service files.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Vite env vars: prefix `VITE_`; document each in `apps/portal/.env.example`.
- **No verbose comments in `.ts`/`.tsx`/`.py` files.** JSDoc (TS/React) and docstrings (Python) are the primary source of context — expand those over adding narrative inline comments; comments are reserved for the non-obvious *why*, kept short. Detail: `best-practices/react/react.md` §19, `best-practices/python/python.md` §14.
- **`lambdas/` carries NO inline comments at all** (only `# noqa` / `# type: ignore` directives). Every module, class, method and function — public or `_private` — has a Google-style docstring: a one-line summary of what it does *and its context*, an optional short *why* paragraph, then `Args:` / `Returns:` / `Raises:`, each written out with `None.` when the section is empty. A module's constants are documented in its docstring's `Attributes:` block. Anything longer than a paragraph of reasoning goes in `@docs/lambda-rationale.md`, not the file. Format: `best-practices/python/python.md` §14.
- When writing/refactoring code in a domain with a rulebook (React, accessibility, …), consult `@docs/best-practices/INDEX.md` first and load only the relevant section(s) — don't reinvent or guess the rules.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
npm run format|format:check -w apps/portal   # Prettier (prettier.config.js); format:check gates CI before tests
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
```

## Specs

Status is authoritative in `@docs/specs/INDEX.md` (each spec file's header carries its own `Status`);
arc narrative is in `@docs/specs/ARCS.md`. **Keep the note below to what's live and not yet written
down elsewhere — when a spec closes, prune it rather than appending.**

**The table-share-at-scale arc (160 → 161) is COMPLETE (2026-08-10).** `cpcommon.transfer` is the
engine the other three arcs depend on, and **161 moved the ceiling**: caps re-sized, the cloned
definition behind a pointer, a top-level `TimeoutSeconds`. **Two live checks are now owed on this
plane, and they are one session** — 161's (a >20 GiB several-hundred-object share, an over-cap
refusal naming the count and cap, a `GetTable` read-back on a 100-column clone) and 160's SCALE
half below, which the same fixture serves. Script: `docs/testing/table-share-e2e.md` → *SPEC-161*.
**DISCHARGED: the Map Run `manifest.json` shape** — a real one is transcribed into
`test_transfer_cpcommon.py` and parsed by the shipped reader, settling that `ResultFiles` maps a
group name to `{Key, Size}` entries and that **`Key` is absolute, not prefix-relative**. **Still
owed: the SCALE half** — that run was one small batch, so share a **several-hundred-object** table
to two recipients where one conflicts: several child executions, the conflicting one refused with
`conflict` and **no child execution of its own**, the other receiving every object at the right key,
and `logs/service=table-share/` carrying one `batch copied` event per child. **Plane-wide, and now
mostly settled:** the `StartExecution` name contract is **verified against the deployed machine** —
idempotent while running, `ExecutionAlreadyExists` once closed. What remains inferred is only that
the Pipe's **v5 (deterministic) execution names** are derived *per message*; **a redrive cannot
settle that and should not be attempted** (see `architecture.md` → *Control Planes → The shared
pattern*, which records the working probe and why redrive is the wrong tool).

**The feature-flags arc (162 → 163) is COMPLETE and its live check is DISCHARGED (2026-08-11).**
Setting `environments.prod` to `{"query": false, "dataQuality": false}` hid both features in the
deployed app — tabs gone at desktop and in the 400px hamburger, `/query` on the unavailable page
rather than the 404, no "Create table" and no "Check quality", and neither guide in Help — and
**Publish Config restored it with no app build in either direction**. **That one observation
discharges 162's FR-009 and FR-007 too**: the fallback is all-on, so an app that CHANGES can only
have read the document successfully, and a `prod` block taking effect proves `VITE_ENVIRONMENT`
reached the bundle. **Two caveats worth carrying.** The override was applied to the published
object **by hand**, so the browser half is exercised and the *pipeline* half was confirmed
separately by a `workflow_dispatch` (run 31495622199) — a hand-edit also opens a **git↔bucket
drift** that the next `config/**` merge would silently overwrite, and the dispatch is the cheap way
to reconcile it. And `_config/` being unlistable in the file browser was **not** checked; IAM's
prefix-conditioned `ListBucket` is the mechanism and a test pins it, so the SPA lists are
belt-and-braces.

**The send-files arc: SPEC-164, 165 and 166 are COMPLETE (2026-08-11); 167 remains Draft.** The
fifth control plane now **delivers** — a request is proved legitimate, expanded into a copy plan,
guarded per recipient, copied by a top-level Distributed Map and attributed back. **It is still
silent: nobody is told anything until 167**, which adds the "Send to…" entry point, the dialog and
the notification producer. What 167 needs from 166: the terminal is `ShapeSummary`'s
`{requestId, sender, itemNames, objectCount, recipients[]}`, where each recipient carries
`{kind, name, status, reason, detail, failedItems}` — `detail` is the **colliding item name** on a
conflict, which is why the guard returns its expected refusals as records rather than raising (a
`TerminalError` cannot carry a name to a user). Its producer is the ONE notifier for every
per-recipient outcome; neither the guard nor the collector emits, deliberately.
**THREE live checks are owed and they are one session** — `docs/testing/file-send-e2e.md`,
*SPEC-164* checks 1–3, *SPEC-165* checks 4–6, and *SPEC-166* checks 7–10 (two recipients receive
every object at `shared_files/{sender}/…`, a repeat refuses **those** recipients naming the item
while a third still receives, the spans, and the IAM simulation). They must be real invocations: a
shared layer's import-time failure only shows at cold start (PR #196), a truncated listing returns
a plausible smaller number rather than an error, and **nothing offline proves the cross-bucket
`*/shared_files/*` write lands** — a simulation without `--resource-policy` returns `allowed` for a
`PutObject` the real call denies. **168→172** archive/restore
(a fifth bucket + a fifth plane; **`GLACIER`**, so restore is `RestoreObject` + a 3–5 h `Wait` loop +
a copy, not a copy; retention is a **7-year lifecycle ceiling, not Object Lock** — versioning is
deferred and compliance mode would block the restore's own cleanup; the archive bucket is
**browser-invisible** (no CORS, not in CSP, zero portal-role statements) and `archive/` is
**Deny**-written in both space buckets; **the source is deleted only when every object is confirmed
copied**, and a partial *archive* rolls back where a partial *restore* does not; the receipt is a
**report, not a record** — the archived key carries its own origin; keys are partitioned
`personal/`/`shared/` because **nothing checks a space name against the User Pool**). Narrative:
`@docs/specs/ARCS.md`.

The observability arc (127→137) is COMPLETE, and so are SPEC-140, 141, 142
and the **whole refresh arc (143, 144, 149, 145)** — the pipeline classifies the change, refuses an
un-opted-into removal, replaces the definition **in place** via `glue:UpdateTable`, and **145 gave it a
browser surface**: a **Refresh table** item in the Query rail, the always-unchecked removals opt-in, and
the `columns_removed` notification link that names the columns. The live checks below are now runnable
from the UI.

**The 2026-08-05 audit arc: 150→156 are COMPLETE, and SPEC-157 and 158 have landed.**
150 was browser+CI guardrails; 151 was the Python control planes, and it closed two defects that
reached users — a single-file data-quality check that profiled the whole parent folder (and could
return **`clean` over `rowCount: 0`** when a sibling shared the file's stem), and a partial shared-space
teardown that **freed the name with objects still under it**. Both are Phase-5 verified. **152 gave
every plane a `NotifyFailure`**, so "it just never came back" is no longer reachable. **153 closed ten
guards that passed by coincidence** and left **mypy report-only** as the next ratchet notch.
**That notch is now taken: mypy is BLOCKING over the five shared layers at zero** (2026-08-09),
so a type error there fails CI. Notch 3 — widen `files` to the verb packages, report-only again —
is recorded in `pyproject.toml`'s `[tool.mypy]` block, which is the only home of the ratchet path.
**154 closed the frontend journey gaps** — table share, sign-in/out, collision
resolution, upload-to-completion, pagination and the dev-unauth guard all now have a test that
performs them. **155 was the reuse-and-structure pass**: seven JSON readers behind one `s3Json`, eleven dialog chromes behind `FormDialog`, a `features/connections/` that ends `features/query/`'s career as an undeclared shared layer (with an **ESLint rule** holding the line), and `QueryWorkspace` 1770→727 / `FileBrowser` 1101→516. Five deliberate user-visible changes and the two residual layering inversions are in its delivery doc. **156 discharged the deliberate twins in `lambdas/`** — CAS, the message resolver, results location, the JWKS path, the SQS parser and the Athena runner each exist once on `cpcommon`.

**The username-directory arc (146 → 147 → 148) is COMPLETE and deployed, and SPEC-158 has landed on
top of it.** The daily builder publishes `_directory/usernames.json`; both `AddMembersDialog` and
`TableShareDialog` suggest existing usernames as you type, and neither blocks a name the directory
does not know. **158 made the suggestion source a prop** and gave the share dialog's *space* entry
its own source — the user's own shared spaces, from the connections cache the app already fetches.

**One live check is owed, and it is a single browser pass** (Safari): open **Add members** and
**Share table** signed in, at 400px and desktop. Confirm suggestions appear **under both share
kinds**, the list positions inside the panel, and several chips still leave the confirm control
reachable. **That one pass also discharges SPEC-146's last owed check** — suggestions only appear if
the portal role's SigV4 `GetObject` on the directory actually succeeds, so seeing one IS the
end-to-end read confirmation. (158 itself owes nothing live: it makes no AWS call.)

Three things the arc left worth carrying:
- **A `rate()` EventBridge rule fires on creation**, so a new singleton's first scheduled invocation
  can hit the placeholder zip before `Deploy Lambdas` lands. The async retry fixes it; a red first
  invocation is expected, not a defect.
- **The deploy role is GitHub-OIDC-only and the local CLI identity is an IAM *user*** that is not on
  the user-space bucket-policy allowlist — so `get-object`/`list-objects-v2` on that bucket return
  `AccessDenied` from a laptop. That is the isolation working, not a fault.
- **`stopPropagation` from a React handler DOES stop `useEscapeKey`'s `document` listener** (React
  delegates below it), settled by measurement in 147. The hook needed no `defaultPrevented` guard and
  **did not get one**. Don't re-open it.

What remains below is the live checks that are owed.

- **SPEC-141 left two things live.** (1) Its single `--delete` is scoped to `assets/`, so
  **stale root-level objects are never removed**. That orphan class is a **spec choice, not a CLI
  constraint** (see the decisions entry). `icons.svg`, the first such orphan, was **removed by hand
  2026-08-05** (`aws s3 rm` + a targeted invalidation); the class remains, so the next one needs the
  same treatment. **Do not verify such a removal by status code** — this distribution maps
  `403/404 → /index.html` with a **200** for client-side routing, so a deleted asset still answers
  200. Check `content-type` and `x-cache: Error from cloudfront` instead. (2) **DISCHARGED
  (2026-08-07): the delete pass deleted for the first time.** SPEC-155's merge (run 31142729286) was
  the first deploy to change bundle hashes, and `Reconcile deletions` removed exactly **5** superseded
  chunks — `index`, `QueryPage`, `ConnectionsPage`, `shared-spaces`, `CollapsibleRail` — **every one
  under `assets/`, none at the root**, which is the prefix scoping working rather than a lucky diff.
  The pass is now exercised, not merely configured.
- **SPEC-138's follow-up is now BUILT: four of six scanners block (2026-08-09).**
  `docs/security-baseline.md` has every finding with a disposition, and its threshold table is now a
  record rather than a proposal. `gitleaks` + `pip-audit` went `block` at zero (2026-08-02);
  **Semgrep** and **Checkov** joined them. **`react-router` is on 8.3.0 (2026-08-05) —
  every one of its advisories is now cleared**, including the RSC-mode survivor that had been accepted
  as inapplicable; the v8 major was a package rename (`react-router-dom` is gone) and nothing else.
  **`npm audit --omit=dev` now reports NO highs.** The build-time `postcss` /
  `brace-expansion` advisories are **fixed (2026-08-03)** — both resolved by `npm update` inside the
  existing caret ranges, no `package.json` change and no `overrides` needed. **Both Checkov "FIX" rows
  are closed:** multipart-abort shipped 2026-08-05, and the Athena workgroup was **re-dispositioned to
  accept** — enforcing workgroup configuration would force every query to the workgroup default (the
  admin-only bucket) and break per-user results. **S3 versioning is deferred by decision
  (2026-08-03)** — pre-production, no real user data. Revisit before any real data lands, because the
  exposure it covers is unrecoverable loss on a failed `CopyObject`+`DeleteObject`. **ZAP now stands at
  13 alerts (1 Medium, 2 Low, 10 Info), down from 20**, every remaining non-Info row accepted with
  reasoning in `security-baseline.md`. Its first scheduled run went red for a **workflow** reason with
  no security content (a duplicate `-J` broke the action's report read-back, outside the
  `fail_action` guard — #327): a scanner that ran can still read as broken, the mirror of this file's
  "did not run is never clean" rule.
- **SPEC-139 closed the IAM blind spot, and the isolation model came back clean.** 431 IAM checks
  against 55 resources on the rendered plan; `portal-role-permissions` has zero `Resource: "*"`.
  **The event-source-mapping findings are fixed (2026-08-02):** the DLQ drain's grant was dead
  permission (SPEC-126 replaced the mappings with a schedule) and was deleted; the notifications grant
  is now condition-scoped on `lambda:FunctionArn`. **IAM findings 6 → 2.** The 2 that remain are
  permanent — CloudFront/Cognito creation and Lake Formation account-level actions have no ARN before
  the resource exists and no applicable condition key — so **`GATE_CHECKOV_PLAN` can never be a blanket
  `block`**; gate by check ID + resource instead. That fix also caused a deploy-role lockout; see the
  refresh-deadlock line in Key Decisions.

- **SPEC-137 shipped half of FR-005 and broke sign-up for nine days (fixed 2026-08-01, PR #317).**
  The instrumented code landed; the `cpcommon` layer attachment, `LOGS_QUEUE_URL` and the producer
  IAM did not — so all three singleton Lambdas raised `ModuleNotFoundError` at cold start, and on
  `pre-signup` that is a Cognito trigger. **Every gate was blind**: `conftest.py` puts the layer on
  `sys.path`, `update-function-code` succeeds against a function that cannot import, and the
  instrumentation harness was *satisfied by* the unresolvable import. `lambdas/test_deploy_matrix.py`
  now joins the deploy matrix against what each function imports — **the check that the code/infra
  split needs and had nowhere else.** Full account: the Correction section of 137's delivery doc.
  **Still owed live: 137's Phase 4** — sign up one test user, confirm the trigger succeeds and
  `logs/service=auth/` carries both spans.
- **DISCHARGED (2026-08-03): the data-quality live run.** A real check was run end to end from the
  UI, clearing what **114** (`reportKey` seeding), **123** (the index CAS), **128** (`request_id` as
  the join key), **129** (the append at real volume) and **132's Phase 4** all owed.
- **Still owed live:** **125**'s shared-space smoke run (create → add-member → leave → delete; a
  shared layer's import-time `_require` fails at **cold start**, PR #196 — **134's narrative makes
  that run far more legible**, and the two should be done together), and **133's Phase 5**: a
  malformed message on one request DLQ, confirming the user is notified, the message is gone, and
  the redacted body is in `logs/service=dlq-drain/`. That discharges **126**'s owed malformed-body
  check too.
- **SETTLED (2026-07-23) — the no-file-contents rule is about FIELDS; `error.stack` is exempt.**
  `log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span, walking
  the `__cause__` chain — so a polars parse error quoting a user's cell reaches `error.stack` in
  `logs/`. **Accepted rather than stripped** (user decision): `logs/` is admin-only, the absolute
  rule binds the values a call site *chooses* to emit, and a stack is diagnostic metadata that
  admins reading a failed run need. Do **not** conclude from a stack trace that the field rule is
  loose — a verb still may never put file contents in a **field**. Pinned by
  `test_ACCEPTED_the_span_error_stack_may_carry_file_contents` (data-quality inspect-source): if it
  starts *failing*, `log-foundry` began stripping stacks and this decision should be revisited, not
  the test deleted. Full reasoning: `decisions.md`.
- **The refresh arc owes TWO live checks — run them from the UI now (145 shipped), not by hand-crafted SQS.**
  (1) **FR-010's sequence:** build a table from a CSV folder, add a file with a new column, refresh
  and confirm it appears; remove a column, refresh and confirm the block, its **named columns** and
  the notification link; then refresh with the opt-in and confirm the column is gone. Run it against
  a **partitioned** table too — FR-005's reconstruction is unit-tested against fixtures built from
  the same renderer it re-renders through, so only a table the pipeline did not write tests the
  assumption rather than the arithmetic. (2) **149's preservation check:** refresh a table carrying a
  `Description` and a column comment, then `GetTable` — both survive, the columns changed, and
  `get-table-versions` shows a previous version. Fold the casing read-back into it. **While you have
  that response, paste it verbatim** as SPEC-153's owed foreign projection fixture (FR-006 AC2 shipped
  a docs-transcribed stand-in because LF filters the local CLI principal's catalog to empty). SPEC-137 is the
  precedent for why these matter: instrumented code shipped whose layer attachment was missing, and
  every gate was blind to it. **149's policy simulation is DISCHARGED against the DEPLOYED role**
  (2026-08-04, post-apply): `glue:UpdateTable` allowed, `glue:DeleteTable` **implicitDeny**,
  `s3:DeleteObject` explicitDeny in all three buckets. Note the admin bucket is
  `dat-prod-athena-admin` — a wrong resource ARN returns **implicitDeny**, which reads like a pass
  and is really "your ARN matched no statement". **The casing premise is CORROBORATED, NOT
  DISCHARGED** — AWS documents that Athena
  lowercases every column name it creates through DDL, which is strong and is why 149 hard-codes the
  fold, but documentation is the same class of evidence that had SPEC-144 FR-001 reversed mid-build,
  and 149 raised the stakes: the fold is now OURS. If the premise is wrong, the first refresh of an
  existing table silently re-cases its columns while `diff-schema` calls them unchanged — a mutation
  no test and no notification would report. Settle it with the `GetTable` read-back in check (2).
- **SPEC-157 closed the concurrent-refresh race and owes ONE live check.** Submit two refreshes of
  one table in quick succession from the UI: one succeeds, the other produces the
  `refresh_already_running` notification, and both runs appear in `logs/service=table-builder/`.
  **Nothing that runs today proves two real executions serialize** — the unit tests simulate
  contention with a pinned read. Its **IAM simulation is DISCHARGED against the DEPLOYED role**
  (2026-08-09): `PutObject`/`GetObject` allowed under `locks/table-builder/`, `DeleteObject`
  **explicitDeny** there, `PutObject` **implicitDeny** elsewhere in the admin bucket — each with an
  `allowed` control beside it, because an `implicitDeny` alone cannot tell an ungranted action from
  a wrong ARN.
- **SPEC-142's `"$path"` premise is CONFIRMED; its disagreeing-files check is still owed.**
  SPEC-151's Phase 5 (2026-08-05) settled the assumption underneath the fix — a single-file check's
  `"$path"` predicate demonstrably matched, so Athena's pseudo-column does return the
  `s3://bucket/key` form the manifest is keyed to. What was **never run** is 142's own scenario: a
  check over a folder whose files deliberately **disagree** (expect the cross-file finding and **no**
  ragged count), and one whose files agree (expect the same numbers as before). Do not read the
  premise being settled as the check being done.
- **SPEC-151 left two things owed, and neither is a blocker.** (1) **FR-006's escaping is asserted at
  RENDER time only** — a data-quality check over a folder whose partition segment contains `'` was
  not run, so Athena's acceptance of the backslash-escaped form is corroborated, not demonstrated;
  if such a folder ever still fails, suspect the engine before the renderer. (2) **FR-003's failure
  direction** — only a successful teardown was exercised; a denied key cannot be staged from the UI,
  so the raise path is unit-tested only.

---

## Key Decisions (settled — don't re-litigate)

One line each. **Full reasoning + the "do NOT build" fences: `@docs/decisions.md`** — read the entry
before working in that area; the line here is a reminder, not the spec.

- **Auth:** Cognito User Pool → Identity Pool (ABAC); `username` principal tag stamped server-side from the verified claim (unspoofable). One shared role; isolation via `${aws:PrincipalTag/username}`. (SPEC-011)
- **Hosted UI = Managed Login v2** (`managed_login_version = 2`); classic Hosted UI broke the post-signup redirect. CI re-ensures default branding post-apply.
- **No backend:** browser → AWS direct. Cognito trigger Lambdas allowed (service config, not an API).
- **State:** TanStack Query = server state; Context+`useReducer` = UI state. No Redux. (SPEC-015)
- **File ops = filesystem UX;** S3 has no move/rename → `CopyObject`+`DeleteObject`, folder ops recursive + non-atomic, collisions warn-and-confirm. (architecture.md Known Constraints)
- **Analytics (032→036):** in-app Athena/Glue/LF workspace; isolation = `username` principal tag on the Glue DB ARN (DB name = username), **not** LF-Tags.
- **Usernames** = S3 prefix = principal tag = Glue DB name; catalog-safe `^[a-z][a-z0-9_]{2,62}$` (SPEC-033).
- **Query workspace has NO active database** (SPEC-077, supersedes 047/076): every base table is fully-qualified `database.table`; rail is browse-only.
- **Multi-statement scripts (078):** client-side `;` split, sequential stop-on-first-failure, 3 run scopes (⌘⏎ / ⌘⇧⏎ / ⌘⌥⏎). No transactions.
- **Bucket 2 (shared-space):** privileged async control plane (FIFO SQS → Pipe → SFN → single-task verb Lambdas + `cpcommon` **and** a domain-only `shared-space-common` layer since SPEC-125, one shared `orchestrator` role). Create is creator-only. Record: `architecture.md` → *Control Planes → Shared Spaces*.
- **Member join status (073):** 7th verb `acknowledge-membership` flips pending→active; display/bookkeeping only, access granted at add time.
- **Member roster (075):** reverses 053 — every member sees a read-only roster; `cache.write_roster_to_all` fans out on add/remove/leave.
- **Table Builder (066→072):** dedicated control plane (5 linear verbs, one role, `tbcommon` + `polars` layers). Partition keys are **user-declared** + Athena partition projection. CSV all-string. Record: `architecture.md` → *Control Planes → Table Builder*.
- **Table Share (088→094):** dedicated control plane w/ recipient `Map`; **clone** the source Glue table def, never re-infer; push (no consent). Record: `architecture.md` → *Control Planes → Table Share*.
- **The copy is a top-level Distributed Map and attribution is a verb (160, supersedes 091's per-recipient copy):** a `(recipient × object)` JSONL manifest, batched into `cpcommon.transfer` (the engine, because send-files and archive are callers two and three); **not nested** in the recipient Map, and **S3 Batch Ops is rejected on the API, not deferred**. `ToleratedFailurePercentage: 100` + `STANDARD` children; a deterministic item failure **succeeds** its batch (so `collect-transfer-results` must read `SUCCEEDED_n` **and** `FAILED_n`/`PENDING_n` — a FAILED-only collector reports universal success over an incomplete dataset), an omitted payload is **unattributable ⇒ whole-request failure**, and **one failed item ⇒ no table**. The manifest key is **execution-unique** where the copy plan deliberately is not. The Map's `states:`/S3 grants belong to the **state-machine role** — on the execution role it renders, applies and unit-tests green, then `AccessDenied`s at the `ItemReader`. **Caps unchanged**; 161 moves them.
- **Everything unbounded on the state travels by pointer, and a cap is not a substitute (161, extending 090/160):** the cloned definition joins the object list and the manifest in the admin bucket (`definitionKey` → `table-share/{hash}/definition.json`, one module owning all three key layouts, **no IAM change**). Inline, `SHARE_MAX_DEFINITION_BYTES` had to choose between the 256 KB payload and a 100-column commented table — it survives at **64 KiB** bounding **Athena's 262,144-byte query-string quota** instead (the rendered DDL can be **2×** the JSON, and a quote-heavy *table property* expands far more than a *comment* — 128 KiB measured 99.98% of the quota). Plan and definition are **pure functions of the request**; only the manifest is execution-unique. An unreadable definition fails **that recipient** (`definition_unreadable`) and never renders — an empty column list makes a CREATE Athena *accepts*, over real data, that returns nothing.
- **Caps name the limit that sized them, and each one is COMPUTED by a test (161):** `SHARE_MAX_OBJECTS` **20,000** (listing time), `SHARE_MAX_TOTAL_BYTES` **1 TiB** (one copy of the *source* — it says nothing about the Map Run), `SHARE_MAX_OBJECT_BYTES` **10 GiB**, and two product caps the per-source ones cannot express because every manifest item is a full copy: `SHARE_MAX_TRANSFER_ITEMS` **20,000** and `SHARE_MAX_TRANSFER_BYTES` **3 TiB**, both on the **requested** recipient count, before the guard. `MAX_ITEMS_PER_BATCH` **50 → 8 = `COPY_CONCURRENCY`**, because a batch costs `ceil(items/workers)` **rounds of its slowest object** — a makespan, not bytes over a rate. `SHARE_MAX_RECIPIENTS` (50) unchanged; the two manifest verbs 60s/512MB → **300s/2048MB**. **Four review rounds each found a bound measured against the wrong quantity** — read the `decisions.md` entry before touching any of these numbers.
- **`TimeoutSeconds` 10,800 is TOP-LEVEL, and it cannot notify on its own (161):** without it a Standard workflow runs a **year**; with it, AWS catchers still **don't cover top-level execution failures**, so it ships with an **EventBridge `TIMED_OUT` rule** (never `FAILED`, or every caught failure double-notifies) invoking the same verb through a second door, which takes the actor from the **token in the execution input**, expiry unenforced. Sized against `SHARE_MAX_TRANSFER_BYTES` at a **makespan** rate (500 MB/s, not an aggregate 4 GB/s), minus the guard Map, finish Map and serial verbs. Retention (30 d) clears the ceiling **240×**, so FR-004 needed **no lifecycle rule**.
- **An expected refusal is a RETURN VALUE, and a conflict is per item NAME (166):** the guard returns `{status, recipient, reason, detail}` for the two refusals it expects and keeps its `Catch` for unpredicted faults — because FR-001 needs the **colliding item named** and a `TerminalError` cannot carry one (tokens are kept out of the message, `detail` is operator text SPEC-106 forbids rendering). The inbox is read with **one delimited listing**, never a probe per item: `/` is not the lowest byte a key may carry, so a `MaxKeys=1` probe returns `notes.txt-old` and reads "clear" over an occupied destination. A name is a name whatever it holds. **Neither the guard nor the collector notifies** — every per-recipient outcome is told once, from the terminal summary, by 167's producer. Two **fail-open** holes were found in review and closed (an empty selection cleared everybody; an absent `transfer` block reported universal success with no S3 call at all); the guard's **TOCTOU is not closed**, as table-share's is not.
- **The three transfer caps are each measured against a DIFFERENT budget (166):** `SEND_MAX_OBJECT_BYTES` **10 GiB** against `COPY_TIMEOUT_SECONDS` (a batch is one round of the pool and **one object is one worker** — its absence made every distributed model a half-truth, at 43,980s for one 1 TiB object), `SEND_MAX_TRANSFER_ITEMS` **50,000** against the memory the two verbs either side of the Map hold the manifest in (read back **from `locals.tf`**), `SEND_MAX_TRANSFER_BYTES` **3 TiB** against the machine's ceiling at the **makespan** rate. Both product caps are measured on the **requested** recipient count, before the guard. The items cap **deliberately diverges** from table-share's 20,000 — that plane's equals its object cap, so at full size it permits one recipient.
- **The ceiling ships WITH its rule, and this plane's door needs a fallback (166):** `TimeoutSeconds` **10,800** top-level, plus an EventBridge `TIMED_OUT` rule (never `FAILED`), `fs_notify_failure`'s second door, its 15s→60s raise and the deploy-role `events:` grant — catchers do not cover top-level execution failures. **EventBridge drops an input this plane's own cap allows to approach 200 KB**, so the door reads it back with `states:DescribeExecution` on the **Lambda** role; table-share needs no such fallback and inheriting its shape would have left FR-005 half-delivered. **The seed that reports all this must not carry the request twice**: `RequestFailureSeed` supplies `$.raw` and **not** `$.source` — together ~300 KB, `States.DataLimitExceeded` on a Pass with no Catch, killing the run before `NotifyFailure`.
- **Data-quality report view (113):** `/data-quality/:space/:requestId` — space is **in the route, not derived**; own username wins; unreachable space renders denied and issues **no S3 request** (no existence oracle).
- **Data-quality runs index (123):** the `/data-quality` list is backed by a per-space `index.json` appended under **ETag CAS** (S3 lists lexicographically, so a UUID key gives no chronology); capped at 200, every failure swallowed — report → notification → index, most durable to least. No new IAM.
- **Data-quality notifications (114):** the notification **is** the completion channel and must carry the report link (the reports folder is hidden); the link builder mirrors 113's precedence and mints **nothing** where the view would resolve wrong. One dedup token per *outcome*, not per verb. FR-005's alarms were **removed** → **SPEC-126**.
- **Control-plane DLQ drain (126):** one shared Lambda **sweeps** all four request DLQs on a **10-min EventBridge schedule** and turns each dead-lettered request into a user notification — recipient from the **verified token**, **nothing from the untrusted body** in the message, and it **deletes every message it reads** (nothing redelivers). The **notifications DLQ stays undrained** (circular). No redrive, no alarms.
- **Structured logging (127→137):** `cpcommon.observability` is the **only** door to `log_foundry`; the logs queue is **FIFO** (`message_group_id` = service), **swept every 10 min, never long-polled**; layout `logs/service={s}/year=/month=/day=/data.jsonl` appended under **ETag CAS**, retained **forever**; `@traced` outermost, above `@notifies_on_failure`; messages are **literals**, `echo=` prohibited repo-wide. **The field rule — user metadata in, file contents out, tokens/emails always out — read its `decisions.md` entry before instrumenting any call site.** Four register entries: *pipe (127→129)*, *narrative primitives (130/131)*, *the field rule (130)*, *per-plane rules (132→137)*.
- **Control-plane table creation = TBAC (070/111 correction):** LF **admin does NOT grant `CREATE_TABLE`**. A `portal-managed` LF-Tag on every DB + one tag-policy grant per execution role + static per-bucket `DATA_LOCATION_ACCESS`. (Distinct from the per-user isolation tag.)
- **No ASL state decodes an error Cause (#252, control-plane-wide):** `States.StringToJson($.error.Cause)` raises `States.Runtime`, **uncatchable anywhere**. Carry raw `$.error`; decode via `cpcommon.errors.failure_reason`.
- **IaC:** OpenTofu; `infra/modules/` bounded-context; IAM policies are `.tftpl` rendered with `templatefile()`.
- **Dev-unauth path:** `VITE_S3_DEV_UNAUTH=true` = read-only test bucket, local only.
- **Notifications (058→061):** per-user inbox JSON; **single-writer** FIFO SQS → writer Lambda (no Pipe/SFN); browser only reads + enqueues; anti-spoof via verified ID-token claim. Optional `link` gated by `isSafeInAppPath`.
- **Responsive (095):** mobile-first, only `tablet:` (≥900) / `desktop:` (≥1300) compile; reflow on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); `useIsMobile` for mount-gating only, never styling.
- **Help & guides (074):** `/help` page from static code-grounded `helpContent.ts`; document only shipped, wired-end-to-end behavior.
- **User-facing error messaging (106):** raw AWS/Cognito/Athena text is **never** shown; `lib/errorMessages.ts` `toUserMessage` is the single source of wording — never render `error.message`.
- **Response headers / CSP (140):** one response-headers policy on the distribution = enforcing CSP + the full header set, `Server` stripped; CSP built from **variables** (root locals, never module outputs); `connect-src` **is** the app's network surface — enumerate it from the **hosts the app fetches**, not the AWS services it uses (the omitted Hosted UI domain broke fresh sign-in for a day; the code exchange is a `fetch`, not a navigation). **A report-only pass proves nothing about enforcement, and a signed-in pass never tests sign-in.** **Report-only first, always**; verify with a **same-origin page script + a negative control** (CDP eval bypasses page CSP). COEP and Monaco's `style-src 'unsafe-inline'` accepted; `preload` is on but inert — **never submit this `*.cloudfront.net` domain** to hstspreload.org. **Diff findings per check ID, never by total.**
- **Removing a column needs an opt-in, and the refusal IS the warning (144):** a refresh that would drop a column changes **nothing** and fails `columns_removed`, naming them; the user re-submits with `allowRemovals` (validated not coerced, persisted **nowhere**). The notification **link** is the only channel that names them to the browser — its column names are **percent-encoded and must NOT be re-validated as identifiers**, because column names are *not* catalog-safe. Column matching **folds case** — AWS documents that Athena lowercases every column name it creates through DDL.
- **The refresh apply replaces the definition IN PLACE (149, supersedes 144's apply):** one `glue:UpdateTable`, a **read-modify-write on the live table** — `UpdateTable` replaces the WHOLE definition, so building the input from SPEC-143's capture would CLEAR `Description`/`Owner`. The `TableInput` is an **allowlist projection** pinned against botocore; column names are **lowercased on write** (this path bypasses Athena's fold); `portal.managed` goes through `ddl.mark_managed`, never named in a verb. **`glue:DeleteTable` was REMOVED** — no verb here deletes a table. No window, no metadata loss, and the "committed drop then silence" exposure is retired; the **concurrent-refresh race is reduced, NOT closed** — Glue offers no compare-and-set on `UpdateTable`.
- **A per-table lock serializes refresh (157, supersedes 149's "reduced, NOT closed"):** an admin-bucket object under `locks/table-builder/`, claimed under **ETag CAS**; the loser is **refused with a notification**, never queued. Releases by **overwriting** — the role's `Deny s3:DeleteObject` makes "free" a *state*, not an absence. The holder is the **execution ARN** (a request id identifies the *message*, and Pipes delivery is at-least-once), stamped by a **Pass** state because reading `$$` in the task's own `Parameters` wraps the payload and every notify path reads the request at the **top level**. A stale lock is stealable only because the machine now has a **`TimeoutSeconds`** — a **top-level ASL field**, not a resource argument. `REQUEST_RESPONSE` on the Pipe is **impossible** for a STANDARD machine and EXPRESS is rejected twice over. `apply-refresh`'s freshness guard **narrows, does not close** the window — and it judges on the **columns as well as the stamp**, or a retry after its own committed write blames a phantom writer.
- **Refresh eligibility = shape, not marker (143):** a refresh is judged by what Glue reports (`cpcommon.glue.clone_definition`, moved from `tscommon`), **never** by the `portal.managed` TBLPROPERTY it also starts writing — pre-143 tables lack it and users can set it; a test forbids any verb reading it. Reconstructed partition keys must **round-trip through the create path's renderer AND match the live column type**; a reconstruction that can't be performed is a **refusal, not a guess**. A `Choice` on an **absent** path raises uncatchable `States.Runtime` — `Default` does not cover it, so guard with `IsPresent`. `portal.managed` (table property, dotted) ≠ `portal-managed` (LF tag on databases, hyphenated).
- **Username directory source = S3, not Cognito (146):** the daily builder enumerates the user-space bucket's top-level common prefixes and makes **no Cognito call** (a test enforces it) — today Cognito is complete and S3 is not, but the transition reverses that (`ensurePrefixMarker` is deleted, `cognito:username` becomes synthetic `identitycenter_<subject>`). **No Cognito union "to be safe."** The document is **advisory**: never an authorization input, every existence check stays `admin_get_user`, and a tripwire test enforces that too.
- **No shared-space directory is published (158):** the share dialog suggests only the spaces the user already belongs to, from `useConnections` — a full list would be strictly more useful (membership is not required to share) and is **declined** as a disclosure with no equivalent; an unlisted space stays typeable, and the suggestion source is now a **prop** (`SuggestionSource`), not a hook the combobox reaches for.
- **A feature flag is presentation, never authorization — and it lives beside the username directory (162):** `_config/feature-flags.json` in the **user-space** bucket (one `s3:GetObject`, no `ListBucket` widening, no write, **no** deploy-role/CORS/CSP/bucket-policy change); the admin bucket was specced first and **moved before any code**, because its grant would not have worked. A test forbids any `*.service.ts` or `lib/` module importing the flags — **verified against a deliberate violation**, not trusted. An unusable document falls back to **all-on and silently**, accepting that during an outage a deliberate "off" does not apply; that silence is why FR-009 exists — a blocked read renders *identically* to a healthy environment, so the live check's pass condition is a **200 in the network panel**, never "the app looks right". Wrong **version/shape** is refused whole; one bad **value** falls back for that key only. The validator **reads the publish workflow's matrix** (a list handed in would compare a copy of the answer with itself), and the publish is **one exact key** — `_directory/` is one prefix over. **"It already works" about CORS, `connect-src` and the bucket-policy allowlist is asserted, not assumed**; a failure there is a finding, not a licence to widen infra.
- **Gating is by REGISTRY, not per-component opt-in (163):** `GATED_SURFACES` names all 27 gated surfaces by **accessible name** and one test walks each **in both states** — because the tabs are the easy part and "Create table" is a *Query* feature on a *file-browser* toolbar. Reach-recipes live in the **test**, the registry stays declarative, and a guard equates the two sets. **One door, enforced by a tripwire**: nothing outside `features/feature-flags/` may even name `useFeatureFlags` (`useFeature` / `FeatureGate` / `useFeatureSet`). Hidden means **removed** — never `hidden`, never disabled, and the share dialog renders **no** kind toggle rather than a one-option one. A gated route **keeps its path and swaps its element** (falling through to `*` would call a correct URL wrong); it renders `LoadingState` while resolving because the page must **not mount** — an optimistic render makes the DQ report route an existence oracle. `components/` still imports no feature: the nav takes a **required predicate** from `Header`. `?space=` is **not read** with the flag off (never routed through `fellBack`, whose banner would be a lie), and shared databases in the Query rail were **added to the contract** but filtered **at the view** — a saved query on a hidden database still runs. **A recipe that re-implements the gate proves nothing** — two rows did, and deleting both real gates left the suite green (measured); recipes render the **real page**. **The off-half must assert AFTER settling**, never inside `waitFor`, whose first attempt lands while every surface is legitimately absent. **`useFeatureFlags` has THREE auth states**: settled-with-no-user is `'fallback'`, not `'loading'` — collapsing them made the dev-unauth path a permanent spinner. **Test harness:** `renderWithProviders` seeds flags all-on, and `setQueryDefaults` **before** `setQueryData` is load-bearing (`gcTime: 0` evicts an observer-less seed, so a control mounting after a click reads as off).
- **File-send is its own plane, and its front door is bounded by a CHAIN (164):** its own queue/DLQ/Pipe/machine/role + `fscommon` — the two features share `cpcommon.transfer` and nothing else, and one DLQ under both would let a malformed send dead-letter someone's table share. The envelope is **flat** (`actor` = the raw token, top level) because SPEC-126's drain reads and **redacts** that field flatly — nested, a dead-lettered send notifies nobody *and* writes the JWT to CloudWatch. Source authorization is the **space's** status (`is_active_member`), never the member's join chip — the other reading reverses SPEC-073. Containment is **three** rules: normalised root (`alice2/`), `.`/`..` **segments**, and a folder that **CONTAINS** `athenaresults/` (selecting the space root passes the first two, and 165 expands by prefix — folder keys are normalised to a trailing slash for the same reason). **Two caps, and the byte one is bounded by a chain:** a count cap cannot bound bytes (a control char escapes to six), and a byte cap measured against the *state* still permits a request the Pipe cannot start — its record re-escapes the body into `StartExecution`'s own 256 KB limit. The failure seed reads `$$.Execution.Input`; threading the request through the state was tried and **rejected** (it doubles the payload for the whole run). **FR-006: the user-space bucket-policy allowlist is hand-maintained — an explicit Deny beats an identity Allow, and a missing plane half-works.**
- **A received file lands in `shared_files/{sender}/`, built by ONE function (165):** the layout a recipient sees forever — `{targetRoot}shared_files/{sender}/{item}[/{relKey}]`, mirroring `shared_tables/`, independent of the sender's own folder depth. Keying by **item name** forces two refusals (an **overlapping** selection, and two items whose names would collide) where a **repeat** collapses; the destination tests can only prove the ONE builder right, so an **AST sweep** forbids a second — exempting docstrings and the declaration **by node identity**, because skipping the `Expr` and not its `Constant` child flagged two docstrings.
- **The exclusion rule is anchored at the SPACE ROOT, and reuse would have dropped files silently (165):** `is_ignored`'s rules anchor at the **listing prefix**, which here is whichever item the user picked — so sending `alice/reports/` would have dropped a user-made `reports/athenaresults/` (SPEC-164 records it as sendable) and any `_drafts/`, with no refusal. `list_data_objects` took an optional **`ignore` predicate** rather than a fork: the pagination genuinely is shared and is what a fixture proves least. **`user_settings/` is excluded too and is NOT in the spec's list** — narrowing an exclusion set is a decision, and at the root it costs zero false positives. The exclusions apply to a selected **file** as well as to a listing (nothing upstream filters a file item). A genuinely empty **file** is sent; a **placeholder** (zero bytes, trailing slash) is not, so an **empty subfolder does not survive a send**.
- **A duplicate is `(kind, key)`, never the key alone (165):** validate-authorize normalises a *folder* key to a trailing slash and leaves a *file* key untouched, so one key can arrive with two kinds — collapsing on the key sent a zero-byte placeholder and **none of the folder's contents**, reporting success, with the outcome depending on list order. Found in review; the silent drop arrived through the one part of FR-002 that was meant to be safe.
- **The expansion caps are memory and makespan, and both obvious models are wrong (165):** `SEND_MAX_OBJECTS` **20,000** is sized by the **plan held in memory** (~45 MB, peaking ~135 MB) against `locals.tf`'s 1024 MB **which the test reads back**; its timeout twin is **per-ITEM, not per-page** — a `file` costs its own *serial* HeadObject, so 200 files is 200 round trips where 20,000 objects is 20. `SEND_MAX_TOTAL_BYTES` **1 TiB** is a **makespan** at 500 MB/s, never the aggregate 4 GB/s. The per-object and recipient-product caps are **deferred to 166 with the `TimeoutSeconds` they are measured against**, and **both** carry a `hasattr` tripwire that fails when the cap arrives — the per-object one matters most, because the makespan test certifies the **distributed** case only and one 1 TiB object is one worker at 25 MB/s = **43,980 s**, four times over the ceiling.
- **A post-identity failure needs its OWN seed, and the fleet guard cannot see it (165):** `RecordFailure` reads `$.raw`, which exists on **no** post-validate state, so a catch routed straight to it — as every other plane's are — raises an uncatchable `States.Runtime` **before** `NotifyFailure`. The fleet guard identifies a seed structurally by `error.$ == "$"` and misses the `ResultPath` shape (`"$.error"`); widening it fleet-wide was **rejected as out of scope**, and the plane's own walk derives from the machine what SFN leaves on the state at each catch. Its **first version passed vacuously** on the exact mutation it existed for.
- **An unreadable settings document is quarantined, never deleted and never overwritten (159):** a `user_settings/` read-modify-write that cannot read the live body copies it aside (`{key}.unreadable-{ISO basic UTC}-{token}.json`, same prefix ⇒ **no IAM change**) and only then writes; a failed copy **refuses**, never silently overwrites. A **newer** schema is refused untouched — quarantining it would be the downgrade the fix exists to prevent — so the parse is **three-way**, version checked **before** shape. The key's **random token is load-bearing**: a clock-only key lets a racing quarantine copy the already-repaired document over the evidence. Quarantine objects are undeletable (console-only) and accumulation is not a loop.
- **The directory is readable by EVERY authenticated user (146), and that is accepted:** one `s3:GetObject` on `_directory/*`, no `ListBucket` widening (so it stays invisible to the file browser), no write. The username is already the prefix, the principal tag and the DB name; usernames only — **no emails**. The builder's own `ListBucket` is unconditioned and holds **no `GetObject` anywhere**; the `s3:prefix`-on-empty-string tightening is rejected as unverifiable.
- **Static-asset caching (141):** `deploy-app.yml` uploads in **three prefix-scoped passes** — assets `immutable`, shell `no-cache`, one `--delete` last. A content-hashed URL is immutable, a stable URL revalidates. `--exclude` **protects** keys from `--delete` (it filters the destination generator too), so a pass that excludes a prefix can never *reconcile* it — scope by **prefix**, and never let two passes touch one file (mtime re-upload overwrites the header). Accepted orphan class: **stale root files**.
- **Security scanning (138):** `security.yml` runs the six-scanner suite, gated by one `GATE_*` value each (bad value = hard error); the two ESLint security plugins **block** in lint instead. Every scanner **version-pinned**. **"Did not run" is never "clean"** — a broken scanner fails the job even under `report`. Findings + dispositions: `docs/security-baseline.md`.
- **A scanner gate blocks on a NARROWED count, never a total (2026-08-09):** Checkov gates on an **enforce list** of check IDs measured at zero (`.github/checkov-enforced.txt`, 52) — enforcing what already passes, not suppressing what doesn't; the plan scan gates on IAM findings not on an **accept list keyed by check ID AND resource** (2 permanent deploy-role rows). An enforced ID evaluated against **nothing**, and a stale acceptance, are both **hard errors**. **Neither Checkov gate can redden a deploy** — `plan` is PR-only and `apply` doesn't depend on it. Two shell facts make all of that reachable and both were missing at first: **assign before you echo** (`echo "V=$(f)"` never fails the step) and **default to a non-numeric sentinel** (`${V:-0}` fires on empty too, so a missing count read as clean). `--quiet` strips `passed_checks` and must never come back. Semgrep blocks on **unpinned registry rulesets** — accepted, same property `pip-audit` already has.
- **IAM policy scanning (139):** the `.tf` scan evaluates **zero** IAM checks (policies are `templatefile()` calls); `deploy-infra.yml`'s plan job scans the **rendered** `tofu show -json` plan instead, and **asserts its own coverage** (fails if IAM resources are present but no IAM check ran). Isolation policies are clean; the residual findings are non-scopable deploy-role actions.
- **Every plane notifies on a pre-verb failure (152):** all four machines carry a `NotifyFailure` before `Fail`, reached on **every** failure path (the no-verb-ran paths can't be selected for in ASL), invoking a thin verb that decodes the raw `{Error, Cause}` with `cpcommon.errors.failure_reason` — the **only** decoder. A fleet test asserts every machine has the state and copies `$.error` **whole**; the exemption list is empty. Duplicate suppression differs **by force, not style**: tb/ts suppress on **one positively-identified name** (`Error == "TerminalError"`) and notify on everything else — the tempting "a dot means an engine error" heuristic **silences an import-time bare `RuntimeError`**, which is PR #196's own shape, so don't reintroduce it; a **seed** must therefore never wear a verb's error name (`DiffMissingSeed`). shared-spaces reproduces the verb's **FIFO dedup token** instead, because five of its seven verbs notify nothing. shared-spaces also needed `ResultPath` on its seven catches — without it the verified actor was **discarded**. **No deploy-role IAM was needed** (verified: per-plane wildcards already cover it).
- **A layer gate checks the COPY LIST, not the flag map (153):** for any layer packaged by an explicit per-file list (only `shared-space-common`), assert **set equality** between the workflow's list and the directory — completing the flag map closes nothing, because all nine modules ship behind one flag. A sweep fails if a second explicit list appears; a guard-the-guard fails if the parse goes trivial.
- **`ACCEPTED_` tripwires record what the project has NOT verified (153):** a test that pins today's behaviour, names the reasoning, and says **revisit the decision, don't delete the test** if it starts failing. Four exist — the Athena case-fold, the projection round-trip's self-reference, the duplicate inbox row on redelivery, and the runs-index cap's position-based eviction.
- **A partial teardown never frees the space name (151):** `delete_objects`/`batch_delete_table` return **HTTP 200 with a per-item `Errors` array**, so a partial failure looked complete; both now raise `TeardownIncompleteError` and **leave the registry record intact** — the record IS the name lock (meets SPEC-054's criterion). Counts, never keys; every page attempted first; the Glue raise lands **before** `delete_database`.
- **Every DDL literal goes through `literal()` (151):** `TBLPROPERTIES` keys/values and `LOCATION` included — a raw `f"'{v}'"` let an enum value inject `'projection.enabled'='false'`, and an S3 segment like `year=2024'` killed a whole data-quality check. **Two escapers, never confused:** `ddl.literal` backslash-escapes (Hive/DDL), `dqcommon.sql._literal_dml` doubles the quote (Trino/DML). Ordinary values render byte-identically.
- **`components/` may not import from `features/` (155):** `features/query/` had become an undeclared shared layer; `Toast` → `components/`, the identifier rule → `lib/catalogIdentifier.ts`, and the connections domain (incl. `Sidebar`/`SpacesList`) → a new `features/connections/`. An **ESLint rule enforces it**, exempting tests and the two app-chrome files (`Header`, `ProtectedLayout`) **by name**. **The rule now covers `lib/` and `hooks/` too (2026-08-09)**: `lib/queryClient.ts` → `fileBrowserKeys` was the same inversion one layer lower, and closed by moving `invalidateListing` into `features/file-browser/`, not by moving the keys out.
- **Dialog Enter-to-submit fires from ONE field (155):** `FormDialog`'s body is a real `<form>`, but implicit submission is **suppressed** and only `submitOnEnterRef` (default `autoFocusRef`) submits — adopting the form naively filed a table build from a partition-key row mid-edit, **measured**. A child that handled the key wins.
- **Escape dispatches by tree DEPTH, not per-component opt-out (155, supersedes `closeOnEscape`):** one registry, innermost enabled handler only; `Drawer.closeOnEscape` is **gone**, and a busy `Modal` **swallows** Escape. Sits beside — does not contradict — the settled `stopPropagation` finding below: a child that stops the event never reaches the registry.
- **The byte formatters share a TB ceiling (155 FR-007):** `formatSize` and `formatBytes` stay separate for `undefined` handling, but 3 TB no longer reads `3072.0 GB` on one screen and `3.0 TB` on another. **User-visible on purpose**; silently keeping both was not an allowed outcome.
- **Compiler and coverage defaults are declared, never inherited (150):** both tsconfigs state `"strict": true` (already TS 6's default — declaring it changed **zero** errors) and both suites carry **literal** coverage floors — portal 91/86/89/93, lambdas 95 — as **ratchets at the measured level, not targets**. Never lower one for a regression. `pyproject.toml`'s ruff block is the precedent; the `npm run build` PR gate is separate and already shipped (#363).
- **The deliberate twins are discharged (156):** `cpcommon` owns the algorithm, a domain layer owns its wording — one CAS loop (cap 6), one `Resolver` that renders the **whole sentence** (`prefix`/`access_denied`/`fallback` templates), one results-location builder, one JWKS path, one SQS parser, one Athena runner, one `dedup_id`. **An eager module-level `_require` forces a fork, not just an inconvenience** — that is why the JWKS duplication existed. **Byte-identity was measured by rendering both implementations and diffing (2214 messages/side), not argued**; the one row that differed is unreachable and pinned by a test. Do NOT merge the domain layers wholesale.
- **Deploy-role refresh deadlock (lever):** the deploy role can lock itself out — tighten or widen one of its own grants and plan, apply **and revert** all fail alike. `Deploy Infrastructure` takes an off-by-default `skip_refresh` dispatch input to break it; **always follow with a normal run**. A green `plan` is not proof — IAM is eventually consistent.

## Out of Scope (don't build)

No backend/API layer · no in-browser file preview · no admin UI · no second **user-space** bucket
(several buckets exist — shared-space, admin, artifacts, static; the constraint is one bucket of
personal prefixes).

---

## Session Workflow

**Start:** (1) this file; (2) the spec you're implementing (`@docs/specs/SPEC-XXX`); (3) for context, pull **only** what the spec touches — the matching `component-inventory/` area file(s), the one architecture.md section, the `decisions.md` entry for the area, a dependency's delivery doc. Never read architecture.md, the inventory, or delivery docs in full. (4) Confirm `gh run list --branch main --limit 5` is green (esp. Deploy Infrastructure / Lambdas / App); investigate failures before building. (5) Branch from fresh `main` (`git fetch && git switch -c <branch> origin/main`). (6) Generate an implementation plan from the spec's phases, validate it against the spec (FRs + acceptance criteria covered, reuse used, nothing out of scope), and confirm it before writing code.

**During:** after a phase, stop and summarize what was built and how it maps to the plan. Specs carry no Open Questions — triage emergent issues by kind: **reversible/technical** ones you decide in-session (update the spec if scope changes); **product-changing or ambiguous** ones you stop and escalate to the human with options + a recommendation, never silently decide.

**Review:** code review and verification run in a **fresh context** (new session or subagent), never the session that wrote the code — check the diff against the spec's acceptance criteria, not just "looks fine."

**PRs & main:** before opening a PR, get the formatter, linter, unit tests **and `npm run build`**
green locally — `build` (`tsc -b`) is the only one that typechecks, and `tsc -p tsconfig.json`
silently checks nothing. CI now runs it too (#363). Watch every PR to completion and merge it as soon as CI is green — never open-and-abandon. `main` is always watched: after any merge confirm it went green, and if `main` fails, diagnose immediately and fix it with a new PR before anything else.

**Infra rule:** any spec that provisions new infra must expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) as in-scope work — not an afterthought. Adding a *new resource type* trips recurring IAM/propagation traps (self-grant timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) and Lambda code/infra split — read architecture.md → *Deploy-role IAM — adding a new resource type* + *Lambda code/infra split* first.

**On spec completion — keep the always-loaded files lean:**
1. Set the spec file's `Status: Completed`.
2. Update the one-line row in `@docs/specs/INDEX.md` (status only — don't add prose).
3. Write a delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from the template — **short** (what shipped + what changed; reuse lives in code + component-inventory, not prose).
4. If it added reusable services/hooks/components, add a one-line row to the `docs/component-inventory/<area>.md` **matching the component's path** — a `features/query/` row belongs in the query file, nowhere else (the router only gains a row if a whole new area appeared).
5. A *new architectural decision* gets the full entry in `@docs/decisions.md` **first**, then **one line** in Key Decisions above — the digest line is **never the only home of a fact**, and never a paragraph. If it **supersedes an earlier decision**, add an in-place superseded marker (short blockquote) at every doc site still stating the old claim (`ARCS.md` arcs, architecture.md sections). Reasoning belongs in the spec/delivery doc.
6. **Prune `## Specs` → Current work:** delete what the closed spec made stale. It tracks *only* what is live and undocumented elsewhere — never append a changelog; INDEX.md has status and `ARCS.md` has narrative.
7. **User-facing docs sweep:** if the spec changed anything a user can see, update the in-app **Help & guides** content (`apps/portal/src/features/help/helpContent.ts`, SPEC-074) and any onboarding copy — add a guide for a newly-shipped feature, fix steps/labels for a changed flow, delete a removed one. Document only what's shipped + wired end-to-end (SPEC-074 FR-005). If nothing user-facing changed, note that and skip.

**Doc-size guardrail:** `CLAUDE.md` is the always-loaded file — if an edit pushes a section past a
few lines, the detail belongs in a `docs/` file behind a pointer. Same for `INDEX.md` (status rows
only) and the inventory router.
