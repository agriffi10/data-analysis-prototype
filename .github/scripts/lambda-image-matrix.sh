#!/usr/bin/env bash
# The Lambda image's behaviour matrix. It asserts the one thing no other suite in this repository
# can: that every function's handler module IMPORTS, inside the built artefact, under the runtime
# that will run it.
#
# NOTHING ELSE SEES THIS. pytest puts every layer root on sys.path by design, so every import that
# would fail in Lambda succeeds under test. `update-function-code` succeeds against a function that
# raises ModuleNotFoundError at cold start. Both were green while sign-up was broken for nine days.
#
# IT RUNS THE IMAGE, IT DOES NOT READ IT. Every assertion below is measured inside a container
# started from the image under test, through the Runtime Interface Emulator that ships in the AWS
# base image — so `sys.path` is the one `/var/runtime/bootstrap` builds, not one this script
# reconstructed. A reconstructed path that is a superset of the real one passes an import that
# production fails, which is this arc's own failure mode rebuilt by its own tooling.
#
# THE EXPECTATIONS ARE HOST-SIDE AND THE OBSERVATIONS ARE IMAGE-SIDE, deliberately. The sweep
# inside the container cannot see the repository, so it returns data and this script decides what
# the numbers have to be. That is what makes the count assertion meaningful: two independent
# derivations of "how many Lambdas are there" compared against each other, rather than one number
# compared with itself.
#
# Usage: lambda-image-matrix.sh <image-ref>
set -uo pipefail

IMAGE="${1:?usage: lambda-image-matrix.sh <image-ref>}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../.." && pwd)"
SWEEP="${HERE}/lambda-image-sweep.py"
PORT=18100
NAME="lambda-image-matrix-$$"

# The environment a deployed function always has. NOT a workaround for a broken image: the Lambda
# runtime sets AWS_REGION on every invocation, and Terraform sets the rest, so a sweep run without
# them would be testing a state that never occurs. The values are deliberately fake and obviously
# so. The agreement between this list and what the fleet reads at import is asserted by the Python
# suite, which can parse both — the same split spa-image-matrix.sh uses for its REQUIRED_ENV.
# THE CONTAINER RUNS THE WAY LAMBDA RUNS IT: a read-only root with a writable /tmp, which is the
# filesystem a deployed function is given. That is not decoration, and it is not only fidelity —
# it is what makes the "no __pycache__" assertion below mean anything. Importing 86 modules writes
# bytecode beside every one of them, so on a writable root the sweep manufactures the exact
# offenders it then reports, and the check fails against artefacts the test created rather than
# against the image. Measured: the shipped image is clean and the same sweep on a writable root
# reports twelve __pycache__ directories.
RUNTIME_FLAGS=(
  --read-only
  --tmpfs /tmp:rw,exec,mode=1777
)

FIXTURE_ENV=(
  -e AWS_REGION=us-east-1
  -e AWS_DEFAULT_REGION=us-east-1
  -e PORTAL_ROLE_ARN=arn:aws:iam::000000000000:role/matrix-fixture-portal-role
  # The emulator's own default is one second, which is not enough to import polars once, let
  # alone to walk the fleet.
  -e AWS_LAMBDA_FUNCTION_TIMEOUT=900
)

FAILURES=0
CHECKS=0

pass() { CHECKS=$((CHECKS + 1)); printf '  ok   %s\n' "$1"; }
fail() {
  CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1))
  printf '  FAIL %s\n' "$1"
  [ $# -gt 1 ] && printf '       %s\n' "$2"
  return 0
}

# Every comparison below is between two DERIVED values, and two derived values that are both
# empty are equal. A guard that cannot tell "matched" from "found nothing" is the failure this
# whole file exists to prevent, so nothing is compared before it is known to be non-empty.
check_eq() {
  local label="$1" actual="$2" expected="$3"
  if [ -z "$actual" ]; then
    fail "$label" "read nothing — the probe found no value, which is not the same as a match"
  elif [ "$actual" = "$expected" ]; then
    pass "$label"
  else
    fail "$label" "expected [$expected], got [$actual]"
  fi
}

# Removes THIS run's container, and any left behind by an earlier one. The prefix sweep is not
# tidiness: a stale container still holds the port, and the only symptom is `docker run` failing
# with a message about the port that the caller never sees. On a CI runner there is never one; on
# a laptop, after an interrupted run, there always is.
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  local stale
  stale=$(docker ps -aq --filter "name=lambda-image-matrix-" 2>/dev/null || true)
  [ -n "$stale" ] && docker rm -f $stale >/dev/null 2>&1
  return 0
}
trap cleanup EXIT

echo "Lambda image matrix: ${IMAGE}"

# ── What the repository says, computed before the container starts ─────────────
# The layer table is the declaration of what shared code exists. TERRAFORM is the declaration of
# how many Lambdas there are — and it is deliberately not the AST sweep the assembler uses.
#
# THAT CHOICE IS THE DIFFERENCE BETWEEN A GUARD AND A TAUTOLOGY, and it was measured rather than
# reasoned about. The image-side sweep decides "is this a Lambda" by looking for a top-level
# `handler`. An earlier version of this script computed the expected count the same way, from the
# same source tree — so renaming a function's `handler` removed it from BOTH sides at once, the
# two numbers agreed at 85, and a planted mutation that broke a function's entry point passed the
# whole matrix. The table is maintained separately and still says 86, so the shortfall is visible.
# `lambdas/test_image_layout.py` is what keeps the Terraform declaration and the directories
# honest with each other; this script leans on that rather than repeating it.
#
# THAT REPOINT HAS NOW HAPPENED, and it honoured the instruction above. The function count comes
# from `lambdas/fleet.py`, which reads the fleet out of the Terraform that DECLARES it — a
# derivation maintained separately from the tree, exactly as the table was. It is deliberately NOT
# `tofu output`: this job runs on pull requests with no AWS credentials at all.
EXPECTED=$(python3 - "$REPO" <<'PY'
import json, pathlib, sys

repo = pathlib.Path(sys.argv[1])
table = json.loads((repo / ".github" / "lambda-layers.json").read_text())
packages = sorted(pathlib.Path(e["package"]).name for e in table if e.get("package"))
flat = sorted(m for e in table if e.get("sourceDir") for m in e.get("modules", []))

sys.path.insert(0, str(repo / "lambdas"))
import fleet

print(json.dumps({"packages": packages, "flat": flat, "functions": len(fleet.function_names(repo))}))
PY
)
if [ -z "$EXPECTED" ]; then
  echo "  FAIL could not read the repository's layer table, or could not derive the fleet from" >&2
  echo "       its Terraform — a refusal there is deliberate and is never an empty expectation." >&2
  exit 1
fi
EXPECTED_PACKAGES=$(jq -r '.packages | join(" ")' <<<"$EXPECTED")
EXPECTED_FLAT=$(jq -r '.flat | join(" ")' <<<"$EXPECTED")
EXPECTED_FUNCTIONS=$(jq -r '.functions' <<<"$EXPECTED")

# A repository that appears to hold no Lambdas would make every count assertion below pass. That
# is the shape of a sweep that silently stopped finding anything, so it is refused here.
if [ "${EXPECTED_FUNCTIONS:-0}" -lt 30 ]; then
  echo "  FAIL only ${EXPECTED_FUNCTIONS} functions declared on the host — the read that" >&2
  echo "       computes the expected count has stopped working, and every comparison against it" >&2
  echo "       would pass vacuously." >&2
  exit 1
fi

# ── The image's own declaration, read without running it ──────────────────────
# Config, not behaviour, so it is the one thing read from the image rather than measured inside it.
DECLARED_CMD=$(docker image inspect "$IMAGE" --format '{{json .Config.Cmd}}' 2>/dev/null)
if [ "$DECLARED_CMD" = "null" ] || [ "$DECLARED_CMD" = "[]" ]; then
  pass "the image declares no CMD, so a function that forgot its command cannot start"
else
  fail "the image declares no CMD" "it declares ${DECLARED_CMD}; every function supplies its own"
fi

# ── Run it, and ask it what it is ─────────────────────────────────────────────
# Through the emulator, with the sweep mounted read-only into the task root. A single-file mount
# adds the module without hiding the directory it sits in, and nothing here is baked into the
# image that ships.
cleanup
# Docker's own error is REPORTED, not swallowed. "could not start a container" is true of a
# missing image, a bad platform and a port already bound, and only one of those is the image's
# fault — a matrix that cannot say which sends the reader to the wrong place.
if ! START_ERROR=$(docker run -d --name "$NAME" --platform linux/amd64 -p "${PORT}:8080" \
      -v "${SWEEP}:/var/task/_matrix_sweep.py:ro" \
      "${RUNTIME_FLAGS[@]}" "${FIXTURE_ENV[@]}" \
      "$IMAGE" _matrix_sweep.handler 2>&1 >/dev/null); then
  echo "  FAIL could not start a container from ${IMAGE}" >&2
  echo "       ${START_ERROR}" >&2
  exit 1
fi

# WAIT FOR THE LISTENER, NEVER BY INVOKING. The emulator serves ONE invocation at a time and
# initialises lazily on the first one, so a readiness probe that posts to the invocation endpoint
# starts the real sweep, times out on its own deadline, and leaves the retry to collide with the
# run it just started — `ReserveFailed: AlreadyReserved`, and the emulator panics. Measured, and
# it cost this script its first run. Any HTTP response on any path proves the port is serving; an
# unknown path answers 404, which is exactly the signal wanted and is why `-f` is absent here.
for _ in $(seq 1 30); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:${PORT}/" 2>/dev/null)
  [ -n "$code" ] && [ "$code" != "000" ] && break
  sleep 1
done
if [ -z "${code:-}" ] || [ "${code:-000}" = "000" ]; then
  echo "  FAIL the emulator never started listening on port ${PORT}." >&2
  docker logs "$NAME" 2>&1 | tail -30 >&2
  exit 1
fi

# UNDER THE JOB'S OWN CEILING, deliberately. The PR gate allows fifteen minutes total and the
# checkout, the build and the readiness loop all precede this — so a deadline equal to the job's
# can never be the one that fires, and a hung invocation surfaces as GitHub's generic timeout
# instead of the diagnostic below.
REPORT=$(curl -fsS --max-time 480 -XPOST \
  "http://localhost:${PORT}/2015-03-31/functions/function/invocations" -d '{}' 2>/dev/null)

# A sweep that could not run is not a sweep that found nothing. Both halves are checked: the call
# has to return, and what it returns has to be this sweep's report rather than the emulator's
# error envelope.
if [ -z "$REPORT" ] || ! jq -e '.handler_count' >/dev/null 2>&1 <<<"$REPORT"; then
  echo "  FAIL the sweep did not run inside the image — 'did not run' is never 'clean'." >&2
  echo "$REPORT" | head -c 2000 >&2
  echo >&2
  docker logs "$NAME" 2>&1 | tail -30 >&2
  exit 1
fi

# ── The interpreter ───────────────────────────────────────────────────────────
check_eq "the interpreter is python3.12" "$(jq -r '.python' <<<"$REPORT")" "3.12"

# ── The search path the imports actually ran under ────────────────────────────
# Not an assertion about a reconstruction — there is none — but about the two paths agreeing, so
# a subprocess that quietly saw MORE than the runtime cannot pass an import the runtime fails.
RUNTIME_HEAD=$(jq -r '.runtime_path[0:3] | join(" ")' <<<"$REPORT")
check_eq "the runtime puts the task root and both layer paths first" \
  "$RUNTIME_HEAD" "/var/task /opt/python/lib/python3.12/site-packages /opt/python"

# THE ABSENT PATH IS CHECKED BEFORE THE COMPARISON, and that order is the point. The sweep
# returns null here whenever its observation subprocess exits non-zero, and `null // []` is an
# empty list — which subtracts to nothing and reads as "the subprocess added nothing". A probe
# that found no value is not a match, which is the rule the rest of this file applies through
# check_eq and which this comparison sits outside of.
if ! jq -e '.subprocess_path | type == "array"' >/dev/null <<<"$REPORT"; then
  fail "each import ran on the runtime's own search path" \
       "the sweep could not report the path its subprocesses saw, so the comparison has no left-hand side"
else
  EXTRAS=$(jq -r '.subprocess_path - .runtime_path | join(" ")' <<<"$REPORT")
  if [ -z "$EXTRAS" ]; then
    pass "each import ran on the runtime's own search path, with nothing added"
  else
    fail "each import ran on the runtime's own search path" "the subprocess also saw: ${EXTRAS}"
  fi
fi

# ── /opt/python is what a layer provides, and only that ───────────────────────
check_eq "/opt/python holds exactly the layer table's packages" \
  "$(jq -r '.opt_packages | join(" ")' <<<"$REPORT")" "$EXPECTED_PACKAGES"
check_eq "/opt/python holds exactly the flat layer's declared modules" \
  "$(jq -r '.opt_flat_modules | join(" ")' <<<"$REPORT")" "$EXPECTED_FLAT"

# ── Nothing shadows anything ──────────────────────────────────────────────────
# The image gives every function one task root and one /opt/python, which no zip ever did. The
# search order is task root, then /opt/python, then the dependencies — so a name appearing twice
# does not collide, it silently wins, and the loser is the copy that was supposed to be used.
SHADOWED_SHARED=$(jq -r '[.task_top_level[] as $n | (.opt_packages + .opt_flat_modules)[] |
  select(. == $n)] | unique | join(" ")' <<<"$REPORT")
if [ -z "$SHADOWED_SHARED" ]; then
  pass "no module in the task root shadows a shared package or flat module"
else
  fail "no module in the task root shadows a shared package or flat module" \
       "these resolve to the task root's copy for every function: ${SHADOWED_SHARED}"
fi

# The dependency list is the one observation nothing else in this file proves is non-empty: the
# three sets above are each proved live by a check_eq of their own. If it came back empty — its
# collector filters on a path substring, one string away from matching nothing — the shadowing
# check below would pass over anything at all, and that check is what pays for installing
# dependencies outside /opt/python in the first place. So it is proved against a package the
# image is known to carry.
DEP_COUNT=$(jq -r '.site_packages_names | length' <<<"$REPORT")
if [ "${DEP_COUNT:-0}" -gt 0 ] && jq -e '.site_packages_names | index("polars")' >/dev/null <<<"$REPORT"; then
  pass "the installed dependencies were enumerated (${DEP_COUNT} top-level names, polars among them)"
else
  fail "the installed dependencies were enumerated" \
       "read ${DEP_COUNT:-0} names and did not find polars — the shadowing check below would pass over nothing"
fi

SHADOWED_DEPS=$(jq -r '[(.task_top_level + .opt_packages + .opt_flat_modules)[] as $n |
  .site_packages_names[] | select(. == $n)] | unique | join(" ")' <<<"$REPORT")
if [ -z "$SHADOWED_DEPS" ]; then
  pass "no repository module shadows an installed dependency"
else
  fail "no repository module shadows an installed dependency" \
       "the repository's copy wins for these: ${SHADOWED_DEPS}"
fi

# ── What must not be in the image ─────────────────────────────────────────────
# By PATTERN, not by a list of filenames — a list would pass the day someone adds a suite this
# check has never heard of.
# THE POSITIVE CONTROL FOR AN ABSENCE. A walk that examined nothing finds no offenders and reads
# as a clean image, so the count is checked before the emptiness is believed. The image carries
# well over a thousand files under those two trees.
EXAMINED=$(jq -r '.paths_examined' <<<"$REPORT")
if [ "${EXAMINED:-0}" -lt 100 ]; then
  fail "the image was walked for files it must not ship" \
       "the walk examined ${EXAMINED:-0} paths, which is too few to have covered the image — the absence below would be vacuous"
else
  pass "the image was walked for files it must not ship (${EXAMINED} paths examined)"
fi

OFFENDERS=$(jq -r '.offenders | join(" ")' <<<"$REPORT")
if [ -z "$OFFENDERS" ]; then
  pass "the image ships no suite, no conftest, no __pycache__ and no requirements file"
else
  fail "the image ships no suite, no conftest, no __pycache__ and no requirements file" \
       "found: ${OFFENDERS}"
fi

# ── Every handler imports ─────────────────────────────────────────────────────
# The reason the arc exists.
check_eq "the image carries one handler module per function Terraform declares" \
  "$(jq -r '.handler_count' <<<"$REPORT")" "$EXPECTED_FUNCTIONS"

IMPORTED=$(jq -r '.handler_count' <<<"$REPORT")
IMPORT_FAILURES=$(jq -r '.import_failures | length' <<<"$REPORT")
if [ "$IMPORT_FAILURES" = "0" ]; then
  pass "all ${IMPORTED} handler modules import, and each exposes a callable handler"
else
  fail "all ${IMPORTED} handler modules import, and each exposes a callable handler" \
       "$(jq -r '.import_failures | to_entries[] | "  \(.key): \(.value)"' <<<"$REPORT")"
fi

# ── The size ceiling ──────────────────────────────────────────────────────────
# A CEILING EXISTS AGAIN, and this one is for the packaging that actually ships. The zip pipeline
# measured every function's package plus its layers against Lambda's 250 MB unzipped limit, and
# that guard was deleted with the script that owned it — correctly, since nothing builds a zip,
# but it left the class of check with no successor at all. A container image has its own limit,
# 10 GB, so the number is different and the question is the same.
#
# THE BUDGET IS DELIBERATELY NOT PINNED AT THE MEASUREMENT. The image is ~223 MiB today, about 2%
# of the ceiling; a cap set just above that would fail on the next legitimate dependency and make
# the gate cause the damage it exists to prevent. 5 GB is half the hard limit — room for the fleet
# to grow by an order of magnitude, and still far enough below 10 GB that crossing it is a
# deliberate conversation rather than a failed deploy.
SIZE_BYTES=$(docker image inspect "$IMAGE" --format '{{.Size}}' 2>/dev/null || true)
CEILING=$((5 * 1024 * 1024 * 1024))
if ! [ "${SIZE_BYTES:-0}" -gt 0 ] 2>/dev/null; then
  fail "the image is under Lambda's size ceiling" \
       "could not read its size — an unread size is not a small one, and this check would pass over anything"
elif [ "$SIZE_BYTES" -le "$CEILING" ]; then
  pass "the image is under Lambda's size ceiling ($((SIZE_BYTES / 1024 / 1024)) MiB of $((CEILING / 1024 / 1024)) MiB budgeted, 10 GB hard limit)"
else
  fail "the image is under Lambda's size ceiling" \
       "$((SIZE_BYTES / 1024 / 1024)) MiB exceeds the $((CEILING / 1024 / 1024)) MiB budget. Lambda refuses an image over 10 GB; this budget sits at half that so the headroom is deliberate."
fi

# ── The build stamp ───────────────────────────────────────────────────────────
# The stamp is a FILE in the task root, not an environment variable — the SPA image's equivalent
# check reads `printenv` and is an analogue here, not a transplant. Terraform owns each function's
# environment map, so an env-borne version would be reverted by the next apply.
#
# This exists because a `--build-arg` dropped from ONE of the two image workflows is otherwise
# invisible: the image builds, every handler imports, the matrix passes, and every log record the
# fleet emits carries the 0.0.0 sentinel instead of a commit. The expected value is the tag being
# built, which is what makes "the sha identifies what is running" true of the stamp as well as of
# the registry.
STAMP=$(docker exec "$NAME" cat /var/task/BUILD_VERSION 2>/dev/null || true)
EXPECTED_STAMP="${IMAGE##*:}"
if [ -z "$STAMP" ]; then
  fail "BUILD_VERSION is stamped in the image" \
       "empty or absent — the build ran without --build-arg BUILD_VERSION, so every record this fleet emits will carry the 0.0.0 sentinel"
else
  check_eq "BUILD_VERSION is the tag being built" "$STAMP" "$EXPECTED_STAMP"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "${CHECKS} checks passed."
else
  echo "${FAILURES} of ${CHECKS} checks FAILED."
fi
# A run that asserted nothing must never look like a run that passed.
if [ "$CHECKS" -eq 0 ]; then
  echo "::error title=Matrix::no checks ran at all." >&2
  exit 1
fi
exit $((FAILURES > 0))
