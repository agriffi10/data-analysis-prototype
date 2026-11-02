---
type: Decision
title: "A guard is retired by proving its replacement, then deleting (SPEC-214)"
description: "**Retire a guard by PROVING its replacement, then deleting** — the matrix reasoned about a table; the image RUNS every handler. Absence is what the API ANSWERS: a destroy of the wrong names deletes nothing and looks finished."
---

The retired `lambdas/test_deploy_matrix.py` was the only thing standing between a missing layer and a
production `ModuleNotFoundError`. It worked by **joining two tables**: the function list said which
functions existed, the layer table said which layers each needed, and the test asserted the join was
consistent. It never ran a single import.

The container image replaced it with something categorically different: `lambda-image-matrix.sh`
imports **every** function's handler module **inside the built image**, through the runtime's own
bootstrap. That is stronger for a reason worth naming — it runs the code rather than reasoning about
a description of it. The old guard could only catch a disagreement between two files a human
maintained; it was blind to anything true of the artefact but absent from the tables, which is the
half that actually breaks.

**The ordering is the whole safety argument, and it is not reversible.** SPEC-212 shipped the
replacement and proved it covered all 86 functions; SPEC-213 put every function on the image; only
then did SPEC-214 delete the tables, the build script and the join. Deleting first and proving after
would have left a window with no guard at all, and — because the risk here is *absence* — nothing to
read in a review. A review samples what is present. It cannot sample what is gone.

**What that ordering cost, twice, and what it teaches.**

Two defects in this arc came from the same blind spot, and neither was about the guard that was
named.

**A disposition can be true of the END state and false where you stand.** PR 2a removed a guard
reasoning "there is no list any more" — true of the arc's end, false at that commit, and it opened a
real window. The question to ask of every removal is not "is this unreachable when the spec is
done" but "is it unreachable **at this commit**".

**Ask what a removed declaration was holding INCIDENTALLY.** The layer table's stated job was to say
which layers a function needed. It was also, silently, pinning "exactly one directory publishes flat
modules" — nothing said so, and deleting it let a planted `table-builder-common/config.py` shadow
`shared-space-common`'s `config` for all 86 functions behind a green suite and a green image matrix.
`assemble.shared_layout` now refuses that.

The destroy inherited the same lesson in a third form. The layer table was **also** the only
enumeration of the ten published layer names: Terraform declares eight, and `control-plane-common`
and `table-builder-common` appear in no local and no output. A destroy list derived from Terraform —
the obvious source, and the one the work was first pointed at — would have stranded 253 of 923
versions while every assertion passed over the eight it did reach.

**The fences the destroy earned.**

- **Absence is what the API answers, not what you assume it answers.** The sweep's proof of a
  destroyed layer was first written to catch `ResourceNotFoundException`. AWS does not raise it: a
  layer that does not exist answers `{"LayerVersions": []}`. That guard would never have fired while
  reading as coverage. Measured against the live service, not inferred from the documentation.
- **Deleting nothing must not look like deleting everything.** An absent layer and a just-emptied
  one are the same answer, so a wrong project or environment sweeps ten layers that do not exist,
  finds no survivors and exits 0. The IAM grants do not contain this — every layer grant wildcards
  the environment segment — so containment had to come from the artefact: `apply` requires the
  version count the report printed, re-checked against the live total. Supplying that number is
  impossible without having run the report, which makes report-before-apply a **gate** rather than an
  instruction in a header comment.
- **A one-shot destroy states what it did NOT prove.** The job proves the ten named layers empty. It
  cannot enumerate the account — the deploy role holds no `lambda:ListLayers` — so completeness rests
  on the grant history plus an account-wide listing from another identity, recorded before and after.

## History

### 2026-09-03

- **Settled:** SPEC-214.
