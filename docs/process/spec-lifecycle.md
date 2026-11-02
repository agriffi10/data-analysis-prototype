# The spec lifecycle


Specs move **Draft → In Progress → Completed** (`spec_status` in each spec's frontmatter is the one
home of its status; `docs/specs/index.yaml` is generated from it by `sh scripts/gen-index.sh`).

- **Draft** — written, **reviewed by a fresh-context reviewer (`session-rhythm.md`, *The reviewer contract*)** and
  refined, but **do not build until told.** The user authors spec files incrementally, sometimes well
  ahead of implementation. A Draft spec being in the repo is not a signal to start it. A spec that has
  not been through the gate is not Draft-ready, whatever its frontmatter says.
- **In Progress** — exactly one spec at a time is in flight. Set when you branch to build it.
- **Completed** — merged on green CI, delivery doc written (see `completion-ritual.md`).
- **Superseded** — replaced by another spec, named in `superseded_by`. The file stays.
- **Cancelled** — the work is not being done, or not here. The file stays (every link to it stays
  live) and it stays in the index. A spec cancelled because its work **can only be done in
  another environment** is reduced to a tombstone: why it was cancelled, where the design went, and
  what validating it against the built code found. Successor-account work belongs in
  [`transition_plan.md`](../transition_plan.md), not in a spec — a spec nobody can build is a spec
  whose claims drift with no test to catch them (SPEC-204, 2026-09-01). `validate_docs.py` skips a
  Cancelled spec in the FR-count ratchet for that reason, and only a Cancelled one.

**Arcs.** Related specs are grouped into *arcs* (file-operations, analytics, query-editor UX,
shared-connections, notifications) with an explicit **build order** in each spec's `arc` and
`arc_order` keys, which the index lists, and the reasoning in `docs/specs/ARCS.md`. Build in that order; arcs can have non-obvious dependencies (e.g. 056 before
051). Grouping is a choice; recording the order of a **size split** (`authoring-a-spec.md`) is not — a spec cut for
size always leaves an arc entry behind. An arc is also what an over-scoped spec *becomes*: a spec
that runs past the size ceiling in `authoring-a-spec.md` is cured by a second spec beside it and an arc entry holding
the order, rather than by a longer spec.
