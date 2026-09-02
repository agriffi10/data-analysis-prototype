# S3 File Portal

A web portal that lets authenticated users upload and download files to/from their own
private space in AWS S3. Authentication is handled by **AWS Cognito**; per‑user isolation is
enforced at the **IAM layer**, not in application code. The single‑page app talks to AWS **directly
from the browser** using short‑lived, scoped credentials for most of what it does, with an HTTP API
and seven async control planes behind it for work a browser session must not be trusted with.

> **New here?** Start with this README for the big picture and setup, then read
> [`docs/architecture.md`](docs/architecture.md) for the design and
> [`CLAUDE.md`](CLAUDE.md) for conventions and the decision log.

---

## How it works (in one minute)

```
Browser (React SPA)
  │  1. Sign in  ──────────────►  Cognito User Pool (Hosted UI, username + password)
  │                                     │ JWT (id/access/refresh)
  │  2. Every request  ─────────►  The API, carrying the ID token as a bearer
  │                                     │ verifies it, then assumes ONE shared role
  │                                     │ stamping  username  from the verified claim (ABAC)
  │                                     ▼
  │                               S3 user-space bucket, scoped to  {username}/  by
  │                               ${aws:PrincipalTag/username} in the role policy
  │  3. Bytes  ─────────────────►  S3 directly, over a presigned URL the API minted
```

- **One shared IAM role** for all users. Isolation comes from the API stamping the verified
  `username` claim as a principal tag — the browser never asserts its own identity, and never
  holds AWS credentials at all, so it can't be spoofed.
- **File work goes through the API**, which does the S3 work under the assumed role. The one
  thing the browser still sends to AWS itself is bytes, over a presigned URL. Move/rename are
  copy‑then‑delete (S3 has neither); folders are zero‑byte marker objects. Anything privileged,
  cross‑user or multi‑step runs on a **control plane** instead.
- The pieces, how a request travels between them, and the decision record that explains the shape
  live in [`docs/architecture.md`](docs/architecture.md).

---

## Repository layout

This is an **npm workspaces monorepo**.

```
/
├── README.md                  ← you are here
├── CLAUDE.md                  ← project memory: conventions, tech stack, decision log
├── package.json               ← workspace root (workspaces: apps/*, packages/*)
├── apps/
│   └── portal/                ← the React SPA (all app code lives here)
│       ├── src/               ← components, features, hooks, lib, routes, types
│       ├── .env.example       ← every VITE_* var, documented
│       └── package.json
├── infra/                     ← OpenTofu IaC (ECS + ALB, the API, Cognito, IAM, data buckets)
│   ├── main.tf · variables.tf · outputs.tf
│   ├── bootstrap/             ← one-time remote-state setup (S3 + DynamoDB)
│   └── modules/               ← spa/ + network/ (hosting) · api/ · base/ (OIDC + deploy role) · auth/ · data/
├── lambdas/
│   └── pre-signup/            ← Cognito pre-signup trigger (Python)
├── docs/                      ← architecture, design system, specs, delivery records
└── .github/workflows/         ← CI + deploy pipelines (OIDC, no stored AWS keys)
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Language | TypeScript (strict mode) |
| Styling | TailwindCSS v4 (`@theme` design tokens — no `tailwind.config`) |
| Routing | `react-router-dom` v7 (library mode) |
| Server state | TanStack Query (`@tanstack/react-query`) |
| UI state | React Context + `useReducer` (no Redux) |
| AWS SDK | `@aws-sdk/client-athena`, `@aws-sdk/client-glue`, `@aws-sdk/client-sqs` — **no S3 client**: objects go through the API and file bytes through presigned URLs |
| Auth | AWS Cognito + Amplify v6 (`aws-amplify`) |
| Testing | Vitest + React Testing Library |
| Linting | ESLint + Prettier |
| IaC | OpenTofu (`~1.8`), AWS provider, S3 remote state + DynamoDB lock |
| Lambdas | Python 3.12 |
| CI/CD | GitHub Actions (OIDC to AWS) |
| Monorepo | npm workspaces |

---

## Local development

### Prerequisites

- **Node.js 24** and npm — the version lives in `.nvmrc`, which is the single source of truth:
  every workflow reads it via `node-version-file`, and `nvm use` / `fnm use` picks it up locally.
  Matching it keeps `package-lock.json` stable, since npm's major writes different lockfile
  metadata.
- For IaC work: **OpenTofu `~1.8`** and the **AWS CLI** (configured with credentials for the
  target account)
- For Lambda work: **Python 3.12**

### Install & run

```bash
npm install                      # installs all workspaces from the repo root
npm run dev      -w apps/portal  # Vite dev server → http://localhost:5173
```

App scripts (run from `apps/portal/`, or from the root with `-w apps/portal`):

```bash
npm run dev        # start the dev server
npm run build      # production build → apps/portal/dist/
npm run preview    # serve the production build locally
npm run test       # Vitest (unit + component)
npm run lint       # ESLint
npm run format     # Prettier
```

### Running it locally

`apps/portal/.env.example` documents every variable. Copy it to `apps/portal/.env.local` and point
the `VITE_COGNITO_*`, `VITE_API_BASE_URL` and `VITE_S3_USER_SPACE_BUCKET` variables at a deployed
environment's `tofu output` values, then sign in normally. Uploads and downloads redeem presigned
URLs from `http://localhost:5173`, which both buckets' CORS allowlists name.

There used to be a second mode — an unauthenticated one that browsed a public test bucket with
anonymous S3 requests, needing no AWS account. It worked by having the browser call S3 directly,
and the browser no longer does: every read and write goes through the API, which verifies a bearer.
There is no unsigned call left for that mode to make, so it is gone along with its five variables.

---

## Deploying to a fresh AWS account

The app deploys as a container image behind a load balancer; all other resources (Cognito, the
shared IAM role, the user‑space bucket, the GitHub Actions OIDC role, the API, Lambda infra) are
provisioned by OpenTofu. The runbook below stands up the whole thing in a **new AWS account**.

> Detailed, step‑by‑step references: [`infra/bootstrap/README.md`](infra/bootstrap/README.md)
> (remote state) and [`.github/workflows/README.md`](.github/workflows/README.md) (CI/CD config).

### 1. Bootstrap remote state (once per account)

OpenTofu stores state in S3 with a DynamoDB lock table. These are created **manually** and are
**not** managed by the IaC. Follow [`infra/bootstrap/README.md`](infra/bootstrap/README.md) to
create the state bucket and lock table, then:

```bash
cd infra
cp bootstrap/backend.conf.example backend.conf   # fill in bucket/table names (gitignored)
```

### 2. Configure IaC inputs

```bash
cp terraform.tfvars.example terraform.tfvars      # gitignored
```

Set at least `aws_region`, `project_name`, `github_repo` (as `owner/repo`), `state_bucket`, and
`state_lock_table`. Other inputs (`environment`, `cognito_domain_prefix`,
`user_space_bucket_name`, `portal_role_name`) have sensible defaults — see
[`infra/variables.tf`](infra/variables.tf). Resource names follow `{project_name}-{environment}-*`.

### 3. First apply (locally, with admin credentials)

The first apply must run locally because it *creates* the GitHub Actions OIDC role that CI uses
for every subsequent apply (chicken‑and‑egg). Authenticate the AWS CLI to the target account,
then:

```bash
cd infra
tofu init -backend-config=backend.conf
tofu plan          # review
tofu apply
tofu output        # capture the values needed for the next step
```

This provisions: the VPC and its endpoints, the load balancer and the ECS service that serves
the SPA, the API's front door, the GitHub Actions OIDC deploy role,
the Cognito User Pool + SPA client + Hosted UI domain, the shared portal IAM role, the
user‑space S3 bucket, and the pre‑signup Lambda's infrastructure (placeholder code).

### 4. Configure GitHub Actions (Settings → Secrets and variables → Actions)

Populate from `tofu output` (see [`.github/workflows/README.md`](.github/workflows/README.md)
for the full table and notes).

**Secrets**

| Secret | Source |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` |
| `TF_VAR_state_bucket` | your bootstrap state bucket name |
| `TF_VAR_state_lock_table` | your bootstrap lock table name |

**Variables**

| Variable | Source |
|---|---|
| `AWS_REGION` | e.g. `us-east-1` (must match all resources) |
| `VITE_APP_URL` | `tofu output spa_origin` |
| `TF_VAR_github_repo` | `owner/repo` (must match exactly; scopes OIDC trust) |
| `VITE_COGNITO_USER_POOL_ID` | `tofu output cognito_user_pool_id` |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | `tofu output cognito_user_pool_client_id` |
| `VITE_COGNITO_DOMAIN` | `tofu output cognito_domain` |
| `VITE_S3_USER_SPACE_BUCKET` | `tofu output s3_user_space_bucket_name` |
| `TF_VAR_project_name` / `TF_VAR_environment` | only if you overrode the Terraform defaults (`dat` / `prod`) |

### 5. Deploy the Lambda code

The IaC creates the Lambda *infrastructure* with placeholder code; the real Python is shipped by
CI. Trigger **Deploy Lambdas** — run it manually (`workflow_dispatch`) or push a change under
`lambdas/**` to `main`.

### 6. Deploy the app

Push to `main` (or merge a PR). **Deploy SPA image** builds the image, proves it against the
container matrix, pushes it to ECR tagged with the commit sha, and points the ECS service at the
new revision. The app loads at `spa_origin` when the rolling deployment finishes.

There is no URL loop to close any more. The app's origin is a subdomain the infrastructure owns,
so `spa_origin` is known before the first deploy rather than after it — which is what the old
CloudFront domain was not. The certificate is DNS-validated in `us-east-1` and provisioned with
the rest of the front door; see [`docs/architecture.md`](docs/architecture.md) →
*Infrastructure and delivery*.

---

## CI/CD pipelines

All deploy workflows authenticate to AWS via **GitHub OIDC** — no long‑lived AWS keys are stored.
See [`.github/workflows/README.md`](.github/workflows/README.md) for the full configuration.

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push (any branch) · PR → `main` | Lint, unit/component tests, production build |
| `deploy-spa-image.yml` | push → `main` | Build the SPA image, prove it against the container matrix, push to ECR by commit sha, point the ECS service, wait for it to settle |
| `deploy-infra.yml` | PR / push → `main` (paths `infra/**`) | `tofu fmt -check` + `plan` (posts plan to the PR); `apply` on merge |
| `deploy-lambdas.yml` | push → `main` (paths `lambdas/**`) · manual | Build each Python Lambda, upload artifact, `update-function-code` |

---

## Environment & configuration reference

- **App configuration** — the app reads a runtime `/config.json` document rather than build-time
  `VITE_*` values in production. Every key, and the five places it is wired, is
  [`apps/portal/info/runtime-configuration.md`](apps/portal/info/runtime-configuration.md); the dev
  fallback variables are [`apps/portal/.env.example`](apps/portal/.env.example).
- **IaC inputs** — [`infra/variables.tf`](infra/variables.tf) /
  [`infra/terraform.tfvars.example`](infra/terraform.tfvars.example).
- **IaC outputs** (the values you wire into GitHub Actions) —
  [`infra/outputs.tf`](infra/outputs.tf).
- **GitHub Actions secrets & variables** — tables above and in
  [`.github/workflows/README.md`](.github/workflows/README.md).

---

## Documentation index

| Document | What's in it |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Project memory (always loaded, kept lean): tech stack, code conventions, a one-line **Key Decisions** digest, session workflow |
| [`docs/process.md`](docs/process.md) | How we work: where truth lives, the spec lifecycle, the review gate, the completion ritual |
| [`docs/reviewer-contract.md`](docs/reviewer-contract.md) | The method behind the review gate — pulled when you are about to spend a reviewer |
| [`docs/decisions/`](docs/decisions/INDEX.md) | The **Key Decisions register in full** — reasoning + the "do NOT build" fences |
| [`docs/architecture.md`](docs/architecture.md) | **How the system works** — the pieces, how a request travels, the constraints that shape it, and the Architecture Decision Record indexing the register |
| [`docs/transition_plan.md`](docs/transition_plan.md) | The client-environment transition — IdC federation, de-provisioning, Lake Formation re-keying |
| [`lambdas/info/shared-layer.md`](lambdas/info/shared-layer.md) | The long-form *why* behind `cpcommon` — sizing evidence, rejected designs, the traps |
| [`lambdas/info/planes/`](lambdas/info/planes/) | One page per control plane: its machine, rules, fences, layer and sizing |
| [`apps/portal/info/component-inventory/INDEX.md`](apps/portal/info/component-inventory/INDEX.md) | **Router** to the per-area inventories in [`apps/portal/info/component-inventory/`](apps/portal/info/component-inventory/) (reusable services / hooks / components / types / utilities) |
| [`docs/best-practices/INDEX.md`](docs/best-practices/INDEX.md) | Router to the domain rulebooks — React, Python, lambdas, accessibility |
| [`lambdas/info/INDEX.md`](lambdas/info/INDEX.md) | Every Lambda grouped by control plane, with a page per plane |
| [`infra/info/INDEX.md`](infra/info/INDEX.md) | Every Terraform module; each has a `README.md` carrying its reasoning |
| [`docs/specs/`](docs/specs/) | Feature specs — what each feature should do; [`INDEX.md`](docs/specs/INDEX.md) is status, [`ARCS.md`](docs/specs/ARCS.md) is arc narrative |
| [`docs/spec-delivery/`](docs/spec-delivery/) | Delivery records — what was actually built per spec, plus later-change amendments |
| [`docs/testing/e2e.md`](docs/testing/e2e.md) | **The** end-to-end validation guide; [`owed.md`](docs/testing/owed.md) is what it cannot settle, [`sessions.md`](docs/testing/sessions.md) is what has been run |
| [`docs/security-baseline.md`](docs/security-baseline.md) | Every scanner finding with a disposition, and the gate thresholds |
| [`docs/design/design-system.md`](docs/design/design-system.md) | Design tokens, typography, component patterns (the source of truth for the UI) |
| [`docs/templates/`](docs/templates/) | Spec + spec-completion templates |
| [`infra/bootstrap/README.md`](infra/bootstrap/README.md) | One-time remote-state (S3 + DynamoDB) bootstrap |
| [`.github/workflows/README.md`](.github/workflows/README.md) | CI/CD workflows + first-time GitHub Actions configuration |

---

## Conventions & where to find things

- **Code conventions** (TypeScript strict, named exports, `ServiceResult<T>` from services that
  never throw, feature‑folder structure, file‑naming) are defined in [`CLAUDE.md`](CLAUDE.md).
- **Feature code** lives in `apps/portal/src/features/<feature>/`; shared UI primitives in
  `apps/portal/src/components/`; AWS clients in `apps/portal/src/lib/`.
- **Before reusing code**, check [`apps/portal/info/component-inventory/INDEX.md`](apps/portal/info/component-inventory/INDEX.md) and
  open the area file(s) it routes you to.
- **Infrastructure** is organized as bounded‑context modules under `infra/modules/`; IAM policies
  are `.tftpl` templates rendered with `templatefile()`. New resource types must also be granted
  to the deploy role (`infra/modules/base/`).
