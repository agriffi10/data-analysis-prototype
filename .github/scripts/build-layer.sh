#!/usr/bin/env bash
# Builds and publishes ONE Lambda layer, and prints `flag<TAB>arn<TAB>unzipped_kb`
# on stdout for the caller to collect. Everything else it says goes to stderr, so the
# caller can read stdout as data.
#
# Ten layers used to be ten JOBS. Each took 14-29 seconds and GitHub bills a whole
# minute per job, so they cost ten minutes for about three minutes of work. They are
# one job now, and the per-layer differences that justified separate jobs turned out to
# be three shapes over one table — see .github/lambda-layers.json.
#
# A separate FILE rather than a shell function, for the same reason as
# deploy-lambda.sh: the caller runs it from an `if`, and bash disables errexit inside a
# function invoked that way, so a failed `pip install` would publish a layer missing its
# dependencies and report success.
#
# The layer is always BUILT, because the combined 250 MB per-function guard needs its
# unzipped size whether or not it changed. It is only PUBLISHED when the second argument
# says so. That split is what makes skipping unchanged functions correct at all:
# `publish-layer-version` mints a NEW VERSION on every call and functions pin layers by
# ARN, so republishing an unchanged layer would oblige every function attaching it to be
# re-pointed — which is precisely the work the plan is trying to avoid. An unchanged layer
# resolves to the version already published instead.
#
# Required env: PROJECT_NAME, ENVIRONMENT.
set -euo pipefail

FLAG="${1:?usage: build-layer.sh <flag> <publish:true|false>}"
PUBLISH="${2:?usage: build-layer.sh <flag> <publish:true|false>}"
LAYERS_JSON="${LAYERS_JSON_FILE:-.github/lambda-layers.json}"

entry=$(jq -c --arg f "$FLAG" '.[] | select(.flag==$f)' "$LAYERS_JSON")
if [ -z "$entry" ]; then
  echo "::error::no layer with flag '${FLAG}' in ${LAYERS_JSON}" >&2
  exit 1
fi

read_field() { jq -r --arg k "$1" '.[$k] // ""' <<<"$entry"; }

LAYER_NAME_SUFFIX=$(read_field layerName)
REQUIREMENTS=$(read_field requirements)
PACKAGE=$(read_field package)
SOURCE_DIR=$(read_field sourceDir)
DESCRIPTION=$(read_field description)

BUILD_ROOT="build/layers/${FLAG}"
LAYER_DIR="${BUILD_ROOT}/python"
rm -rf "$BUILD_ROOT" && mkdir -p "$LAYER_DIR"

# ── Shape 1: external dependencies from a requirements file ────────────────────
# Plain pip install on the linux x86_64 / python3.12 runner pulls the manylinux
# wheels, ABI-compatible with the python3.12 Lambda runtime (Amazon Linux 2023).
if [ -n "$REQUIREMENTS" ]; then
  pip install --quiet --requirement "$REQUIREMENTS" --target "$LAYER_DIR" >&2
fi

# ── Shape 2: a whole package directory ─────────────────────────────────────────
# A new module here ships automatically, so there is no list to drift from — which is
# why only the flat-module layer below needs a copy-list test.
if [ -n "$PACKAGE" ]; then
  cp -r "$PACKAGE" "$LAYER_DIR"/"$(basename "$PACKAGE")"
  find "$LAYER_DIR"/"$(basename "$PACKAGE")" -name '__pycache__' -type d -prune -exec rm -rf {} +
fi

# ── Shape 3: an explicit list of FLAT modules ──────────────────────────────────
# shared-space-common publishes flat modules rather than a package, so the list is
# enumerated. That list is the one thing here that CAN silently drift from its source
# directory, and lambdas/test_deploy_matrix.py asserts set equality in both directions —
# a module added to the directory and not the list never ships, and a function importing
# it dies at cold start (SPEC-137's exact shape, one level down).
if [ -n "$SOURCE_DIR" ]; then
  while IFS= read -r module; do
    [ -n "$module" ] || continue
    cp "${SOURCE_DIR}/${module}.py" "$LAYER_DIR"/
  done < <(jq -r '.modules[]? // empty' <<<"$entry")
fi

if [ -z "$(ls -A "$LAYER_DIR")" ]; then
  echo "::error::layer '${FLAG}' built EMPTY — its table entry names no requirements, package or modules, and an empty layer publishes fine and fails every function that attaches it at cold start." >&2
  exit 1
fi

UNZIPPED_KB=$(du -sk "$LAYER_DIR" | cut -f1)
echo "${LAYER_NAME_SUFFIX} unzipped: $((UNZIPPED_KB / 1024)) MB (${UNZIPPED_KB} KB)" >&2

# Lambda's hard limit is 250 MB unzipped per FUNCTION (package + every attached layer);
# fail early with headroom if one layer alone approaches it. Applied to every layer
# rather than only the two polars ones, which is the one behaviour change in the merge:
# it can only refuse a layer that is already too big to deploy. The COMBINED guard that
# catches several layers on one function stays in deploy-lambda.sh, because only that
# side knows which layers a function attaches.
if [ "$UNZIPPED_KB" -gt 245760 ]; then
  echo "::error::${LAYER_NAME_SUFFIX} layer exceeds 240 MB unzipped ($((UNZIPPED_KB / 1024)) MB)." >&2
  exit 1
fi

LAYER_NAME="${PROJECT_NAME}-${ENVIRONMENT}-${LAYER_NAME_SUFFIX}"

ARN=""
if [ "$PUBLISH" != "true" ]; then
  # Unchanged: reuse the newest version already published. `list-layer-versions` returns
  # newest first, so this is the version every function attaching this layer is already
  # pointing at — re-pointing them is a no-op, which is the point.
  ARN=$(aws lambda list-layer-versions \
    --layer-name "$LAYER_NAME" \
    --max-items 1 \
    --query 'LayerVersions[0].LayerVersionArn' --output text 2>/dev/null || true)
  if [ "$ARN" = "None" ]; then
    ARN=""
  fi
  if [ -n "$ARN" ]; then
    echo "Reusing ${ARN} (unchanged)" >&2
  else
    # Never published — a brand-new layer on a push that did not appear to change it.
    # Publishing is the only correct answer; the alternative is an empty ARN, and
    # deploy-lambda.sh would refuse every function attaching it.
    echo "No published version of ${LAYER_NAME} exists — publishing despite no detected change." >&2
  fi
fi

if [ -z "$ARN" ]; then
  (cd "$BUILD_ROOT" && zip --quiet --recurse-paths "../${FLAG}-layer.zip" .)
  ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "$DESCRIPTION" \
    --zip-file "fileb://build/layers/${FLAG}-layer.zip" \
    --compatible-runtimes python3.12 \
    --query LayerVersionArn --output text)
  echo "Published ${ARN}" >&2
fi

printf '%s\t%s\t%s\n' "$FLAG" "$ARN" "$UNZIPPED_KB"
