#!/usr/bin/env bash
#
# The .tf gate's population. Refuses a tracked file that OpenTofu reads and Checkov's terraform
# framework cannot read the way OpenTofu does, before the scan's count is trusted.
#
# WHY. security.yml scans `-d infra --framework terraform`, which parses `.tf` and `.hcl` files.
# OpenTofu also loads `*.tf.json`, `*.tofu` and `*.tofu.json`, and a `.tofu` file shadows the
# `.tf` of the same name. Measured against 3.3.9: a log group with no retention in `bare.tofu`,
# `bare.tf.json` or `bare.tofu.json`, beside a compliant one in `main.tf`, left CKV_AWS_66
# PASSED on the compliant one only, and the enforced numerator printed 0. Every enforced ID can
# be dodged that way. An override file (`override.tf`, `*_override.tf`) is parsed, but OpenTofu
# merges it into the block it overrides while Checkov scores each block alone, so a setting
# that only the merge produces is one no check reads. And a variable file (`*.tfvars`,
# `*.tfvars.json`) works the other way round: Checkov applies one in a module's directory to that
# module, while OpenTofu reads one only in the directory it runs from. Measured by review: an
# `*.auto.tfvars.json` beside a security group in a child module turned CKV_AWS_24 from FAILED to
# PASSED, and a real plan of the same shape still opened the port to 0.0.0.0/0.
#
# WHY REFUSE. Nothing here uses any of these shapes, so refusing them costs nothing, and reading
# them would need a second framework whose JSON is a list the numerators read only the first
# report of. A shape Checkov learns to read later is still refused, which is the safe direction.
#
# WHY EVERY TRACKED FILE, NOT infra/ ALONE. A module's source can name a directory outside
# infra/, which OpenTofu loads and Checkov follows (measured), so a directory boundary would be a
# claim about where modules live. Tracked files, because a checkout is what the deploy applies,
# once a module from outside the checkout is refused, which checkov-enforced.sh does.
#
# PATHS ARE READ RAW. Without -z, git quotes a path holding a non-ASCII character, and the
# closing quote hid `infra/sécurité.tofu` from every rule here while OpenTofu loaded it (measured
# by review). NUL-separated paths are turned into lines, so a name holding a newline is read as
# pieces, and the last piece carries its suffix and the end of its basename, which are all the
# rules below read.
#
# NOT COVERED: which directories Checkov walks. It skips hidden directories and those named in
# CKV_IGNORED_DIRECTORIES, but follows a module call into one (measured), so a module there is
# read. The variable itself is one Checkov reads without a flag, which checkov-scan.sh records
# as not refused.
#
# Usage: checkov-tf-population.sh [<repository root>]   (default: the working directory)
# Stdout: nothing. Diagnostics go to stderr.
# Exit: 0 when no such file is tracked, 2 on a refusal or when the tracked files cannot be read.

set -euo pipefail

root="${1:-.}"

err() { echo "::error title=Checkov (population)::$1" >&2; }

if ! files=$(git -C "$root" ls-files -z | tr '\0' '\n'); then
  err "could not list the files tracked under $root, so nothing shows the scan can read every file OpenTofu loads."
  exit 2
fi

# A listing with no .tf file in it came from the wrong tree, and would refuse nothing.
tf_count=$(printf '%s\n' "$files" | grep -c '\.tf$' || true)
if [ "$tf_count" -eq 0 ]; then
  err "no .tf file is tracked under $root, so this read the wrong tree and its silence would prove nothing."
  exit 2
fi

refused=$(printf '%s\n' "$files" | awk '
  { base = $0; sub(/.*\//, "", base) }
  /\.tofu$/ || /\.tofu\.json$/ || /\.tf\.json$/ {
    print $0 ": OpenTofu loads it and the terraform framework does not parse it, so a finding in it reaches no check"; next
  }
  base == "override.tf" || base ~ /_override\.tf$/ {
    print $0 ": OpenTofu merges it into the block it overrides, which Checkov scores alone, so a setting only the merge makes reaches no check"; next
  }
  /\.tfvars$/ || /\.tfvars\.json$/ {
    print $0 ": Checkov applies a variable file to the module beside it, and OpenTofu only to the root it runs from, so beside any other module a check can pass a value that is never applied"
  }')

if [ -n "$refused" ]; then
  while IFS= read -r finding; do
    err "$finding."
  done <<< "$refused"
  err "Write it as a plain .tf file, with each setting in the block it belongs to, and pass a variable's value from the module call rather than a file beside the module. A shape the scan cannot read is refused rather than trusted to be clean."
  exit 2
fi

echo "$tf_count tracked .tf file(s); none that OpenTofu loads and the scan cannot read" >&2
