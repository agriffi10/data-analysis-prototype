# Authoring a spec


Specs are written from `docs/templates/spec-template.md`. **A spec touching lifecycle, IAM or
concurrency is planned with an execution harness rather than a review** — an import-time `_require`
in a shared layer fails at cold start only, and a concurrent-refresh race is a property of two
overlapping executions; neither is findable by reading (`docs/reviewer-contract.md`). What makes a
spec *buildable*:

- **Overview** — user/business intent, no implementation detail. Understandable cold.
- **Scope: In / Out** — explicitly list what's *excluded*, especially anything a reader would
  reasonably assume is included.
- **Functional Requirements** — one FR per discrete, testable behavior, with binary pass/fail
  **Acceptance Criteria** covering happy path, error path, and edges. Sequential IDs so a prompt can
  say "implement FR-001 through FR-003 only."
- **Size: aim for 3–6 FRs, and split above 8.** A spec is one coherent slice of behavior, not a
  feature's whole surface, and a spec past eight is not a big spec — it is a spec that should have
  been two. (Measured once, when this rule landed on 2026-08-31: the median spec carried 6 FRs and
  four in five carried 8 or fewer. A dated observation, not a standing claim about the corpus — `completion-ritual.md`
  forbids a rule resting on a number that rots.) The 3–6 aim sits at or below that median
  deliberately: it is where the method is going, not where it already is. Growing one spec is the
  wrong repair; the right one is a second spec beside it, with the pair's build order recorded in
  `ARCS.md` as an **arc** (`spec-lifecycle.md`). Splitting keeps paying off past the first cut — a three-spec arc
  reads better than one fourteen-FR spec, and each piece earns its own reviewed plan, its own
  review gate and its own delivery doc. Cut along a seam the system already has — a plane, a
  surface, a switchover, the point where something inert goes live — never at "FR-009, because that
  is where the count ran out." **The second spec restarts at FR-001**: IDs are spec-local, which is
  why a dependency cites them as "SPEC-111 FR-001" and never as a number on its own.
- **The ceiling is a ratchet, not a per-spec fail.** `validate_docs.py` holds the *number of specs*
  above 8 at the level it was measured at, in the same shape as every other budget in that file: a
  new over-size spec fails CI, the ones that predate the rule do not, and splitting one lowers the
  constant in the same PR. The number lives in `SPEC_OVERSIZE_MAX` and is deliberately not repeated
  here — two hand-synced copies of one number is how they drift (`session-rhythm.md`). A genuinely indivisible spec
  can still sit above the line, but it is paid for out of the ratchet, which means **raising
  `SPEC_OVERSIZE_MAX` by one in the same PR**, the way `CLAUDE_MAX_BYTES` was raised: a deliberate,
  argued edit rather than a reflex. Say why in one line under *Scope → In Scope*, and it is the
  reviewer's call to accept or reject — "it is all one feature" is the claim to be most skeptical
  of, because it is what every over-scoped spec says about itself.
- **Data Model / Interface Contract** — TypeScript shapes, not prose. Explicit types produce
  better-typed output. Note the target path (`src/types/…`).
- **Implementation Phases** — each phase is one session's worth of work and maps to a discrete,
  reviewable unit. Phases are the input to the implementation plan generated at build time (`session-rhythm.md`); don't
  bake per-phase checkpoints into the spec.
- **No Open Questions.** Resolve every decision while authoring — a spec doesn't move to Draft-ready
  with unanswered questions. Issues that only surface during the build are handled in-session (`session-rhythm.md`),
  not parked in the spec. `validate_docs.py` refuses an `Open Questions` or `Checkpoint` heading in a
  live spec, and that check is easy to pass while failing: **an Open Question can wear a declarative
  sentence.** SPEC-205 shipped *"either the exception moves to a shared location or `save_members`
  returns a refusal the caller raises. The spec states which"* — and then did not. A sentence that
  **promises a decision** is an Open Question with a declarative shape; so is an acceptance criterion
  demanding a **computed** bound while supplying none of its inputs. Both were caught by an
  implementer who had to pick, and neither by a reader.
- **Then the reviewer gate** (`session-rhythm.md`, *The reviewer contract*). A freshly-authored spec goes to a
  fresh-context reviewer before it is Draft-ready, and its findings are fixed or answered.
  The commonest thing this catches is not a wrong requirement — it is an acceptance criterion that
  cannot fail, an Out of Scope bullet that an FR quietly needs, or two FRs that cannot both hold
  (`docs/reviewer-contract.md`, *Adjudicating two FRs that cannot both hold*).
