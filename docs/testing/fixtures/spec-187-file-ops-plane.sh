#!/usr/bin/env bash
# Live checks for the file-operations control plane's foundation.
#
# WHY THIS IS A SCRIPT AND NOT A LIST OF STEPS IN e2e.md: nothing in the browser reaches this
# plane yet. The enqueue service exists and no gesture calls it, so every check here is a
# hand-crafted envelope on the CLI. Each one is also an `owed.md` row; running this is what
# discharges them.
#
# A SHARED LAYER'S IMPORT-TIME FAILURE ONLY SHOWS AT COLD START. Offline tests cannot see a verb
# shipped without its layer — the fleet has an outage on record for exactly that — so these are
# real invocations against the deployed plane, not a simulation of one.
#
# USAGE
#   1. Sign in to the portal in a browser as the account you want to act as.
#   2. Copy its ID token out of local storage into /tmp/idtoken (no trailing newline):
#        JSON.parse(Object.entries(localStorage).find(([k]) => k.endsWith('.idToken'))[1])
#      or, if Amplify stores it under a keyed entry:
#        localStorage.getItem(Object.keys(localStorage).find(k => k.includes('idToken')))
#   3. USERNAME=alice ./spec-187-file-ops-plane.sh
#
# The token is read, never minted: the plane verifies it offline against the pool's JWKS, and a
# token this script forged would be refused at the front door in a way that reads exactly like the
# check failing.
#
# EXPECTED FIXTURES in the acting user's own space, created through the browser beforehand:
#   {USERNAME}/fileops-check/one.csv      any small file
#   {USERNAME}/fileops-check/nested/      a folder with at least one file in it
#   {USERNAME}/fileops-dest/              an empty folder
# The plane copies and deletes NOTHING at this stage — the machine ends in a placeholder — so
# these are named in requests and never touched. They exist so the requests are about real keys.

set -euo pipefail

: "${USERNAME:?set USERNAME to the signed-in account}"
TOKEN_FILE="${TOKEN_FILE:-/tmp/idtoken}"
[ -s "$TOKEN_FILE" ] || { echo "no token at $TOKEN_FILE — see USAGE" >&2; exit 1; }

REGION="${AWS_REGION:-us-east-1}"
USER_BUCKET="${USER_BUCKET:-dat-prod-user-space}"
ADMIN_BUCKET="${ADMIN_BUCKET:-dat-prod-athena-admin}"
QUEUE=$(aws sqs get-queue-url --queue-name dat-prod-file-ops-requests.fifo --query QueueUrl --output text)
MACHINE="arn:aws:states:${REGION}:$(aws sts get-caller-identity --query Account --output text):stateMachine:dat-prod-file-ops-orchestrator"

# THE GROUP ID IS A DIGEST OF "{bucket}/{spaceName}/", and the trailing slash is inside it. The
# browser hashes the same string for MessageGroupId and the plane hashes it again for the lock key
# — a difference of one character means delivery is ordered on one key while the lock is held under
# another, and NOTHING at runtime reports that.
space_digest() { printf '%s/%s/' "$1" "$2" | shasum -a 256 | cut -d' ' -f1; }
GROUP=$(space_digest "$USER_BUCKET" "$USERNAME")
LOCK_KEY="locks/file-ops/${GROUP}.json"

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
uuid() { python3 -c 'import uuid;print(uuid.uuid4())'; }

send() {
  # send <body-json> [group]
  aws sqs send-message --queue-url "$QUEUE" \
    --message-group-id "${2:-$GROUP}" \
    --message-deduplication-id "$(uuid)" \
    --message-body "$1" >/dev/null
}

executions_since() {
  aws stepfunctions list-executions --state-machine-arn "$MACHINE" --max-items 20 \
    --query 'executions[].{name:name,status:status,start:startDate}' --output table
}

echo "== 1. A valid delete reaches the placeholder terminal =="
# A DELETE CARRIES NO destination, onConflict OR submittedAt. The plane REJECTS them for a delete
# rather than ignoring them, so adding one turns this check into a refusal that looks like a bug.
send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" \
  '{requestId:$r, actor:$t, operation:"delete",
    source:{space:{kind:"personal", name:$u},
            items:[{kind:"folder", key:($u+"/fileops-check/nested/")}]}}')"
echo "   PASS: a SUCCEEDED execution appears below within ~30s, and no notification arrives."
echo "   (The machine does no work yet — success means it validated, locked, branched and released.)"

echo "== 2. A copy names both sides and is accepted =="
send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" --arg s "$(now_iso)" \
  '{requestId:$r, actor:$t, operation:"copy",
    source:{space:{kind:"personal", name:$u}, items:[{kind:"file", key:($u+"/fileops-check/one.csv")}]},
    destination:{space:{kind:"personal", name:$u}, prefix:($u+"/fileops-dest/")},
    onConflict:"refuse", submittedAt:$s}')"

echo "== 3. An unauthorized source notifies the ACTOR, not the request's claim =="
# The space named is somebody else's. The actor comes from the verified token, so the refusal is
# addressed to the signed-in user — never to the name in the body.
send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" \
  '{requestId:$r, actor:$t, operation:"delete",
    source:{space:{kind:"personal", name:"someone-else"}, items:[{kind:"file", key:"someone-else/x.csv"}]}}')" \
  "$(space_digest "$USER_BUCKET" someone-else)"
echo "   PASS: the notification inbox shows \"Couldn't delete that: you don't have access…\","
echo "   the execution is FAILED, and logs/service=file-ops/ records the refusal."

echo "== 4. Each protected-location rule refuses, and only the item it names =="
# PER ITEM, not whole-request: the protected folder fails alone and the ordinary one proceeds.
# This is the behaviour the browser has always had for a select-all delete at a space root.
for folder in athenaresults saved_queries archive user_settings; do
  send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" --arg f "$folder" \
    '{requestId:$r, actor:$t, operation:"delete",
      source:{space:{kind:"personal", name:$u},
              items:[{kind:"folder", key:($u+"/"+$f+"/")},
                     {kind:"folder", key:($u+"/fileops-check/nested/")}]}}')"
done
echo "   PASS: four SUCCEEDED executions. Each one's validate-authorize log carries an outcome of"
echo "   \"protected\" for the named folder and NOTHING for fileops-check/nested/ — the second item"
echo "   is undecided and would proceed. A whole-request refusal here would be the regression."

echo "== 5. The space root is refused outright =="
# The third way to select a protected folder: every rule matches the named folder or below it,
# never above. One item of "{user}/" names a subtree containing all four of the folders above.
send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" \
  '{requestId:$r, actor:$t, operation:"delete",
    source:{space:{kind:"personal", name:$u}, items:[{kind:"folder", key:($u+"/")}]}}')"
echo "   PASS: FAILED, and the notification reads \"a whole space can't be worked on in one go\"."

echo "== 6. Two requests in one space do not run at once =="
# THE OBVIOUS TECHNIQUE DOES NOT WORK AND MUST NOT BE RE-DERIVED. Two submits seconds apart both
# return independently, because this machine does no work and the window is milliseconds — the
# table-builder's equivalent check is recorded as unrunnable from the UI for the same reason.
# ONE BATCH, same group, distinct dedup ids: the Pipe starts the second while the first still
# holds the lock.
#
# THE LOAD-BEARING ASSERTION IS THE NEGATIVE ONE: while the first holds the lock there is no
# second execution OPERATING on the space. The loser waits and then proceeds — it is not refused.
BODY_A=$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" \
  '{requestId:$r, actor:$t, operation:"delete", source:{space:{kind:"personal", name:$u}, items:[{kind:"folder", key:($u+"/fileops-check/nested/")}]}}')
BODY_B=$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" \
  '{requestId:$r, actor:$t, operation:"delete", source:{space:{kind:"personal", name:$u}, items:[{kind:"file", key:($u+"/fileops-check/one.csv")}]}}')
aws sqs send-message-batch --queue-url "$QUEUE" --entries "$(jq -nc --arg a "$BODY_A" --arg b "$BODY_B" --arg g "$GROUP" \
  --arg d1 "$(uuid)" --arg d2 "$(uuid)" \
  '[{Id:"a", MessageBody:$a, MessageGroupId:$g, MessageDeduplicationId:$d1},
    {Id:"b", MessageBody:$b, MessageGroupId:$g, MessageDeduplicationId:$d2}]')" >/dev/null
echo "   PASS: BOTH end SUCCEEDED, and logs/service=file-ops/ shows one \"space lock acquired\""
echo "   followed by \"space lock refused\" and a later acquire for the same key — never two"
echo "   acquires with no refusal between them."

echo "== 7. A wedged lock makes the waiter give up rather than wait forever =="
# THE HOLDER MUST BE A DEAD EXECUTION. A live waiter re-claims its own lock on every attempt and
# so refreshes acquiredAt — it would never be stolen, and this check would measure nothing.
aws s3api put-object --bucket "$ADMIN_BUCKET" --key "$LOCK_KEY" \
  --body <(jq -nc --arg a "$(now_iso)" '{version:1, holder:"arn:aws:states:us-east-1:0:execution:wedged:by-hand", acquiredAt:$a}') \
  --content-type application/json >/dev/null
send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" \
  '{requestId:$r, actor:$t, operation:"delete", source:{space:{kind:"personal", name:$u}, items:[{kind:"file", key:($u+"/fileops-check/one.csv")}]}}')"
echo "   PASS: the execution stays RUNNING for ~10 minutes (20 attempts, 30s apart), then FAILS"
echo "   with a notification reading \"something else was already working in that space\"."
echo "   NOT a bare TIMED_OUT — the give-up bound is deliberately well under the machine's ceiling,"
echo "   and a timeout here would mean that inequality has been broken."
echo "   CLEAN UP AFTERWARDS: the lock is left held by a holder that does not exist."
echo "     aws s3api put-object --bucket $ADMIN_BUCKET --key $LOCK_KEY \\"
echo "       --body <(echo '{\"version\":1,\"holder\":null,\"acquiredAt\":null}') --content-type application/json"

echo "== 8. A cross-space move takes TWO locks and releases both =="
echo "   NEEDS A SHARED SPACE the acting user belongs to. Set SHARED_SPACE and re-run this block:"
if [ -n "${SHARED_SPACE:-}" ]; then
  send "$(jq -nc --arg r "$(uuid)" --arg t "$(cat "$TOKEN_FILE")" --arg u "$USERNAME" --arg sp "$SHARED_SPACE" --arg s "$(now_iso)" \
    '{requestId:$r, actor:$t, operation:"move",
      source:{space:{kind:"personal", name:$u}, items:[{kind:"file", key:($u+"/fileops-check/one.csv")}]},
      destination:{space:{kind:"shared", name:$sp}, prefix:($sp+"/")},
      onConflict:"refuse", submittedAt:$s}')"
  echo "   PASS: SUCCEEDED, and logs/service=file-ops/ shows TWO \"space lock acquired\" events and"
  echo "   TWO \"space lock released\" — the second lock is the destination's, and without it a"
  echo "   concurrent delete in that space would run alongside this move."
else
  echo "   SKIPPED — no SHARED_SPACE set. This one is owed until it runs."
fi

echo
echo "== Executions =="
executions_since
echo
echo "== 9. Everything above appears in the structured log =="
echo "   s3://$ADMIN_BUCKET/logs/service=file-ops/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/data.jsonl"
echo "   Every record must carry a populated \`env\` and \`version\`. An empty \`env\` means the"
echo "   verbs shipped without ENV_NAME, which no offline test can see."
