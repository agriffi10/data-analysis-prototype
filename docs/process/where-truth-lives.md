# Where truth lives (and why it's layered)


Two axes, and they answer different questions. **How often is it loaded** decides what may go in it:
the always-loaded tier was cut down from much larger versions and must not regrow, and the fix each
time is a pointer to a deeper tier, never a longer paragraph. **Which tree does it describe** decides
where it lives: documentation sits beside the code it is about, and `docs/` carries what spans trees
or belongs to no tree at all.

## Pulled on demand, by tree

| Tree | Entry point | Holds |
|---|---|---|
| The app | `apps/portal/info/component-inventory/INDEX.md` | a **router** to per-area inventories of what already exists — read the area(s) your spec touches, never all |
| | `apps/portal/info/best-practices/` | the React and accessibility rulebooks |
| | `apps/portal/info/runtime-configuration.md` | the `/config.json` contract and the five places a key is wired |
| The lambdas | `lambdas/info/INDEX.md` | every function, grouped by control plane — a lookup, not a description |
| | `lambdas/info/planes/<plane>.md` | one page per plane: its machine, what it accepts, its fences, its layer, and the evidence behind its caps |
| | `lambdas/info/shared-layer.md` | `cpcommon`'s module map and the long-form *why* behind it |
| | `lambdas/info/deployment.md` | the code/infra split, and the traps that only bite on deploy |
| | `lambdas/info/best-practices/` | the Lambda-shape and Python rulebooks |
| The infrastructure | `infra/info/INDEX.md` | the module index and the shape every control plane shares |
| | `infra/info/deploy-role-iam.md` | the trap list for adding a new AWS resource type |
| | `infra/info/web-tier.md` | the web tier's off switch: how to turn it off and on, and what it takes down |
| | `infra/modules/<name>/README.md` | one README per module, beside its `.tf` |

`docs/best-practices/INDEX.md` is a **cross-tree router** — it names which rulebook lives in which
tree, and holds no rules of its own.

## Pulled on demand, spanning trees

| File(s) | Loaded | Authoritative for |
|---|---|---|
| `docs/specs/INDEX.md` + each spec header | on demand | spec **status**, one row per spec |
| `docs/specs/SPEC-XXX-*.md` | the one you're building | requirements + phases |
| `docs/specs/ARCS.md` | the arc you're in | why an arc exists, how its specs compose |
| `docs/architecture.md` | whole, when you need orientation | **how the system works** — the pieces, how a request travels, and the ADR table indexing the decisions that shaped it. Short by design; it holds no rules and no trap lists |
| `docs/decisions/INDEX.md` → one area file | the *entry* for your area | settled decisions in full and the "do NOT build" fences, **one file per area, matching the rows of CLAUDE.md's Key Decisions table** |
| `docs/spec-delivery/SPEC-XXX-*.md` | when a dependency points to one | what a past spec shipped |
| `docs/testing/e2e.md` + `owed.md` + `sessions.md` | when running live checks | how to validate the deployed app, what is still owed, and what has actually been run |
| `docs/reviewer-contract.md` | when you are about to spend a reviewer, and when a build hits two FRs that cannot both hold | how many reviewers and where they run, briefing one, rotating the frame, adjudicating two FRs that cannot both hold, and when to stop — the method behind `session-rhythm.md`'s gate |
| `docs/templates/` | when authoring a spec or closing one | the spec and completion templates `authoring-a-spec.md` and `completion-ritual.md` start from |
| `docs/security-baseline.md` | before touching a scanner or a suppression | every shipped scanner finding and its written disposition |
| `docs/transition_plan.md` | before auth, provisioning or LF work | the client-environment transition |
| `docs/design/` | before changing visual language | the design system and the breakpoint reference |
