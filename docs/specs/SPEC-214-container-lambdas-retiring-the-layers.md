# Spec: Container Lambdas — Retiring the Layers and the Deploy Tables

**ID:** SPEC-214
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-212 (the image and its import smoke test — the replacement guard), SPEC-213 (every function already running the image)

**Arc:** Container Lambdas (212 → 213 → 214). Narrative in `ARCS.md`.

**Interacts with:** SPEC-215, order-independently — FR-003 and SPEC-215 FR-001 each state the
obligation for both orders. This spec also repoints one SPEC-212 test; see FR-002.

## Overview

After SPEC-213 every function runs the container image and no function attaches a layer. What is
left behind is the machinery that made layers work: two JSON tables, a layer build script, a literal
attach-order loop, and the tests that hold them in agreement. All of it is now describing something
that does not happen.

This spec deletes it. That makes this spec's risk **the opposite** of every other spec's: nothing
new is built, so nothing new can be wrong, and the only way to get it wrong is to remove a guard
whose absence nobody notices. `lambdas/test_deploy_matrix.py` is the single thing that has stood
between a missing layer and a production `ModuleNotFoundError`, and deleting it removes real
protection unless something else already provides it.

So the order is fixed and is the whole point: **SPEC-212's per-function import smoke test runs
against the real image and covers every function before anything here is deleted.** This spec's job
is to prove that coverage is total, then remove what it replaced — and to enumerate what it removed,
because a review samples and the risk here is absence.

## Scope

### In Scope

- Deleting `.github/lambda-layers.json`, the layer build script and the attach-order loop.
- Deleting or rewriting `.github/lambda-functions.json` — CI's function list becomes a Terraform
  output.
- Deleting `lambdas/test_build_layer.py` and the layer half of `lambdas/test_deploy_matrix.py`.
- Destroying the published layer versions.
- An enumerated record of every guard removed and what now covers it.
- Rewriting the documentation that describes the old split.

### Out of Scope

- **Any change to the image, the module or a function.** If this spec finds it needs one, that is a
  finding to raise — it means SPEC-212's coverage was not total and the deletion is premature.
- **Merging the domain layers' source directories.** `cpcommon` owns the algorithm and a domain
  layer owns its wording; that separation is a code decision, not a packaging one, and the image
  copying them to one directory does not change it. `docs/decisions/` says do **not** merge them,
  and this spec does not.
- **Changing any import.**

---

## Functional Requirements

### FR-001: The replacement is proven total before anything is deleted

#### Description:

The deletion is conditional on a coverage proof, and the proof is mechanical.

#### Acceptance Criteria:

- [ ] A sweep lists every function directory under `lambdas/`, every module it imports, and whether
      SPEC-212's matrix imports that function's handler. Every function is covered; a gap fails.
- [ ] The sweep is run and its output recorded in the PR **before** any deletion commit — the report
      is read, then the removal happens, in that order.
- [ ] Every assertion `test_deploy_matrix.py` makes is listed, and each is marked as: still needed
      and moved, or made unreachable by the image and named as such. No assertion is unaccounted for.
- [ ] The count of functions the image matrix imports equals the count of functions Terraform
      declares equals the count of function directories. Three numbers, asserted equal.

### FR-002: The layer tables and the build machinery are removed

#### Acceptance Criteria:

- [ ] `.github/lambda-layers.json` is deleted.
- [ ] The layer build script and `deploy-lambda.sh`'s literal attach-order loop are deleted.
- [ ] `lambdas/test_build_layer.py` is deleted.
- [ ] **`lambdas/test_image_layout.py` is repointed, not left to break.** SPEC-212 FR-002 has it
      assert that the packages under `/opt/python` equal "the set the layer table declares", and the
      layer table is the `.github/lambda-layers.json` this spec deletes. Its set-equality guard is
      still wanted — it is what stops the image quietly shipping without a shared package — so its
      expected set is re-derived from the layer **source directories** on disk. This is the one
      change to SPEC-212's artifact that this spec makes, and it is named here because SPEC-212's own
      Out of Scope says a needed image change means the deletion was premature: it is not the image
      that changes, it is where the test reads its expectation.
- [ ] No workflow, script or `.tf` file references a layer version, a layer ARN or a layer name; a
      test greps for each and fails on a hit.
- [ ] `ruff check lambdas/ scripts/ .github/scripts/` and the blocking `mypy` both pass — neither is
      run by pytest, and both fail only in CI unless run by hand.

### FR-003: CI's function list comes from Terraform

#### Description:

`.github/lambda-functions.json` existed to say which layers a function needed. Its surviving job is
to say which functions exist, and Terraform already knows.

#### Acceptance Criteria:

- [ ] The root module gains one output listing every function name, built from the `docker-lambda`
      module calls.
- [ ] `deploy-lambdas.yml` reads that output and shards over it; `.github/lambda-functions.json` is
      deleted.
- [ ] If SPEC-215 has landed, this workflow reads the output through **its** resolver rather than
      writing a second `tofu init` + `tofu output -json` step. It still joins SPEC-215 FR-001's
      version agreement, because that predicate is "declares an OpenTofu version" and not "runs
      `tofu init`" — a workflow that uses the resolver still pins the toolchain it runs, and an
      init-based predicate would have excluded exactly this workflow.
- [ ] If SPEC-215 has **not** landed, this spec adds the read directly and SPEC-215 folds it into the
      resolver when it lands. Both specs state this obligation; neither leaves it to the other.
- [ ] The shard computation covers the whole list — a test asserts the union of the shards equals
      the function list, so a sharding bug cannot silently skip a function.
- [ ] A function added to Terraform is deployed with no further edit anywhere; a test asserts no
      hand-maintained function list survives in `.github/`.

### FR-004: The published layer versions are destroyed

#### Acceptance Criteria:

- [ ] Every layer version published by the old pipeline is deleted, and the deletion is done in CI
      rather than from a laptop — the deploy role holds the grant and a local identity does not.
- [ ] The deletion runs **after** the functions have been confirmed on the image for at least one
      deploy cycle, so a rollback to a zip-packaged function is still possible until it does.
- [ ] The deploy role's now-unused layer grants are removed in the same pass.

### FR-005: The documentation says what actually happens

#### Acceptance Criteria:

- [ ] `lambdas/info/deployment.md` describes the image split: Terraform owns the function and its
      command, CI owns the image and points every function at it. Its "Layers deploy like code"
      section, its two-deploy-tables section and its "Adding a function" steps are rewritten, not
      appended to.
- [ ] `lambdas/info/shared-layer.md` keeps `cpcommon`'s reasoning — which is about what the module
      holds and why, and is unaffected — and loses only the sentences about layer packaging and
      attach order.
- [ ] `infra/info/control-plane-shape.md` and every module README that describes zip packaging or
      layers is corrected.
- [ ] **`docs/process.md` §6 is corrected too.** It states the fact being retired — "Terraform owns
      the function, CI owns the code and every layer attachment" — and it is an always-referenced
      tier. The claim below about markdown sweeps is about *source-file* pointers being the ones that
      rot unseen; it is not a licence to skip the markdown that states the retired rule.
- [ ] Every `.py` docstring, `.tf` comment and `.yml` step that points at a deleted file is fixed.
      A markdown-only sweep reports the tree clean and would be wrong: the pointers that rot unseen
      are in source files.
- [ ] `scripts/validate_docs.py` passes, and it is run by every reviewer of this change.

### FR-006: What was removed is written down once, as a lesson

#### Description:

Most rejected findings are worth a sentence out loud and nothing more. This one is worth writing
down, because the removed guard was load-bearing and the reason it could go is non-obvious.

#### Acceptance Criteria:

- [ ] A `docs/decisions/` entry records that the deploy matrix's import-join was replaced by an
      import executed inside the artifact, that the replacement is stronger because it runs the code
      rather than reasoning about it, and that the ordering — prove, then delete — is what made the
      removal safe.
- [ ] CLAUDE.md's Key Decisions gains a clause in the infrastructure area, replacing the layer
      clauses it supersedes rather than being appended beside them.
- [ ] The arc's row in `docs/architecture.md`'s Architecture Decision Record is added: a mechanism
      was swapped, which is one of the few things that qualifies.

---

## Data Model

Not applicable. This spec deletes; the only artifact it produces is the coverage report in FR-001
and the register entry in FR-006.

## File & Folder Structure

```
.github/
├── lambda-layers.json          ← DELETED
├── lambda-functions.json       ← DELETED
└── scripts/                    # the layer build + attach-order loop removed

lambdas/
├── test_build_layer.py         ← DELETED
├── test_deploy_matrix.py       ← the layer join removed; whatever survives, survives named
└── info/deployment.md          # rewritten

infra/
├── outputs.tf                  # the function-name list output
└── modules/base/policies/      # the layer grants removed
```

## Implementation Phases

### Phase 1: Prove the coverage

- The three-way count assertion and the per-function coverage sweep.
- The itemised disposition of every `test_deploy_matrix.py` assertion.
- Recorded in the PR before a single deletion.

### Phase 2: Move CI onto the Terraform output

- The function-name output, the workflow's read, the shard-union assertion.
- Delete `.github/lambda-functions.json`.

### Phase 3: Delete the layer machinery

- The tables, the build script, the attach loop, `test_build_layer.py`, the layer half of the matrix.
- The reference greps; ruff and mypy.

### Phase 4: The layer versions, the docs and the register

- Destroy the published layer versions in CI; remove the deploy role's layer grants.
- Rewrite `deployment.md`, `shared-layer.md`, `control-plane-shape.md` and the module READMEs.
- The source-file pointer sweep; `validate_docs.py`.
- The register entry, the Key Decisions clause and the ADR row.
