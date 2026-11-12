---
type: Decision
title: "IaC"
description: "OpenTofu is the IaC tool (over CDK, Pulumi and SST). **A module is one architectural concept, and the root composes them flat**: a concept built once is a module the root calls once, a concept built more than once is a **building block** the root calls once per instance (`control-plane` ×8), and the root passes every dependency in as a constructed string. A plane's own configuration lives with its call (`infra/plane-<slug>.tf`, `infra/planes/<slug>/`). **A building block's inputs are what varies between its callers, found by diffing resolved values** — reading the HCL text misses a value hidden behind a local. **A refactor moves; it never recreates**: every changed address gets a `moved` block in `infra/moved.tf`, and the PR's plan showing only moves is the proof. IAM policies are `.tftpl` templates rendered with `templatefile()`."
---

OpenTofu (over CDK/Pulumi/SST). IAM policies are `.tftpl` templates rendered with `templatefile()`.

**The module rule follows HashiCorp's module guidance** (developer.hashicorp.com/terraform/language/modules/develop,
and its *composition*, *structure* and *refactoring* pages; OpenTofu's agree):

- **A module raises the level of abstraction around one concept.** It is not a thin wrapper around
  one resource type — if it cannot be named without repeating the resource it wraps, use the
  resource. That is why there is no private-bucket module: the seven buckets share four short
  resources and differ in everything else.
- **Composition is flat.** The root calls each module and passes its dependencies in, rather than
  modules nesting modules that create what they need. `docker-lambda` is the one module that is
  ever nested — under the building blocks and under the single-concept modules that deploy a
  function — and it is a utility every function in the fleet goes through.
- **A concept built more than once is a building block.** The eight control planes were eight
  copies of one machine; they are now eight calls to `infra/modules/control-plane`, each carrying
  only what is distinct about its plane. The traps the copies asked every author to remember — a
  hand-kept function map in the definition, a ceiling that needs its `TIMED_OUT` rule — are
  structure in the module instead.
- **A building block's inputs are derived, not designed.** Each is an argument whose resolved
  value differs between today's callers; an argument that never varies is a literal. Two spec
  review rounds found values the designed interface could not carry (an inline policy's name, a
  DLQ's deduplication, a rule's wording, a child-execution wildcard hidden behind a local), each a
  ForceNew or an update the plan would show. Diffing the HCL text could not have found the last
  one, which is why the diff is over resolved values.
- **A refactor moves, and the plan proves it.** Every changed address gets a `moved` block in
  `infra/moved.tf`, kept until every state that predates it has applied it. A `moved` block whose
  `from` is not in state is tolerated silently, so the proof is the plan showing moves and nothing
  else, never the block's presence.

Do NOT nest a plane-specific module that wraps `control-plane` (three levels, and a wrapper with no
concept of its own); do NOT pass a plane's verbs as a `for_each` over one map of planes (every
module address would move and the fleet derivation would have to evaluate HCL); do NOT give a
building block an input "for flexibility" that no caller's value needs.

## History

### 2026-11-12

- **Rewritten (SPEC-252):** bounded-context modules gave way to one-concept modules composed flat
  from the root. The per-feature modules had become eight copies of the control-plane machine
  (5,254 lines of `.tf` across them); the copies are now one building block and eight root calls.
  The proof the spec requires is the PR's plan showing only moves plus the one deliberate change
  (shared spaces' state machine gets its own role).

### 2026-08-02

- **Settled:** entered the register, as "`infra/modules/` are bounded-context modules
  (app/base/auth/data/analytics)".
