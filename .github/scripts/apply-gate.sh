#!/usr/bin/env bash
#
# The gate. Every scanner step in security.yml ends with a call to this script.
#
# SPEC-138 ships every scanner as `report`: it runs, publishes its findings to the job
# summary and an artifact, and concludes green. Flipping one to `block` is a single-value
# edit to the GATE_* block at the top of security.yml — no step changes, no re-plumbing.
# Routing every scanner through one script is what makes that true.
#
# An unrecognised gate value is a HARD ERROR, not a fallback to report-only. A typo
# ("blcok") that silently degraded to reporting would leave a workflow that looks like it
# enforces something and does not — the worst state a security check can be in.
#
# Usage: apply-gate.sh <scanner-name> <gate-value> <finding-count>

set -euo pipefail

scanner="${1:?scanner name required}"
gate="${2:?gate value required}"
findings="${3:?finding count required}"

case "$findings" in
  '' | *[!0-9]*)
    echo "::error title=$scanner::finding count '$findings' is not a number — the scanner's output was probably not parsed."
    exit 2
    ;;
esac

case "$gate" in
  report)
    if [ "$findings" -gt 0 ]; then
      echo "::notice title=$scanner::$findings finding(s). gate=report, so this does not fail the build. See the job summary."
    else
      echo "$scanner: no findings."
    fi
    ;;
  block)
    if [ "$findings" -gt 0 ]; then
      echo "::error title=$scanner::$findings finding(s) and gate=block. Failing."
      exit 1
    fi
    echo "$scanner: no findings."
    ;;
  *)
    echo "::error title=$scanner::unrecognised gate value '$gate' — expected 'report' or 'block'."
    exit 2
    ;;
esac
