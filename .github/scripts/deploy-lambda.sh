#!/usr/bin/env bash
# Builds and deploys ONE Lambda function: package, combined size guard, artifact
# upload, update-function-code, and the layer attachment.
#
# This is a separate FILE rather than a shell function inside deploy-lambdas.yml, and
# that is load-bearing. The shard job must keep going after one function fails, which
# means calling this from an `if` — and bash DISABLES errexit for the whole body of a
# function (or subshell) invoked as an `if` condition. As a function, a failed
# `update-function-code` would fall through to the layer attachment and the shard would
# report success. As a file run under its own `bash -euo pipefail`, it stops.
#
# Reads the layer set for the function from .github/lambda-functions.json, and each
# layer's published ARN + unzipped size from LAYERS_JSON — the flag -> {arn, kb} map the
# layers job emits once for the whole run.
#
# Required env: PROJECT_NAME, ENVIRONMENT, GITHUB_SHA, BUCKET, LAYERS_JSON.
set -euo pipefail

NAME="${1:?usage: deploy-lambda.sh <function-name>}"
FUNCTIONS_JSON="${FUNCTIONS_JSON:-.github/lambda-functions.json}"

LAYERS_JSON="${LAYERS_JSON:?LAYERS_JSON is unset — the layers job produced no map, and every function would deploy with no layer attached}"

# arn / kb for one layer flag, empty if the map does not carry it.
layer_field() { jq -r --arg f "$1" --arg k "$2" '.[$f][$k] // ""' <<<"$LAYERS_JSON"; }

BUILD_DIR="build/${NAME}"
FUNCTION="${PROJECT_NAME}-${ENVIRONMENT}-${NAME}"
KEY="${NAME}/${GITHUB_SHA}.zip"

# The function's row. Read as a whole first so that "not in the table" and "in the table
# with no layers" are distinguishable — they have the same empty output but very
# different meanings, and one of them must never be survivable.
#
# `jq` runs in a COMMAND SUBSTITUTION, not a process substitution: `set -e` does not
# cover the exit status of `< <(...)`, so a jq failure there is silently swallowed and
# the loop simply reads nothing. Empty FLAGS then sends this script down the
# bundle-requirements branch AND leaves LAYERS empty, so the layer attachment is skipped
# whole — new code, no layers, exit 0. That is SPEC-137 verbatim, reached from a
# malformed table instead of a missing flag.
if ! ENTRY=$(jq -ce --arg n "$NAME" '.[] | select(.name==$n)' "$FUNCTIONS_JSON"); then
  echo "::error::${NAME} has no row in ${FUNCTIONS_JSON} (or the file is malformed) — refusing to deploy a function whose layer set is unknown."
  exit 1
fi

# A read loop rather than `mapfile`, which is bash 4+: the runner has bash 5, but this
# script is worth being able to dry-run on a Mac (bash 3.2) before pushing it.
FLAGS=()
while IFS= read -r flag; do
  [ -n "$flag" ] && FLAGS+=("$flag")
done <<<"$(jq -r '.layers[]? // empty' <<<"$ENTRY")"

# Every function in this fleet attaches at least cpcommon, so an empty set is a bug in
# the table, not a valid configuration. Refused rather than tolerated because the
# consequence — a function deployed with no layer — is invisible until cold start. A
# function that genuinely needs no layer should fail here and have this rule revisited
# deliberately, which is the whole point of an ACCEPTED tripwire.
if [ "${#FLAGS[@]}" -eq 0 ]; then
  echo "::error::${NAME} resolves to NO layers. Every function in this fleet attaches at least one, so this is a malformed table rather than a valid row — refusing rather than deploying code that cannot import at cold start."
  exit 1
fi

has() {
  local f
  for f in ${FLAGS[@]+"${FLAGS[@]}"}; do
    [ "$f" = "$1" ] && return 0
  done
  return 1
}

# ── Build the package ──────────────────────────────────────────────────────────
rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"

# Layer functions get their deps from a layer; others bundle the shared requirements.
# `cpcommon` is part of this test because cpcommon is where PyJWT[crypto] is declared
# now (SPEC-107 FR-001) — a function attaching it must NOT also bundle a second copy
# (it would double-count against the combined size guard below, and drift).
# The four flags tested here are exactly the four the unsharded matrix tested; the
# domain layers that carry no external deps are deliberately not among them.
if ! has layer && ! has tbcommon && ! has tscommon && ! has cpcommon; then
  pip install --quiet --requirement lambdas/requirements.txt --target "$BUILD_DIR"
fi

# Copy the function's modules, SUBPACKAGES INCLUDED. The flat `cp .../*.py` this replaces
# silently dropped every subdirectory: a function laid out as a package deployed with its
# top-level modules only, and failed at cold start on an import that resolves perfectly under
# pytest (conftest.py puts the function directory on sys.path) and against which
# `update-function-code` reports success. That is the same shape as the signup outage — green
# tests, green deploy, ModuleNotFoundError in production.
#
# Tests and conftest are pruned by NAME at any depth, not by a top-level glob, for the same
# reason. The old prune matched only test_*.py, so the two functions that have a conftest were
# shipping it. Hidden directories are pruned at any depth because two function directories
# hold a developer's .pytest_cache or .ruff_cache, and a recursive copy is the first thing that
# would carry them; `-mindepth 1` is load-bearing there, since `.` itself matches `.*` and
# pruning it would silently match nothing at all.
#
# CDPATH is cleared because a `cd` under a set CDPATH PRINTS the resolved directory on stdout,
# which this pipeline would then read as a module name.
MODULES=$(
  CDPATH= cd -- "lambdas/${NAME}" &&
  find . -mindepth 1 -name '.*' -prune -o \
       -name '*.py' ! -name 'test_*.py' ! -name 'conftest.py' -print
)

# A function with nothing to ship is a function that is dead at cold start, and the deploy
# would report success. The flat glob refused an EMPTY directory by accident (`cp` found no
# match) and accepted a tests-only one; this refuses both on purpose.
if [ -z "$MODULES" ]; then
  echo "::error::${NAME} has no shippable modules — refusing to deploy an empty package."
  exit 1
fi

printf '%s\n' "$MODULES" | while IFS= read -r module; do
  mkdir -p "$BUILD_DIR/$(dirname "$module")"
  cp "lambdas/${NAME}/$module" "$BUILD_DIR/$module"
done

# Nothing above should be able to reintroduce a suite, so the refusal is here rather than in a
# comment. Scoped to the module list rather than to $BUILD_DIR, which by this point may also
# hold pip-installed dependencies — a vendored package's own tests would otherwise fire this
# and blame a prune that is not at fault.
if printf '%s\n' "$MODULES" | grep -qE '(^|/)(test_[^/]*\.py|conftest\.py)$'; then
  echo "::error::${NAME} package contains test files after the prune — refusing to deploy."
  exit 1
fi
# SPEC-186 FR-005: the build stamp travels IN THE PACKAGE, not in the function's
# environment. Tofu owns the environment map and `update-function-configuration
# --environment` REPLACES it whole, so writing a version there would either race Tofu or
# be reverted by the next apply; and Deploy Infrastructure is path-filtered to infra/**,
# so a Tofu-set sha would name the last INFRA commit rather than the code that is
# running. A file beside the handler is the artefact's own identity.
# `cpcommon.observability` reads it at import (see BUILD_VERSION there).
echo "${GITHUB_SHA}" > "$BUILD_DIR/BUILD_VERSION"
(cd "$BUILD_DIR" && zip --quiet --recurse-paths "../${NAME}.zip" .)

# ── Combined per-function size guard (SPEC-107 FR-004) ─────────────────────────
# Lambda's 250 MB unzipped ceiling is per FUNCTION — the function package PLUS every
# attached layer, combined. The per-LAYER guards measure one layer in isolation and
# CANNOT see a combined overflow (e.g. cpcommon + fccommon + polars on one function).
PKG_KB=$(du -sk "$BUILD_DIR" | cut -f1)
TOTAL_KB=$PKG_KB
NAMES="package(${PKG_KB}KB)"
for flag in ${FLAGS[@]+"${FLAGS[@]}"}; do
  kb=$(layer_field "$flag" kb)
  if [ -z "$kb" ]; then
    echo "::error::${NAME} attaches layer flag '${flag}' but the layer map carries no size for it, so the combined 250 MB guard cannot be evaluated."
    exit 1
  fi
  TOTAL_KB=$((TOTAL_KB + kb))
  NAMES="${NAMES} + ${flag}(${kb}KB)"
done
echo "${NAME} combined unzipped: $((TOTAL_KB / 1024)) MB  [${NAMES}]"
if [ "$TOTAL_KB" -gt 245760 ]; then
  echo "::error::${NAME} exceeds 240 MB unzipped: $((TOTAL_KB / 1024)) MB across ${NAMES} (Lambda's hard limit is 250 MB per function, package + all layers)."
  exit 1
fi

# ── Deploy ─────────────────────────────────────────────────────────────────────
# The function is created by deploy-infra.yml. When a merge touches both infra/ and
# lambdas/, both workflows fire on the same push and this one can win the race — so wait
# for the function to exist before deploying, instead of failing with ResourceNotFound.
# (The artifacts BUCKET is waited for once per shard, by the workflow, not here.)
for attempt in $(seq 1 30); do
  if aws lambda get-function --function-name "$FUNCTION" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "::error::Function ${FUNCTION} not ready after ~5 min. Run Deploy Infrastructure first."
    exit 1
  fi
  echo "Waiting for ${FUNCTION} (attempt ${attempt}/30)…"
  sleep 10
done

# A just-created function can still be in state Pending/Creating (the same push's Deploy
# Infrastructure run), and update-function-code then fails with
# ResourceConflictException — wait for Active first (hit on SPEC-088).
aws lambda wait function-active-v2 --function-name "$FUNCTION"

aws s3 cp "build/${NAME}.zip" "s3://${BUCKET}/${KEY}"
aws lambda update-function-code \
  --function-name "$FUNCTION" \
  --s3-bucket "$BUCKET" \
  --s3-key "$KEY" \
  --publish
aws lambda wait function-updated --function-name "$FUNCTION"

# Attach the function's layers. update-function-configuration --layers REPLACES the
# whole list, so a function needing more than one layer (infer-schema = cpcommon +
# table-builder-common + polars, SPEC-069/107) must pass them together in one call.
#
# ORDER IS PRESERVED FROM THE UNSHARDED MATRIX and is not alphabetical: layers land on
# /opt in order, so a later layer shadows an earlier one's modules. cpcommon goes on
# FIRST so a domain layer can override it, never the reverse.
LAYERS=()
for flag in cpcommon layer polars tbcommon tscommon dqcommon dqpolars fscommon focommon arcommon; do
  has "$flag" || continue
  arn=$(layer_field "$flag" arn)
  if [ -z "$arn" ]; then
    echo "::error::${NAME} attaches layer flag '${flag}' but the layer map carries no ARN for it — refusing to deploy a function with a missing layer, which fails at COLD START where no test and no deploy can see it."
    exit 1
  fi
  LAYERS+=("$arn")
done
if [ "${#LAYERS[@]}" -gt 0 ]; then
  aws lambda update-function-configuration \
    --function-name "$FUNCTION" \
    --layers "${LAYERS[@]}"
  aws lambda wait function-updated --function-name "$FUNCTION"
fi
