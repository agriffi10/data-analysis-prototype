# Spec: Container Lambdas — Retiring the Layers and the Deploy Tables

**ID:** SPEC-214
**Status:** Completed
**Last Updated:** 2026-09-03
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

- Deleting `.github/lambda-layers.json`, the layer build script and the attach-order loop —
  and `deploy-lambda.sh` whole, with `lambdas/test_deploy_packaging.py`. SPEC-213 removed
  `point-lambda.sh`'s zip branch, so nothing calls that script any more; the suite that
  extracts and RUNS its copy block therefore pins unreachable shell and stays green forever.
  Named here rather than left to be discovered, per SPEC-213's own record of it.
- Deleting or rewriting `.github/lambda-functions.json` — CI's function list becomes a Terraform
  output.
- Deleting `lambdas/test_build_layer.py` and the layer half of `lambdas/test_deploy_matrix.py`.
- Destroying the published layer versions.
- An enumerated record of every guard removed and what now covers it.
- Rewriting the documentation that describes the old split.

### Out of Scope

- **Any change to the image, the module or a function.** If this spec finds it needs one, that is a
  finding to raise — it means SPEC-212's coverage was not total and the deletion is premature.
  **Amended during the build, and the exemption is narrower than it first read.** The build found
  that `lambdas/docker/assemble.py` reads `.github/lambda-layers.json` to lay out `/opt/python`, that
  `lambdas/Dockerfile` copies the table in for it, and that `lambda-image-matrix.sh` derives its
  expectation from it — three consumers this spec named nowhere. So deleting the table is impossible
  without touching the assembler, and the raised finding resolves the other way: the image's
  **content** does not change by one byte — the same seven packages and ten flat modules land on
  `/opt/python` — and what moves is where the assembler reads its input. That is the identical change
  FR-002 already mandates for `test_image_layout.py` ("it is not the image that changes, it is where
  the test reads its expectation"); FR-002 simply did not notice that the assembler reads the same
  file. `assemble.shared_layout()`, the Dockerfile's `COPY` and the matrix's expectation are
  therefore **in scope**. Nothing else about the image is.
- **Merging the domain layers' source directories.** `cpcommon` owns the algorithm and a domain
  layer owns its wording; that separation is a code decision, not a packaging one, and the image
  copying them to one directory does not change it. `docs/decisions/` says do **not** merge them,
  and this spec does not.
- **Changing any import.**
- **The `lambda-artifacts` bucket.** It staged a zip per function and nothing writes to it or reads
  it, so it looks like part of this deletion and is not: its objects are the only copies of the
  artefacts the pre-container fleet ran, which is a separate argument from "the machinery that
  built them is gone". Added during the build because `infra/modules/lambda-artifacts/README.md`
  claimed this spec removed it and the Scope above never said so. **No spec owns its retirement**,
  and that is recorded here rather than left as an unowned resource nobody notices.

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
      test greps for each and fails on a hit. **Lands with FR-004's PR, not with this one, and the
      ordering is forced rather than chosen:** the deploy role's layer grants are the thing that
      destroys the published versions, so they are still declared in
      `infra/modules/base/policies/github-actions-deploy-*.json.tftpl` and the module locals still
      carry the layer names the destroy resolves. A test asserting their absence cannot pass until
      after the destroy has run. Named here because the machinery it would grep is deleted in the
      table's PR, which is exactly when "the layer work is done" starts to read as true.
- [ ] `ruff check lambdas/ scripts/ .github/scripts/` and the blocking `mypy` both pass — neither is
      run by pytest, and both fail only in CI unless run by hand.

### FR-003: CI's function list comes from Terraform

#### Description:

`.github/lambda-functions.json` existed to say which layers a function needed. Its surviving job is
to say which functions exist, and Terraform already knows.

#### Acceptance Criteria:

- [ ] The root module gains one output listing every function name, built from the `docker-lambda`
      module calls.
- [ ] ~~`deploy-lambdas.yml` reads that output and shards over it~~; `.github/lambda-functions.json`
      is deleted. **Amended during the build: it shards over the commit's own static derivation of
      the same Terraform sources, and the output is read by the reconciliation instead.** A
      `tofu output` is **last-applied state**, and `deploy-infra.yml` and `deploy-lambdas.yml` fire on
      the same push with no ordering between them — so a commit that adds a function would shard over
      state that does not yet contain it, never point it, and pass the `planned == pointed`
      reconciliation over it. The function would then run whatever image its module created it with,
      working perfectly on the wrong artefact, which is the un-pointed-function trap this whole arc
      exists to close. The commit's own declaration is what the deleted table provided, so the
      sharding reads that; the output is read by the `pointed` job, comparing what was deployed
      against what is applied, which is a stronger check than the marshalling-only one it replaces.
      Marked in place rather than rewritten, so a reader arriving from the old claim sees the reversal.
- [ ] The root output is still added and still read by CI — no hand-maintained function list survives
      in `.github/`, and Terraform remains the single source of the fleet's membership.
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
- [ ] ~~The deletion runs **after** the functions have been confirmed on the image for at least one
      deploy cycle, so a rollback to a zip-packaged function is still possible until it does.~~
      **Superseded by SPEC-213's final PR, which removed `point-lambda.sh`'s zip branch and made a
      non-`Image` packaging a refusal.** There is no longer a pipeline that can deploy a zip
      function, so the layer versions no longer buy a rollback and the ordering they justified is
      void. What replaces it is a rollback that does exist: point the fleet at a previous sha's
      image, which is a `workflow_dispatch` input and no code change. Marked in place rather than
      rewritten, so a reader arriving from the old claim sees the reversal.
- [ ] The deploy role's now-unused layer grants are removed in the same pass.

### FR-005: The documentation says what actually happens

#### Acceptance Criteria:

- [ ] **The sweep is MECHANICAL, and the command is part of the criterion.** SPEC-213 did this by
      memory and a cross-site review found nineteen further sites — most of them a *second* stale
      paragraph in a file whose first had already been corrected, which is the signature of a sweep
      that fixed what someone remembered. Run
      `grep -rniE 'placeholder|attach|layer|zip|artifacts bucket|lambda-layers' docs/ lambdas/info/ lambdas/*/README.md infra/info/ apps/portal/info/ infra/modules/*/README.md .github/ README.md 2>/dev/null`
      — **corrected during the build.** As first written the command had two paths that match nothing
      in this repository (`*/README.md`, and `CLAIMS.md`, which does not exist) and `*/info/` reached
      only two of the three `info/` trees. It therefore never saw `infra/modules/*/README.md`, **18 of
      which carry a hit**, nor `apps/portal/info/`. A criterion whose command cannot reach the files
      the criterion separately requires is a false clean, which is the exact failure this FR was
      written against.
      **Corrected a SECOND time during the build, and the repeat IS the finding.** Even the
      corrected command could not reach `lambdas/*/README.md` — the per-package READMEs, as
      distinct from `lambdas/info/` — and **both files of that class were stale**:
      `table-share-common/README.md` said its package was "published as the `table-share-common`
      Lambda layer ... and attached to all five verbs by deploy-lambdas.yml", and
      `table-builder-common/README.md` said deploy-lambdas.yml "will publish them as a layer". A
      diff review found them, plus one hit the corrected command DOES reach and the sweep had
      simply missed (`infra/modules/user-directory/README.md`). The command above now appends that
      path. The lesson is that widening it once did not make it complete: a path-glob criterion is
      only as good as the file classes someone thought to enumerate, and the way to find the
      missing class is to ask what the glob CANNOT match, not to re-run it and read the output.
      and dispose of **every** hit as still-true, false-and-fixed, or false-and-marked-as-history.
      A hit left undisposed fails this criterion.

- [ ] `lambdas/info/deployment.md` describes the image split: Terraform owns the function and its
      command, CI owns the image and points every function at it. Its "Layers deploy like code"
      section, its two-deploy-tables section and its "Adding a function" steps are rewritten, not
      appended to.
- [ ] `lambdas/info/shared-layer.md` keeps `cpcommon`'s reasoning — which is about what the module
      holds and why, and is unaffected — and loses only the sentences about layer packaging and
      attach order.
- [ ] `infra/info/control-plane-shape.md` and every module README that describes zip packaging or
      layers is corrected.
- [ ] **`docs/process/ci-and-deploy-traps.md` is corrected too.** It states the fact being retired — "Terraform owns
      the function, CI owns the code and every layer attachment" — and it is an always-referenced
      tier. The claim below about markdown sweeps is about *source-file* pointers being the ones that
      rot unseen; it is not a licence to skip the markdown that states the retired rule.
- [ ] Every `.py` docstring, `.tf` comment and `.yml` step that points at a deleted file is fixed.
      A markdown-only sweep reports the tree clean and would be wrong: the pointers that rot unseen
      are in source files.
- [ ] **The in-image docstrings are DEFERRED, and the count below is WRONG — corrected during the
      build.** The population is **23 files**, not seven: measured with a packaging-claim sweep
      (attached / published-as-a-layer) rather than the bare word "layer". The seven named here are
      all real; sixteen more carry the same class of claim, including every domain package's
      `__init__.py`, `focommon/paths.py`, `dqcommon/messages.py`, `cpcommon/type_mapping.py`,
      `transfer_reader.py` and `api/handler.py`. Three `requirements.txt` files carry it too. They
      landed with the completion PR rather than FR-004's, since FR-004's is an AWS-state change and
      this is documentation; the deferral itself is unchanged, only its size and its destination.
      **One of them was materially false rather than dated:** `type_mapping.py` said importing it
      from a verb without a polars layer is an ImportError at cold start, and the image installs
      polars for every function, so it now succeeds — a quieter failure than the one the comment
      was written to prevent. **Seven `.py` docstrings inside the image are DEFERRED to FR-004's
      PR, and the reason is the one this spec's own amendment gives.** `focommon/authz.py`, `dqcommon/config.py`,
      `dqcommon/__init__.py`, `file_ops_copy_objects.py`, `cpcommon/config.py`,
      `cpcommon/observability.py` and `cpcommon/__init__.py` still describe a layer being attached —
      wording SPEC-213 left behind, not this spec. All seven are copied into the image verbatim, so
      editing them changes its content hash, and the table's PR claims the image does not move by
      one byte and proves it. That claim is worth more than the wording, so the wording waits one
      PR. Written down because PRs 4 and 5 are AWS-state and IAM changes with no other reason to
      open a file under `lambdas/`, and an undeclared deferral is how a half-done sweep reads as a
      finished one. The equivalents that are NOT shipped — `test_layer_import_safety.py`,
      `test_layer_discipline_focommon.py`, `test_fleet_environment.py` — were fixed with the
      table.
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
