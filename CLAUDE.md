# Data Quarry — Project Memory

Loaded every session — keep it lean. **Start by reading `@docs/process/INDEX.md`, then
`@docs/process/session-rhythm.md`**: the router to how we work, and the one part of the method every
session runs on. The other parts — the spec lifecycle, authoring a spec, the completion ritual, the
knowledge layout, the CI and deploy traps — are pulled when the router's table says, and `where-truth-lives.md` there is
the **full doc router**: which file is authoritative for what, and when to pull it, so this file
does not repeat it. Everything outside the always-loaded tier is pulled **on demand**:
cross-cutting docs in `docs/`, and the domain rulebooks and inventories beside the code they
govern, in each tree's `info/` folder. Three you will reach for beside this file:
- `@docs/architecture.md` — **how the system works**: the pieces, how a request travels, and the
  **Architecture Decision Record**. Short enough to read whole, and the cheapest way into a part of
  the system you haven't touched. It carries no rules and no trap lists — those live beside the code
- `@docs/decisions/index.yaml` — the Key Decisions register, **generated**: every area's fences, the
  traps that apply green and fail later (one file per decision under `docs/decisions/<area>/`). Read
  your area's block before working in it, not the whole file
- `@docs/specs/index.yaml` — the spec index, generated from each spec's frontmatter
- `@docs/transition_plan.md` — **single source of truth** for the client-environment transition
  (Entra ID sign-in in **two variants** — §3.3 — IdC propagation, one credential plane with S3
  Access Grants, provisioning and de-provisioning, LF re-keying, ODBC/JDBC drivers); read before touching
  auth, provisioning or LF

**Context discipline:** these are pointers, not a reading list. Pull a doc when a task needs it.

---

## Project Overview

A web portal where authenticated users upload/download files to/from their own S3 prefix.
Auth is a Cognito **User Pool**; the browser holds no AWS credentials. The object surface, the
catalog and the control-plane queues sit behind one API (`api.dataquarry.app`). The portal is Next.js
on a Node server behind an ALB, the only front door, off when idle; the browser holds no token and
reaches AWS only for **presigned S3 bytes**. Status: greenfield, no production users yet.

## Monorepo (npm workspaces)

- `apps/portal/` — the Next.js app (**all app code lives here**; paths below are relative to it)
- `infra/` — OpenTofu IaC (**all IaC paths relative to here**); one-concept modules under `infra/modules/`, composed flat from the root
- `packages/` — reserved, currently empty
- `docs/` — architecture, specs, spec-delivery, templates

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 19 on Next.js 16 (standalone server), TypeScript (strict), TailwindCSS (`@tailwindcss/postcss`); `server-only`; `focus-trap-react` |
| TypeScript | **Two copies on purpose: `npm ls typescript` reporting 6.x is not a bug.** `tsc -b` runs 7.x from `apps/portal/node_modules`; typescript-eslint pins `<6.1.0` (TS 7 ships no API before 7.1) so npm hoists 6.x to the root for it. `npm ci` reproduces it; `npm install` only if `typescript` goes LAST — named beside `typescript-eslint` it fails ERESOLVE, and `--force`/`--legacy-peer-deps` "fixes" that by breaking lint. Check versions with `npx tsc --version` **from `apps/portal/`** |
| AWS | Browser: none (`check:bundle` fails on an AWS client). Server (`src/server/`): `@aws-sdk/client-dynamodb` for the session store only. An ESLint `no-restricted-imports` clause and a `package.json` test hold both; objects, bytes, the catalog and the queues go through the API |
| Editor | `@monaco-editor/react` + `monaco-editor` (self-hosted workers; lazy-loaded on the Query route only, SPEC-035) |
| Routing / state | Next.js App Router; features navigate through `src/lib/navigation/` only (`react-router` is its matcher, lint-held). TanStack Query (server state) + Context/`useReducer` (UI state); no Redux |
| Testing / lint | Vitest (Vite's only use) + React Testing Library + `@testing-library/user-event`; `@vitest/coverage-v8` (`npm run test:coverage`); `vitest-axe` (axe-core a11y assertions, SPEC-045); ESLint + Prettier. Tests are **integration-style** — **import only the component under test**, render real hooks/children, mock only the service boundary (`*.service.ts` / `lib/apiClient`); **1–3 scenarios each** (4–5 where earned; a dozen means the unit is scoped wrong), **arrange/act/assert**, happy path and failure path first; shared harness `src/test/renderWithProviders.tsx`. Rules: `apps/portal/info/best-practices/react/react.md` §21, `lambdas/info/best-practices/lambdas/lambdas.md` §11 |
| Lambda Python | `polars` (pinned twice — table-builder and data-quality — and read fleet-wide since the image installs every requirements file into one site-packages); `xlsxwriter` for the results-conversion **convert** verb's Excel writer and nothing else. **A new `lambdas/**/requirements.txt` must be named TWICE in `lambdas/Dockerfile`** (a `COPY` and a `--requirement`); nothing derives that list from the tree, and an unnamed file installs silently as nothing |
| IaC | OpenTofu (HCL, S3 remote state) |
| Security | `eslint-plugin-security` + `eslint-plugin-no-unsanitized` (in `npm run lint`, **pre-push**); Semgrep / `pip-audit` / gitleaks / Checkov **block** in `security.yml`; `npm audit` and the OWASP ZAP baseline **report** (SPEC-138 — the modes are the `GATE_*` block at the top of the workflow). Every scanner version-pinned — see the VERSIONS block and #311 |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS: no SDK in the browser (Tech Stack row). Objects, the catalog and the queues go through `lib/apiClient`'s `apiRequest`, called from service files, never from components; bytes go to S3 on a URL the API presigned.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Configuration: the server's `CONFIG_<key>` variables, documented in `apps/portal/.env.example`.
- **A comment names no spec, PR or issue number** — not `SPEC-166`, not `(#252)`, not "since SPEC-158". A reader is standing in the file, not in the project's history: write the reason ("a third copy would fork the lookup"), not the citation. Full entries live in `docs/decisions/`, findable by what they say. Applies to `.ts`/`.tsx`/`.py`/`.tf`/`.tftpl`; enforced by `scripts/validate_docs.py`.
- **No verbose comments in `.ts`/`.tsx`/`.py` files.** JSDoc (TS/React) and docstrings (Python) are the primary source of context — expand those over adding narrative inline comments; comments are reserved for the non-obvious *why*, kept short. Detail: `apps/portal/info/best-practices/react/react.md` §19, `lambdas/info/best-practices/python/python.md` §14.
- **`lambdas/` production code carries NO inline comments** (only `# noqa` / `# type: ignore` per §14; tests exempt). Every module, class, method and function — public or `_private` — has a Google-style docstring: a one-line summary of what it does *and its context*, an optional short *why* paragraph, then `Args:` / `Returns:` / `Raises:`, each written out with `None.` when the section is empty. A module's constants are documented in its docstring's `Attributes:` block. Anything longer than a paragraph of reasoning goes beside the code in `@lambdas/info/` — `shared-layer.md` for `cpcommon`, the plane's own page otherwise — not in the file. Format: `lambdas/info/best-practices/python/python.md` §14.
- When writing/refactoring code in a domain with a rulebook (React, accessibility, …), consult `@docs/best-practices/INDEX.md` first and load only the relevant section(s) — don't reinvent or guess the rules.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
npm run format|format:check -w apps/portal   # Prettier (prettier.config.js); format:check is a pre-push gate
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
python3 scripts/watch_ci.py --pr <n>         # watch CI for ONE sha; exit 0 only if settled AND green
python3 scripts/watch_ci.py --branch main    # after a merge; --once for a single poll
python3 scripts/validate_docs_test.py        # prove the doc gate's checks still fire (run when you change it)
sh scripts/gen-index.sh                      # after any frontmatter change; never edit an index by hand
```

## Specs

Status lives in each spec's frontmatter (`docs/specs/index.yaml` lists it), narrative in `ARCS.md`, what shipped in
`@docs/spec-delivery/`, live checks in `@docs/testing/`. **This section carries only what is live and
recorded nowhere else** — when a spec closes, prune here rather than appending.

## Key Decisions (settled — don't re-litigate)

**Grouped by area, not by spec.** One file per decision, in one directory per area: its `description`
is the **fence** — the claim and its constraint, the traps that **apply green and fail later**, which
is the failure mode this project keeps paying for — and its body the reasoning and every "do NOT
build". `docs/decisions/index.yaml` (generated) lists every area's fences: **read your area's before
working in it**; a path-scoped rule under `.claude/rules/` points there too. A new decision is a new
file, never a line here; a new *area* is a new directory and a row here, in slug order.
`scripts/validate_docs.py` holds the register and the rules to this table.

| Area | Directory |
|---|---|
| Analytics, the catalog, and two SQL dialects | `docs/decisions/analytics/` |
| Archive and restore — the only place a mistake is unrecoverable | `docs/decisions/archive-and-restore/` |
| The browser | `docs/decisions/browser/` |
| Control planes — one pattern, eight planes, and the traps are shared | `docs/decisions/control-planes/` |
| Gates, scanners and tests | `docs/decisions/gates-and-tests/` |
| Identity, access and the name that ties them together | `docs/decisions/identity-and-access/` |
| Infrastructure, IAM and delivery | `docs/decisions/infrastructure/` |
| Storage, and the fact S3 is not a filesystem | `docs/decisions/storage/` |

## Out of Scope (don't build)

No **second** API (one HTTP API, one `$default` route — a feature does not get its own service) ·
no **new** browser-side AWS SDK call on a path an API route already serves · no in-browser file
preview · no admin UI · no second **user-space** bucket
(several buckets exist — shared-space, admin, artifacts; the constraint is one bucket of
personal prefixes).

---

## Session Workflow

**The contract is `@docs/process/` — its router and `session-rhythm.md` are read every session, not
once.** This section is the entry sequence, plus the few gates worth having in front of you before
you open anything; for the rest it points, because a summary that restates the contract drifts from
it, and this one already has (#595). Nothing here is the *only* statement of a rule — the process
files are.

**Start:** (1) this file, then `@docs/process/INDEX.md` and `@docs/process/session-rhythm.md`; (2)
the spec (`@docs/specs/SPEC-XXX`); (3) pull **only** what the spec touches — the **fences** of each
Key Decisions area it lands in, the matching `apps/portal/info/component-inventory/` area file(s), a
dependency's delivery doc; read `architecture.md` whole only for a part of the system you don't
already hold, and never read the inventory or delivery docs in full. (4) Confirm `main`
is green, verdict first: `python3 scripts/watch_ci.py --branch main --once`, then the deploys per
`session-rhythm.md`; investigate failures before building. (5) Branch from fresh `main`
(`git fetch && git switch -c <branch> origin/main`). (6) Plan from the spec's phases, validate it
against the spec, and send it to a **fresh-context reviewer**; (7) send the **PR grouping** to one
too, before the first push — as few PRs as the dependencies allow.

**During:** those two reviews are the only gates on *starting* — **build straight through to
completion**, summarizing a phase in passing but never ending the turn on it (a summary that ends
the turn *is* a request for approval). Specs carry no Open Questions: decide **reversible/technical**
issues in-session and update the spec if scope changes; **stop and escalate product-changing or
ambiguous** ones — never silently decide, and never as options written out in prose that end the
turn: ask with the **question tool**, the options as selections and the recommended one first, and
continue on the answer.

**Review and spec size: `@docs/process/session-rhythm.md` and `@docs/process/authoring-a-spec.md`.**
Three artifacts — a **spec**, a **plan** and a **diff** — each reviewed in a **fresh context**, the
diff twice; **a branch does not reach the remote** until every finding is fixed or flagged. Specs
run 3–6 FRs and split past 8. Read those files rather than working from memory of them — the
session rhythm carries the exit rules this paragraph compresses, and the authoring file the FR
ceiling and the `SPEC_OVERSIZE_MAX` ratchet. The method — how many reviewers, briefing one, rotating
the frame — is `@docs/reviewer-contract.md`, pulled when you are about to spend one.

**PRs & main:** building a spec **authorizes the whole landing** — the push of the reviewed branch,
the PR, the watch and the merge on green are the build's last steps, not decisions to confirm.
Formatter, both linters, both suites, mypy **and `npm run build`** green locally before pushing —
**CI runs none**, so that run is the only gate, and **that list is a floor, not the set**: also run
whatever `ci.yml` runs on the branch (`@docs/process/ci-and-deploy-traps.md`). **When several
sessions share this repo** — they routinely do — the remote is serialised by a PR queue: one PR open
at a time, in the order agents asked, `main` green before the next, and you get in line only once
your gates and reviews are green; its hook also refuses a stale base. **A queue is already
installed here, at a path derived from this checkout's directory name, and a bare `install.sh`
stands up a SECOND, empty one** — the live path rule and the re-install recipe are
`@docs/process/several-agents.md`; protocol `scripts/pr-queue/PROTOCOL.md`; brief each session from
`@docs/templates/multi-agent-briefing.md`. Watch every PR to completion and merge as soon as CI is
green — never open-and-abandon. `main` is always watched: if it fails, fix it with a new PR before
anything else. **Watch with `scripts/watch_ci.py`, never a hand-rolled loop** — it keys on one sha
and its exit condition is tested, which two hand-written watches were not.

**Infra rule:** any spec that provisions new infra expands the deploy role's IAM (`.tftpl` under
`infra/modules/base/policies/`) as in-scope work, and it lands in **its own PR before** the
resources that need it. A *new resource type* trips recurring IAM/propagation traps (self-grant
timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) — read
`@infra/info/deploy-role-iam.md` first, and `@lambdas/info/deployment.md` before adding or rewiring
a Lambda.

**On spec completion:** run the ritual in `@docs/process/completion-ritual.md` in one pass —
`spec_status`, a **short** delivery doc, a one-line inventory row **if** something reusable landed, a
new file under `docs/decisions/<area>/` **if** the spec settled a new decision, its fence the claim
and the entry its reasoning, `sh scripts/gen-index.sh`, an `architecture.md` ADR row **only** if the
system's shape changed, a prune of `## Specs`, live checks folded into `@docs/testing/e2e.md`, and a
Help & guides sweep. **A fence is never the only home of a fact**; a reversal **rewrites the decision
in place** and adds a dated History entry — and mark the superseded claim in place at every other
site still stating it (`@docs/specs/ARCS.md`, `architecture.md`). A check that cannot
run from a signed-in session becomes a row in `@docs/testing/owed.md`.

**Doc-size guardrail:** detail that outgrows a few lines belongs in a `docs/` file behind a pointer;
**the register is grouped by AREA, and a fence carries a trap, not history.** `scripts/validate_docs.py`
enforces the budgets on every PR — raise the doc's tier, never the cap. Full rules: the completion
ritual's anti-regrowth list.
