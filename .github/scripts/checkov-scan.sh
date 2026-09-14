#!/usr/bin/env bash
#
# Every Checkov scan's one entry point. Runs `checkov` with exactly the arguments given, and
# refuses to run at all if Checkov reports taking configuration from anywhere else: a config
# file it discovered, or an environment variable behind one of its flags.
#
# WHY. Checkov reads `.checkov.yaml` and `.checkov.yml` from the directory named by `-d`, from
# the working directory and from $HOME, even when `-f` names a single file, and it reads the
# environment variables behind its own flags, such as CKV_SKIP_CHECK. A key it finds in either
# place takes effect unless the same flag is on the command line. Measured against 3.3.9 with
# the rendered-plan scan's invocation, on a fixture plan holding one wildcard policy: a
# `.checkov.yml` holding `skip-check: [CKV_AWS_355]` in its working directory took that one
# finding off (9 failures became 8) while every other IAM check still ran. The coverage
# assertion passed, and the blocking gate counted what was left. That file sits outside the
# three list files the gates name, so nobody reviewing it would see it as a change to a gate.
#
# WHY REFUSE RATHER THAN IGNORE. No option turns discovery off. `--config-file` is parsed
# BESIDE the discovered files, not instead of them: the planted skip survived an explicit
# config holding `skip-check: []`. And a config file the scan quietly ignored would read as a
# suppression while suppressing nothing, which is what checkov-plan-iam.sh already refuses in
# a stale accept line.
#
# HOW. Checkov is asked, with the same arguments, what configuration it would use
# (`--show-config`). That is its own answer, not a list of places copied from its source, so a
# discovery location a version bump adds is covered too. Anything reported beyond the command
# line and the defaults is refused, and a report without its command-line section is refused as
# unreadable. The section names are Checkov's own; which sources get recorded is
# ConfigArgParse's, which Checkov does not pin. A source Checkov cannot name crashes
# `--show-config`, which is a refusal. A release that stopped recording one would be silent
# here, so checkov-scan-test.sh plants a config in every discovery place against the installed
# scanner, ahead of the scans that rely on this, and fails there instead.
#
# NOT COVERED: the environment variables Checkov reads directly rather than through a flag,
# such as CKV_IGNORED_DIRECTORIES. `--show-config` cannot report them, so this cannot refuse
# them. Only the workflow, or a step writing $GITHUB_ENV, can set one.
#
# Usage: checkov-scan.sh <checkov arguments...>
# Stdout: Checkov's own output. NOTHING on a refusal, so a caller that validates the scan JSON
# fails rather than reading a scan that never ran. Diagnostics go to stderr.
# Exit: 2 on a refusal, otherwise Checkov's own status.

set -euo pipefail

err() { echo "::error title=Checkov (configuration)::$1" >&2; }

[ "$#" -gt 0 ] || { err "no arguments. This wrapper runs one scan and must be told what to scan."; exit 2; }
command -v checkov >/dev/null 2>&1 || { err "checkov is not installed. The scan did not run."; exit 2; }

if ! shown=$(checkov "$@" --show-config); then
  err "checkov could not report its configuration for these arguments, so the scan cannot be shown to use only them."
  exit 2
fi

# Prints every section other than the command line and the defaults, header and settings both.
# Exits 3 when there is no command-line section. Every invocation has one, so its absence
# means the report's format changed, and silence in the rest of it would prove nothing.
if ! outside=$(printf '%s\n' "$shown" | awk '
    /^Command Line Args:/ { cli = 1; on = 0; next }
    /^Defaults:/          { on = 0; next }
    /^[^[:space:]]/       { on = 1 }
    on                    { print }
    END                   { if (!cli) exit 3 }'); then
  err "checkov --show-config printed no command-line section. Its report format has changed, so a report naming no config file would prove nothing. Re-measure this script against the installed version."
  exit 2
fi

if [ -n "$outside" ]; then
  sources=$(printf '%s\n' "$outside" | awk '/^[^[:space:]]/ { sub(/:$/, ""); printf "%s%s", sep, $0; sep = "; " }')
  err "refusing to scan: checkov would take configuration from outside this command line (${sources}). A setting there changes what the gate counts from a place nobody reviews as part of it. Delete the file or unset the variable. A setting the scan needs belongs on the invocation in the workflow."
  printf '%s\n' "$outside" >&2
  exit 2
fi

exec checkov "$@"
