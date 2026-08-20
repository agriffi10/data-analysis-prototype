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
# layer's published ARN + unzipped size from the environment (ARN_<flag> / KB_<flag>),
# which the shard job populates once from the layer jobs' outputs.
#
# Required env: PROJECT_NAME, ENVIRONMENT, GITHUB_SHA, BUCKET, and ARN_*/KB_* per flag.
set -euo pipefail

NAME="${1:?usage: deploy-lambda.sh <function-name>}"
FUNCTIONS_JSON="${FUNCTIONS_JSON:-.github/lambda-functions.json}"

BUILD_DIR="build/${NAME}"
FUNCTION="${PROJECT_NAME}-${ENVIRONMENT}-${NAME}"
KEY="${NAME}/${GITHUB_SHA}.zip"

# The layer flags this function attaches, in the JSON's own order.
# A read loop rather than `mapfile`, which is bash 4+: the runner has bash 5, but this
# script is worth being able to dry-run on a Mac (bash 3.2) before pushing it.
FLAGS=()
while IFS= read -r flag; do
  [ -n "$flag" ] && FLAGS+=("$flag")
done < <(jq -r --arg n "$NAME" '.[] | select(.name==$n) | .layers[]' "$FUNCTIONS_JSON")

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

cp lambdas/"${NAME}"/*.py "$BUILD_DIR"/
# Never ship tests.
rm -f "$BUILD_DIR"/test_*.py

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
  kb_var="KB_${flag}"
  kb="${!kb_var:-}"
  if [ -z "$kb" ]; then
    echo "::error::${NAME} attaches layer flag '${flag}' but ${kb_var} is empty — the layer job did not report a size, so the combined 250 MB guard cannot be evaluated."
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
  arn_var="ARN_${flag}"
  arn="${!arn_var:-}"
  if [ -z "$arn" ]; then
    echo "::error::${NAME} attaches layer flag '${flag}' but ${arn_var} is empty — refusing to deploy a function with a missing layer, which fails at COLD START where no test and no deploy can see it."
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
