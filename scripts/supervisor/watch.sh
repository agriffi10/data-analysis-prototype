#!/usr/bin/env bash
# The supervisor's watch: a normalised snapshot of the PR queue, open PRs, main's push-run verdict,
# where sessions' work meets, and sessions that look ready to archive, printed as the lines that
# appeared (+) or disappeared (-) since the previous snapshot.
#
# Two modes, because the harness offers two ways to be woken:
#   --until-change  (default) exit on the first change. Run it with Bash run_in_background and
#                   relaunch after handling each event; a quiet night costs no wake-ups. With no
#                   state file yet, it prints the baseline as = lines and exits at once.
#   --stream        print every change and never exit, for the Monitor tool (which it outlives
#                   by expiring every 30 minutes and needing a re-arm).
#
# The state file persists between runs, so a relaunch never replays the baseline; delete it to see
# the whole snapshot once. The queue is read from the Q= line of the main checkout's pre-push hook,
# which several-agents.md names as the one authority for where the live queue is.
#
# Usage: scripts/supervisor/watch.sh --self <this session's id> [--until-change|--stream]
#   SUPERVISOR_STATE_DIR  where watch.state lives (default: $TMPDIR/supervisor-<checkout name>)
#   SUPERVISOR_INTERVAL   seconds between snapshots (default 150)
set -u
export LC_ALL=C GIT_OPTIONAL_LOCKS=0
HERE=$(cd "$(dirname "$0")" && pwd)
common=$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir) || exit 3
REPO=$(dirname "$common")
Q=$(sed -n "s/^Q=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" "$common/hooks/pre-push" 2>/dev/null | head -1)
MODE=until-change SELF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --self) [ $# -ge 2 ] || { echo "--self needs a session id" >&2; exit 2; }; SELF=$2; shift 2;;
    --until-change) MODE=until-change; shift;;
    --stream) MODE=stream; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$SELF" ] || { echo "--self <session id> is required, so this session is never offered for archive" >&2; exit 2; }
STATE_DIR=${SUPERVISOR_STATE_DIR:-${TMPDIR:-/tmp}/supervisor-$(basename "$REPO")}
mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/watch.state"
INTERVAL=${SUPERVISOR_INTERVAL:-150}

snapshot() {
  cd "$REPO" || return
  if [ -z "$Q" ]; then
    echo "ALERT no Q= line in $common/hooks/pre-push; queue not watched"
  elif [ ! -d "$Q" ]; then
    echo "ALERT the queue named by the pre-push hook does not exist: $Q"
  elif [ -f "$Q/lock/holder" ]; then
    spec=$(awk '$1=="spec"{print $2}' "$Q/lock/holder"); br=$(awk '$1=="branch"{print $2}' "$Q/lock/holder")
    since=$(awk '$1=="since"{print $2}' "$Q/lock/holder")
    echo "QUEUE lock held by $spec on $br since $since"
    age=$(( $(date -u +%s) - $(date -ju -f %Y-%m-%dT%H:%M:%SZ "$since" +%s 2>/dev/null || date -u +%s) ))
    [ "$age" -gt 4800 ] && echo "ALERT lock held by $spec for over 80 minutes"
  else
    echo "QUEUE lock free"
  fi
  for t in "${Q:-/nonexistent}"/tickets/*; do [ -d "$t" ] || continue
    echo "QUEUE waiting $(basename "$t") $(cat "$t/spec" 2>/dev/null)"
  done
  if prs=$(gh pr list --state open --json number,headRefName,isDraft --jq '.[]|"PR open #\(.number) \(.headRefName)\(if .isDraft then " DRAFT" else "" end)"' 2>&1); then
    [ -n "$prs" ] && echo "$prs"
  else echo "ALERT gh pr list failed"; fi
  # main is judged at the remote's head, not at the newest run: a push GitHub dropped leaves the
  # newest run on the PREVIOUS commit, green, while the merge was never deployed. Its runs are
  # asked for by sha, because the list endpoint intermittently serves a page weeks stale, and a
  # head missing from that page read as "no push run yet" while main was green.
  head=$(git ls-remote origin refs/heads/main 2>/dev/null | awk '{print $1}')
  if [ -z "$head" ]; then
    echo "ALERT could not read main's head from origin"
  elif runs=$(gh api "repos/{owner}/{repo}/actions/runs?head_sha=$head&branch=main&event=push&per_page=100" 2>&1); then
    echo "$runs" | HEAD_SHA="$head" python3 -c '
import json, os, sys
sha = os.environ["HEAD_SHA"]
try:
    page = json.load(sys.stdin)
    runs, total = page["workflow_runs"], page["total_count"]
    mine = [r for r in runs if r["head_sha"] == sha]
    bad = [r["name"] for r in mine if r["status"] == "completed" and r["conclusion"] not in ("success", "skipped", "neutral")]
    busy = [r for r in mine if r["status"] != "completed"]
    verdict = "no push run yet" if not mine else "RED: " + ", ".join(bad) if bad else "building" if busy else "green"
    if total > len(runs):
        verdict = "unreadable: %d push runs, one page holds %d" % (total, len(runs))
except (ValueError, KeyError, TypeError):
    verdict = None
print("MAIN %s %s" % (sha[:8], verdict) if verdict else "ALERT could not parse the runs of main")'
  else echo "ALERT gh api actions/runs failed"; fi
  "$HERE/overlap.sh" 2>/dev/null | grep -E '^(SHARED|CONFLICT)'
  if done=$(python3 "$HERE/done_check.py" --no-fetch --self "$SELF" 2>&1); then
    printf '%s\n' "$done" | awk -F'\t' '$4=="ARCHIVABLE"{print "ARCHIVABLE " $1 " " $2}'
  else
    echo "ALERT done_check.py failed, so no session is offered for archive: $(printf '%s' "$done" | tail -1)"
  fi
}

while true; do
  cur=$(snapshot | sort -u)
  if [ ! -f "$STATE" ]; then
    printf '%s\n' "$cur" | sed 's/^/= /'
    printf '%s\n' "$cur" > "$STATE"
    [ "$MODE" = until-change ] && exit 0
  elif [ "$cur" != "$(cat "$STATE")" ]; then
    diff <(cat "$STATE") <(printf '%s\n' "$cur") | sed -n 's/^> /+ /p; s/^< /- /p'
    printf '%s\n' "$cur" > "$STATE"
    [ "$MODE" = until-change ] && exit 0
  fi
  sleep "$INTERVAL"
done
