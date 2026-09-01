#!/usr/bin/env bash
# Resolves the runtime configuration's values from Terraform state into step outputs.
#
# Terraform computes these — bucket names, the API's origin, the Cognito identifiers — and
# before this script they reached the deploy as repository variables a person had copied out
# of `tofu output` by hand. A value that moved in infrastructure stayed wrong in the browser
# until somebody remembered to re-copy it, and an unset variable interpolated to the EMPTY
# STRING, which satisfies every presence test there is and reached AWS as a malformed
# request far from its cause.
#
# ABSENT AND EMPTY ARE THE SAME FAILURE, and both are fatal here. Every output in the map is
# a value Terraform always computes, so an empty one means the state is not what this deploy
# assumes — a fault, whatever the browser's degraded path for that key might be. This is
# deliberately stricter than the served document's own REQUIRED list, which still decides
# what may not ship and is unchanged: this script asks "did Terraform tell us", the render
# step asks "may this document be published", and the second question is not this one.
#
# ONE READ. `tofu output -json` runs once into a single document rather than once per name:
# thirty round trips to resolve eight values would be strictly worse than the arrangement it
# replaces, and each one is a chance to resolve half a configuration.
#
# NOTHING IS ECHOED. `tofu output -json` prints values in the clear where plain `tofu output`
# redacts a sensitive one. No output in the map is sensitive — `lambdas/test_config_outputs.py`
# asserts it — but a script that dumps its own document makes that assertion the only thing
# standing between a future `sensitive` output and a public build log.
set -euo pipefail

MAPPING=".github/config-outputs.json"
OUTPUTS_JSON=""

usage() {
  cat >&2 <<'USAGE'
usage: resolve-config.sh [--mapping PATH] [--outputs PATH]

  --mapping PATH   The output-name to configuration-key map.
                   Default: .github/config-outputs.json
  --outputs PATH   Read a captured `tofu output -json` document instead of running
                   OpenTofu. For tests; the deploy omits it.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mapping) MAPPING="${2:?--mapping needs a path}"; shift 2 ;;
    --outputs) OUTPUTS_JSON="${2:?--outputs needs a path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "::error::resolve-config.sh: unknown argument '$1'" >&2; usage; exit 2 ;;
  esac
done

if [ ! -f "$MAPPING" ]; then
  echo "::error::resolve-config.sh: no mapping at $MAPPING" >&2
  exit 1
fi

# A map that parsed to nothing would resolve nothing and report success, which is the one
# failure this script must never have: the deploy would carry on and publish a document
# built entirely from empty values.
if [ "$(jq 'length' "$MAPPING")" -eq 0 ]; then
  echo "::error::resolve-config.sh: $MAPPING declares no entries" >&2
  exit 1
fi

if [ -n "$OUTPUTS_JSON" ]; then
  DOCUMENT="$(cat "$OUTPUTS_JSON")"
else
  DOCUMENT="$(tofu output -json)"
fi

# Absent and empty are reported together rather than one per run: a deploy that names one
# missing value, is fixed, and then names the next costs a deploy cycle per value.
missing=""
while IFS=$'\t' read -r output_name config_key; do
  present="$(printf '%s' "$DOCUMENT" | jq --arg n "$output_name" 'has($n)')"
  if [ "$present" != "true" ]; then
    missing="${missing}
  ${config_key} — Terraform output '${output_name}' is absent from the state"
    continue
  fi

  value="$(printf '%s' "$DOCUMENT" | jq -r --arg n "$output_name" '.[$n].value // ""')"
  if [ -z "$value" ]; then
    missing="${missing}
  ${config_key} — Terraform output '${output_name}' is empty"
    continue
  fi

  # The heredoc form, not `key=value`: a value carrying a newline would otherwise be read as
  # the start of another output and the rest of it published under a name nobody declared.
  if printf '%s' "$value" | grep -q '^__RESOLVE_CONFIG_EOF__$'; then
    echo "::error::resolve-config.sh: ${config_key} contains the output delimiter" >&2
    exit 1
  fi
  {
    printf '%s<<__RESOLVE_CONFIG_EOF__\n' "$config_key"
    printf '%s\n' "$value"
    printf '__RESOLVE_CONFIG_EOF__\n'
  } >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT is not set}"
done < <(jq -r 'to_entries[] | "\(.key)\t\(.value)"' "$MAPPING")

if [ -n "$missing" ]; then
  echo "::error::the deploy cannot resolve its configuration from Terraform state:${missing}" >&2
  exit 1
fi
