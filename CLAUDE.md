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

**No spec is in flight.** The observability arc (127→137) is COMPLETE, and so are SPEC-140, 141, 142
and the **whole refresh arc (143, 144, 149, 145)** — the pipeline classifies the change, refuses an
un-opted-into removal, replaces the definition **in place** via `glue:UpdateTable`, and **145 gave it a
browser surface**: a **Refresh table** item in the Query rail, the always-unchecked removals opt-in, and
the `columns_removed` notification link that names the columns. The live checks below are now runnable
from the UI.

**The username-directory arc (146 → 147 → 148) is COMPLETE and deployed.** The daily builder
publishes `_directory/usernames.json`; both `AddMembersDialog` and `TableShareDialog` suggest
existing usernames as you type, and neither blocks a name the directory does not know.

**One live check is owed, and it is a single browser pass** (Safari): open **Add members** and
**Share table** signed in, at 400px and desktop. Confirm suggestions appear, the list positions
inside the panel, and several chips still leave the confirm control reachable. **That one pass also
discharges SPEC-146's last owed check** — suggestions only appear if the portal role's SigV4
`GetObject` on the directory actually succeeds, so seeing one IS the end-to-end read confirmation.

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
  200. Check `content-type` and `x-cache: Error from cloudfront` instead. (2) **Every** deploy since the split has been byte-identical to
  its predecessor, so **the delete pass has still never deleted anything** (verified through run
  30902923653: 108 assets + 2 root uploaded, 0 deleted). The next deploy that changes a bundle hash
  is its first real test.
- **SPEC-138 shipped security scanning report-only; the follow-up is written but not built.**
  `docs/security-baseline.md` has every first-run finding with a disposition and a proposed gate
  per scanner. Two are at **zero today** — `gitleaks` (357 commits) and `pip-audit` (13 packages) —
  and **have now been flipped to `block` (2026-08-02)**. **`react-router` is on 8.3.0 (2026-08-05) —
  every one of its advisories is now cleared**, including the RSC-mode survivor that had been accepted
  as inapplicable; the v8 major was a package rename (`react-router-dom` is gone) and nothing else.
  **`npm audit --omit=dev` now reports NO highs.** The build-time `postcss` /
  `brace-expansion` advisories are **fixed (2026-08-03)** — both resolved by `npm update` inside the
  existing caret ranges, no `package.json` change and no `overrides` needed. Still open: **two** Checkov fixes
  (multipart-abort lifecycle, Athena workgroup enforcement). **S3 versioning is deferred by decision
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
  `get-table-versions` shows a previous version. Fold the casing read-back into it. SPEC-137 is the
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
- **The concurrent-refresh race is still open, and SPEC-157 owns it.** The Pipe invokes
  `StartExecution` as `FIRE_AND_FORGET`, so `MessageGroupId` serializes *delivery*, not *execution*,
  and two refreshes on one database overlap. 149 **reduced** it — neither run can see a missing table
  any more — but could not close it: **Glue offers no compare-and-set on `UpdateTable`** (`VersionId`
  carries no precondition semantics), so the worst case is last-write-wins between two definitions.
  **150 shut the browser's contribution** — a double-click can no longer start the pair (the ref
  guard; `deduplicationId` is a fresh UUID per call, so SQS FIFO never could have collapsed it) — but
  that is the *trigger*, not the race. SPEC-144's second exposure (a committed drop then silence) is
  **retired**: a failed update changes nothing.
- **SPEC-142 fixed the ragged/union bug; its Phase 4 is owed live.** Ragged rows are now judged
  against each file's own header via a `CASE` on `"$path"`. Still to run from the UI: a check over a
  folder whose files deliberately disagree (expect the cross-file finding and **no** ragged count),
  and one whose files agree (expect the same numbers as before). That live run is also the only
  thing that can confirm the assumption underneath the fix — that `"$path"` on the raw-line table
  returns the same `s3://bucket/key` form the manifest is keyed to.

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
- **Refresh eligibility = shape, not marker (143):** a refresh is judged by what Glue reports (`cpcommon.glue.clone_definition`, moved from `tscommon`), **never** by the `portal.managed` TBLPROPERTY it also starts writing — pre-143 tables lack it and users can set it; a test forbids any verb reading it. Reconstructed partition keys must **round-trip through the create path's renderer AND match the live column type**; a reconstruction that can't be performed is a **refusal, not a guess**. A `Choice` on an **absent** path raises uncatchable `States.Runtime` — `Default` does not cover it, so guard with `IsPresent`. `portal.managed` (table property, dotted) ≠ `portal-managed` (LF tag on databases, hyphenated).
- **Username directory source = S3, not Cognito (146):** the daily builder enumerates the user-space bucket's top-level common prefixes and makes **no Cognito call** (a test enforces it) — today Cognito is complete and S3 is not, but the transition reverses that (`ensurePrefixMarker` is deleted, `cognito:username` becomes synthetic `identitycenter_<subject>`). **No Cognito union "to be safe."** The document is **advisory**: never an authorization input, every existence check stays `admin_get_user`, and a tripwire test enforces that too.
- **The directory is readable by EVERY authenticated user (146), and that is accepted:** one `s3:GetObject` on `_directory/*`, no `ListBucket` widening (so it stays invisible to the file browser), no write. The username is already the prefix, the principal tag and the DB name; usernames only — **no emails**. The builder's own `ListBucket` is unconditioned and holds **no `GetObject` anywhere**; the `s3:prefix`-on-empty-string tightening is rejected as unverifiable.
- **Static-asset caching (141):** `deploy-app.yml` uploads in **three prefix-scoped passes** — assets `immutable`, shell `no-cache`, one `--delete` last. A content-hashed URL is immutable, a stable URL revalidates. `--exclude` **protects** keys from `--delete` (it filters the destination generator too), so a pass that excludes a prefix can never *reconcile* it — scope by **prefix**, and never let two passes touch one file (mtime re-upload overwrites the header). Accepted orphan class: **stale root files**.
- **Security scanning (138):** `security.yml` runs the six-scanner suite, gated by one `GATE_*` value each (bad value = hard error); the two ESLint security plugins **block** in lint instead. Every scanner **version-pinned**. **"Did not run" is never "clean"** — a broken scanner fails the job even under `report`. Findings + dispositions: `docs/security-baseline.md`.
- **IAM policy scanning (139):** the `.tf` scan evaluates **zero** IAM checks (policies are `templatefile()` calls); `deploy-infra.yml`'s plan job scans the **rendered** `tofu show -json` plan instead, and **asserts its own coverage** (fails if IAM resources are present but no IAM check ran). Isolation policies are clean; the residual findings are non-scopable deploy-role actions.
- **Compiler and coverage defaults are declared, never inherited (150):** both tsconfigs state `"strict": true` (already TS 6's default — declaring it changed **zero** errors) and both suites carry **literal** coverage floors — portal 91/86/89/93, lambdas 95 — as **ratchets at the measured level, not targets**. Never lower one for a regression. `pyproject.toml`'s ruff block is the precedent; the `npm run build` PR gate is separate and already shipped (#363).
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
