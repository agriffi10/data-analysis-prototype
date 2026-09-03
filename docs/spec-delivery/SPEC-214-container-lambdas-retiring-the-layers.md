# SPEC-214 — Container Lambdas: retiring the layers and the deploy tables

**Status:** Completed · **Arc:** Container Lambdas (212 → 213 → 214)

## What shipped

The machinery that made Lambda layers work is gone, in the repository and in AWS. Nothing new was
built: this spec is a deletion, and its whole risk was removing a guard nobody would miss.

| PR | What came out |
|---|---|
| #626 | The fleet's membership derived from the Terraform sources (`fleet.py`), proved against the table it replaced |
| #627 | `.github/lambda-functions.json` — CI reads the fleet from Terraform |
| #628 | `.github/lambda-layers.json`, the layer build script, `deploy-lambda.sh`, `test_build_layer.py`; the assembler now derives `/opt/python` from the `lambdas/*-common/` directories |
| #629 | The 923 published layer versions destroyed, in CI |
| #631 | The deploy role's layer grants, 8 locals, 7 outputs, and the one-shot that spent them |

## What replaced the guard, and why the order mattered

`lambdas/test_deploy_matrix.py` was the only thing between a missing layer and a production
`ModuleNotFoundError`. It **joined two JSON tables** and never ran an import. The image's matrix
imports every function's handler **inside the built image**, through the runtime's own bootstrap —
it runs the code rather than reasoning about a description of it.

The ordering is the safety argument and it is not reversible: SPEC-212 proved the replacement covered
all 86 functions, SPEC-213 put every function on the image, and only then did this spec delete. The
risk of a deletion is **absence**, and a review samples what is present.

## The destroy

923 versions across ten layers, run from CI because the deploy role held `DeleteLayerVersion` and a
local identity did not. `report` mode first, read, then `apply`.

Proved gone **positively** and account-wide: `aws lambda list-layers` from an admin identity returned
10 layers before and **0** after, with no pagination marker on either.

Three things about it are worth carrying:

- **Terraform was not a usable source for the names.** It declared eight of the ten as layer-name
  locals; `control-plane-common` existed only as a wildcard ARN pattern in a deploy policy and
  `table-builder-common` nowhere at all. A Terraform-derived list would have stranded 253 versions
  while every assertion passed over the eight it reached.
- **Absence is zero versions, not an exception.** The live API answers a missing layer
  `{"LayerVersions": []}` and raises nothing. A first version keyed its absence proof on
  `ResourceNotFoundException` — a guard that would never have fired while reading as coverage.
- **Deleting nothing must not look like deleting everything.** A wrong project sweeps ten layers
  that do not exist, finds no survivors and exits 0. The IAM grants do not contain that, since every
  layer grant wildcarded the environment segment, so `apply` carries the count its own report found
  — and that count must be positive, because a wrong name set reports zero and `0 == 0` would pass.

## What is left behind deliberately

`lambda-artifacts` — the bucket that staged the zips. Nothing writes to it or reads it, and **no spec
owns its retirement**. Its objects are the only copies of the artefacts the pre-container fleet ran,
which is a separate argument from "the machinery that built them is gone".

## The guard that replaces the grep

`lambdas/test_no_layer_references.py` fails on six forms in any workflow, script or Terraform file:
a layer ARN, a layer IAM action, a layer API call, a layer-name declaration, a Terraform layer
declaration, and a project-and-environment-qualified layer name.

It took three rewrites, and each rewrite is the lesson: it read **prose and IAM but not code** (run
over the destroy script it forbids, it hit three lines, all docstrings); its IAM pattern held **four
of the nine** layer actions; and it watched every way of *managing* a layer and **none of the ways of
declaring one**. The bare layer suffix is deliberately not a pattern — eight of the ten names are
also `lambdas/*-common/` source directory names.
