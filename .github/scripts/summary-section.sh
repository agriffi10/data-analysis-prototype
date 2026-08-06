#!/usr/bin/env bash
#
# Writes one scanner's section to the GitHub Actions job summary.
#
# This repo is private on a personal account, so GitHub code scanning is unavailable —
# `security_and_analysis` is null and the code-scanning API returns 403. There is no
# Security tab, no alert list, no new-vs-existing diffing. The workflow run IS the only
# place a finding appears, which is why the summary is a requirement (SPEC-138 FR-008)
# rather than a nicety.
#
# A zero-finding scanner writes an explicit line rather than an empty section. An empty
# section and a step that silently failed to run look identical in the summary, and
# telling them apart is most of what this check is for.
#
# Usage: summary-section.sh <title> <finding-count> [body-file]

set -euo pipefail

title="${1:?section title required}"
count="${2:?finding count required}"
body="${3:-}"

{
  echo "### ${title}"
  echo
  # SPEC-153 FR-008: a scanner that ran and left no readable report has no finding count
  # at all, and must not be summarised as "No findings." — the summary is the only place a
  # finding ever appears in this repo (see above), so a broken scan rendering identically
  # to a clean one is the failure mode this file exists to prevent, one level up. The
  # caller fails its own job; this just says why in the summary.
  if ! printf '%s' "$count" | grep -Eq '^[0-9]+$'; then
    echo "**⚠️ ${count}.** No finding count could be derived, so this is NOT a clean result."
  elif [ "$count" -eq 0 ]; then
    echo "No findings."
  else
    echo "**${count} finding(s).**"
    echo
    if [ -n "$body" ] && [ -s "$body" ]; then
      cat "$body"
    else
      echo "_(Finding detail is in this job's uploaded artifact.)_"
    fi
  fi
  echo
} >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
