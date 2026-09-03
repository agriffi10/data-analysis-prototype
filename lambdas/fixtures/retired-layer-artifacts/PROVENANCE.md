# The retired layer machinery, captured verbatim

These are the real artifacts the container-Lambdas arc deleted, at their last revision before
deletion. They are **fixtures, not code** — nothing imports or runs them.

`lambdas/test_no_layer_references.py` asserts its patterns find a hit on a **non-comment** line of
every file here. That is the point: the gate is written to forbid exactly this machinery coming
back, and three successive versions of it each passed over a real form of it —

- v1 read prose and IAM but not code: over `destroy_lambda_layers.py` it hit three lines and all
  three were docstrings, so a copy with its comments stripped would have passed.
- v2 added the boto3 and CLI spellings, and still scored **zero** on `lambda-layers.json` (a JSON
  key's closing quote sits between the name and the colon) and **zero** on `deploy-lambda.sh`
  (the attach is `--layers`, which no pattern named).

Each round widened a pattern and the next round found another form. Widening again is the wrong
move; being pinned against the machinery itself is the right one, because these files cannot drift
from what a layer reference actually looks like — they ARE what it looked like.

Vendored rather than read from git because `actions/checkout` is shallow in CI, so a test doing
`git show <sha>:<path>` passes locally and fails there.

Every file carries a trailing `.txt` so no linter or scanner reads it as this repository's source.

| File | Captured from |
|---|---|
| `lambda-layers.json.txt` | `edd50980^:.github/lambda-layers.json` |
| `build-layer.sh.txt` | `edd50980^:.github/scripts/build-layer.sh` |
| `deploy-lambda.sh.txt` | `8c39967e^:.github/scripts/deploy-lambda.sh` |
| `destroy_lambda_layers.py.txt` | `77a9a1ed^:.github/scripts/destroy_lambda_layers.py` |
