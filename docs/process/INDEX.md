# The Spec-Driven Development Process

How work gets done in this repo. `CLAUDE.md` carries the terse, always-loaded rules; this directory
is the fuller **method** they point to, and it is the contract `CLAUDE.md` only summarises. It is a
router and one file per part, so a session loads the part every session needs and pulls the rest at the moment it is used.
**Read this file and `session-rhythm.md` at the start of every session, before any other doc** —
`CLAUDE.md`'s Session Workflow says the same.

Goal: each feature is **specified before it's built**, built in **reviewable phases** off a
**reviewed plan**, landed as **as few PRs on green CI as the dependencies allow**, and recorded in
**lean, layered docs** so the next session starts cheap.

## Loaded every session

The always-loaded set is stated here, and `validate_docs.py` reads it from this table.

| File | Authoritative for |
|---|---|
| `CLAUDE.md` | conventions, the Key Decisions router, the session workflow |
| `docs/process/INDEX.md` (this file) | the router to the method, and the context discipline |
| `docs/process/session-rhythm.md` | how a session runs — the gates on starting, the build, the reviews, landing |

## The method, one file per part

| File | Holds | Pull it |
|---|---|---|
| [`where-truth-lives.md`](where-truth-lives.md) | which doc is authoritative for what, by tree and across trees | when looking for which doc owns a subject |
| [`spec-lifecycle.md`](spec-lifecycle.md) | Draft → In Progress → Completed → Cancelled, and arcs | when a spec changes status |
| [`session-rhythm.md`](session-rhythm.md) | start of session, the build, the reviewer gate, landing | **every session** |
| [`authoring-a-spec.md`](authoring-a-spec.md) | what makes a spec buildable, and the size ceiling | when writing or splitting a spec |
| [`completion-ritual.md`](completion-ritual.md) | the close-out pass, and the anti-regrowth rules for docs | when a spec closes, or a doc changes shape |
| [`knowledge-layout.md`](knowledge-layout.md) | frontmatter, the generated indexes, the register's rules | when adding a decision or rulebook |
| [`ci-and-deploy-traps.md`](ci-and-deploy-traps.md) | what only bites in CI or on deploy | before touching CI, a workflow or a deploy |
| [`ground-rules.md`](ground-rules.md) | the project facts that shape the process | when orienting in a part of the system you have not touched, beside `architecture.md` |
| [`several-agents.md`](several-agents.md) | the PR queue: the four commands, where the LIVE queue is and why a bare install builds a second one, what the hook refuses; the model every agent runs on | before getting in line, before any re-install, and before delegating |

## Path-scoped rules are a backstop, not the instruction

`.claude/rules/decisions-<area>.md` carries one rule per Key Decisions area: a `paths:` list and a
pointer to that area's fences, nothing more. A rule fires when a matching file is opened with the
Read tool and not on a shell read (the measurement is beside `check_rules` in `validate_docs.py`),
so the instruction in `CLAUDE.md` to read an area's fences first is the primary path and the rule
is the nudge for a session that reached the code another way.

**Context discipline (session-start token cost is a standing concern):**
- Read **only the current spec** in full.
- **Never** read an `index.yaml`, `ARCS.md`, a plane page or a delivery doc whole — pull your area's
  block or the one entry you need. Each is built so that is possible. `architecture.md` is the exception: it is
  sized to be read whole, and it is the cheapest way into a part of the system you have not touched.
- The inventories and the Lambda index are **routers**: read the row, then the one file it names.
- Delegate a *dependency's* delivery-doc reading to a subagent brief rather than loading it
  into the main loop.
