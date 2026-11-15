#!/usr/bin/env bash
# Live checks for the file-operations control plane. ONE SCRIPT FOR THE PLANE, NOT ONE PER SPEC.
#
# NOT RUNNABLE AS WRITTEN (found 2026-09-10). Since SPEC-262 the browser holds no token, so
# USAGE step 2 finds nothing in the page. The plane's front door is the API: a signed-in
# `POST /api/v1/enqueue/file-ops` from the portal's own page, naming the signed-in user in
# `x-dq-user`, stamps the actor from the session's token and refuses a body that carries `actor`
# itself, as these do. Send each section's body WITHOUT `actor` through that route instead,
# from the signed-in page — the 2026-09-10 section of docs/testing/sessions.md ran every section it
# reached that way. The sections' EXPECT / PASS text still holds, and so does their DO text except
# §6's single send-message-batch, which the route cannot express: two POSTs in one Promise.all
# stand in for it.
#
# It is named for the plane deliberately. Four specs build this thing, and a script per spec would
# be four files that share a token, a queue URL, a group digest and an envelope builder — the same
# regrowth that took docs/testing/ to sixteen files of four genres. A spec that owes a CLI check
# ADDS A SECTION HERE and points its owed.md row at that section; it does not add a file.
# scripts/validate_docs.py refuses a spec-numbered name in this directory so the next session
# cannot re-derive the other answer.
#
# WHY A SCRIPT AND NOT STEPS IN e2e.md: nothing in the browser reaches this plane yet. The enqueue
# service exists and no gesture calls it, so every check here is a hand-crafted envelope on the
# CLI. Each one is also an `owed.md` row; running this is what discharges them.
#
# WHEN IT GOES AWAY: the spec that gives the browser its async model makes most of this reachable
# from a signed-in session. At that point the checks that can be driven from the UI move into
# e2e.md's file-browser section and this file keeps only what a browser still cannot express.
#
# A SHARED LAYER'S IMPORT-TIME FAILURE ONLY SHOWS AT COLD START. Offline tests cannot see a verb
# shipped without its layer — the fleet has an outage on record for exactly that — so these are
# real invocations against the deployed plane, not a simulation of one.
#
# USAGE
#   1. Sign in to the portal in a browser as the account you want to act as.
#   2. Copy its ID token into /tmp/idtoken (no trailing newline). Since SPEC-262 the browser holds no
#      token: the portal server keeps it in the session store. Load any portal page first, so the
#      server refreshes a token near expiry, copy the __Host-dq_session cookie's value from the
#      browser's developer tools, and read the item it names. The cookie is a 30-day credential, so
#      read it without echo or history, and sign out of the portal once the check is done:
#        read -rs COOKIE
#        PK="session#$(printf %s "$COOKIE" | shasum -a 256 | cut -d' ' -f1)"
#        aws dynamodb get-item --table-name dat-prod-sessions --consistent-read \
#          --key "{\"pk\":{\"S\":\"$PK\"}}" --projection-expression idToken \
#          --query Item.idToken.S --output text | tr -d '\n' > /tmp/idtoken
#   3. USERNAME=alice ./file-ops-plane.sh
#
# The token is read, never minted: the plane verifies it offline against the pool's JWKS, and a
# token this script forged would be refused at the front door in a way that reads exactly like the
# check failing.
#
# WHO YOU ARE WHEN YOU RUN EACH PART, AND IT IS NOT ONE ANSWER. There are three roles here and
# conflating them is how a session stalls halfway through:
#
#   1. THE ACTING USER — the signed-in portal account. Everything in the user-space bucket is
#      created and inspected THROUGH THE PORTAL UI as this person: upload, new folder, delete. A
#      laptop IAM user cannot read or write dat-prod-user-space, and the verification role this
#      would otherwise want is deliberately not created. Do not reach for "an assumed role".
#   2. THE REQUEST SENDER — the same person, whose ID token this script reads from /tmp/idtoken and
#      puts in an envelope. The plane verifies it offline against the pool's JWKS, so the token is
#      READ, never minted.
#   3. AN OPERATOR — credentials that can write an arbitrary object and call DeleteObjects
#      directly. ONLY §11 and §14 need this, and only because they probe what S3 itself answers.
#      Without operator credentials those two rows stay OWED; every other section is runnable
#      without them.
#
# EXPECTED FIXTURES in the acting user's own space, created through the browser beforehand:
#   {USERNAME}/fileops-check/one.csv      any small file
#   {USERNAME}/fileops-check/nested/      a folder with at least one file in it
#   {USERNAME}/fileops-dest/              an empty folder
# THESE ARE REAL AND THE PLANE NOW REALLY MOVES THEM. That was not true when this script was
# written — the machine ended in a placeholder — so a section that reads as though nothing is
# touched is a section that has not been re-read since. Treat every fixture below as disposable and
# recreate it between runs.

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
echo "   PASS: a SUCCEEDED execution appears below within ~30s, the folder is GONE from the file"
echo "   browser, and ONE notification arrives reading \"Deleted 1 item.\""
echo "   (Both halves matter: the notification is the completion channel, so a run that did the"
echo "   work and said nothing is a failure of this plane even though the execution is green.)"

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
echo "   PASS, AND IT IS NOT THE TABLE-BUILDER'S. That plane REFUSES its loser; this one makes it"
echo "   WAIT, so the observation is a cycle rather than a refusal:"
echo "     - both executions end SUCCEEDED;"
echo "     - execution B's history shows at least one WaitForLock -> AcquireLock cycle;"
echo "     - logs/service=file-ops/ holds TWO lock claims for this space's key, B's after A's"
echo "       release, and NO stale-steal warning between them."
echo "   USE A SEVERAL-HUNDRED-OBJECT SOURCE for A (fileops-big/ below is ideal). With a small"
echo "   folder A finishes before the Pipe even starts B, both run cleanly, no cycle appears, and"
echo "   the check passes while measuring nothing — which is exactly how the table-builder's own"
echo "   equivalent failed."

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
  echo
  echo "   8b. AND THE HALF THAT PROVES DEADLOCK-FREEDOM: a request that takes the first lock and"
  echo "   LOSES the second must release the first. Nothing offline proves this — it is the whole"
  echo "   reason the two are taken in digest-sorted order."
  echo "   RECIPE: compute BOTH digests with space_digest and wedge the lock whose digest sorts"
  echo "   SECOND (as in §7). Wedging the one that sorts first proves nothing: the request loses the"
  echo "   first lock, holds nothing, and the other lock reads free whatever the code does."
  echo "   Then send the same cross-space move."
  echo "   PASS: EVERY acquire-lock span that logs \"space lock not yet available\" also logs"
  echo "   \"space lock released\" for the space that sorts FIRST — that record is written only after"
  echo "   the conditional release succeeds — and that lock reads holder null during each Wait and"
  echo "   after the give-up. released_partial on the same record counts locks HELD, not released,"
  echo "   so it proves nothing on its own. A held first lock is the deadlock, and it blocks that"
  echo "   space for hours."
else
  echo "   SKIPPED — no SHARED_SPACE set. This one is owed until it runs."
fi

echo
echo "== Executions =="
executions_since
echo
echo "== 9. Everything above appears in the structured log =="
echo "   s3://$ADMIN_BUCKET/logs/service=file-ops/year=$(date -u +%Y)/month=$(date -u +%m)/day=$(date -u +%d)/file-ops_logs_$(date -u +%Y_%m_%d).jsonl"
echo "   Every record must carry a populated \`env\` and \`version\`. An empty \`env\` means the"
echo "   verbs shipped without ENV_NAME, which no offline test can see."

# ── SPEC-189: the transfer, the source deletion and the terminals ────────────────────────────────
#
# These six are what the offline suites structurally cannot settle. The first four need a real Map
# Run; the fifth needs S3 itself to answer a question the docs do not; the sixth needs the deployed
# role.

echo
echo "== 10. A real move of a folder past the 1,000-key pagination boundary =="
echo "   FIXTURE — BUILT THROUGH THE PORTAL, because the acting user is the only identity that can"
echo "   write this bucket (see WHO YOU ARE, above):"
echo "     1. On your laptop:  mkdir -p /tmp/fileops-big && cd /tmp/fileops-big"
echo "                         seq 1 1200 | xargs -I{} sh -c 'echo {} > f{}.txt'"
echo "     2. In the portal:   Files -> New folder -> fileops-big -> open it -> Upload -> drag all"
echo "                         1,200 files onto the drop zone in ONE go."
echo "     3. EXPECT ~4-7 MINUTES for the queue to drain (it uploads a few at a time and reports"
echo "        each). Leave the tab FOREGROUNDED and do not navigate away."
echo "     4. Confirm the count before using it: the folder's Details panel reports the object"
echo "        count, and it must read 1200 — a partially drained queue is what makes a pagination"
echo "        check pass while testing one page."
echo "   Then send a move of that folder to \$USERNAME/fileops-out/ and watch the execution."
echo "   PASS: every object arrives at the destination, the SOURCE FOLDER IS EMPTY afterwards, and"
echo "   the terminal's outcome list names the item 'moved'. The Map Run's export under"
echo "   s3://$ADMIN_BUCKET/file-ops/<requestId>/results/ must account for EVERY manifest line —"
echo "   a shortfall is a whole-request failure by design, so a green run with missing objects"
echo "   would mean the reconciliation is not running."

echo
echo "== 11. The batch path's error CODE strings — the check no doc can replace =="
echo "   AWS documents that DeleteObjects answers HTTP 200 with a failed object in an <Error>"
echo "   element, and does NOT document the Code string it uses. TWO strings are needed:"
echo "     (a) the PRECONDITION MISMATCH code, for a conditional delete whose ETag has moved;"
echo "     (b) the ALREADY-GONE code, for a key a previous attempt already removed."
echo "   (b) matters as much as (a): a retried delete-source meets keys its predecessor deleted, and"
echo "   reading those as failures reports correctly-moved items to the user as 'duplicate'."
echo "   RECIPE (run as an operator, not as the plane):"
echo "     aws s3 cp /dev/null s3://$USER_SPACE_BUCKET/$USERNAME/probe.txt"
echo "     ETAG=\$(aws s3api head-object --bucket $USER_SPACE_BUCKET --key $USERNAME/probe.txt --query ETag --output text)"
echo "     aws s3 cp /dev/null s3://$USER_SPACE_BUCKET/$USERNAME/probe.txt   # change it"
echo "     aws s3api delete-objects --bucket $USER_SPACE_BUCKET \\"
echo "       --delete \"{\\\"Objects\\\":[{\\\"Key\\\":\\\"$USERNAME/probe.txt\\\",\\\"ETag\\\":\\\$ETAG}],\\\"Quiet\\\":false}\""
echo "     # then repeat against a key that is ALREADY DELETED for (b)."
echo "   PASS: both codes are members of focommon/delete.py's _PRECONDITION_CODES and _ALREADY_GONE."
echo "   If either is not, ADD IT — an unrecognised code currently fails the item, which is the safe"
echo "   direction but reports a false failure."

echo
echo "== 12. A move whose source is MODIFIED between the copy and the delete =="
echo "   THE WINDOW HAS TO BE THE RIGHT ONE, and the naive staging passes vacuously. \"Between the"
echo "   copy and the deletion\" is SECONDS on a small folder. The reachable window is a LONG MAP"
echo "   RUN: an object copied EARLY, overwritten while the Map is still working through the rest."
echo "   Modify an object BEFORE it is copied and the new bytes are what copy, the ETags agree, the"
echo "   item succeeds, and the check reports a pass having tested nothing."
echo "   RECIPE:"
echo "     1. Send a move of \$USERNAME/fileops-big/ (§10's 1,200-object fixture)."
echo "     2. Watch the Map Run; once it reports a few hundred items processed, overwrite an object"
echo "        from the FIRST batch by re-uploading it through the portal (Upload -> Overwrite)."
echo "        The single-file upload path takes no lock, which is what makes this reachable at all."
echo "   PASS: that item ends as 'duplicate' with reason 'source_changed' — NOT a silent skip and"
echo "   NOT a success. The user holds the data in two places and only they can choose which to"
echo "   keep, so the outcome has to say so."

echo
echo "== 13. A delete of a folder holding a NESTED DO_NOT_DELETE.txt =="
echo "   FIXTURE:"
echo "     aws s3 cp /dev/null s3://$USER_SPACE_BUCKET/$USERNAME/fileops-marked/keep/DO_NOT_DELETE.txt"
echo "     aws s3 cp /dev/null s3://$USER_SPACE_BUCKET/$USERNAME/fileops-marked/ordinary.txt"
echo "   Send a delete of \$USERNAME/fileops-marked/."
echo "   PASS: the marker SURVIVES and ordinary.txt is GONE. Only true because assert_item_deletable"
echo "   is scoped per item — a whole-list refusal would leave the whole folder untouched, and no"
echo "   refusal at all would fail the batch part way through."

echo
echo "== 14. Does S3 ENFORCE the conditional delete on these buckets? =="
echo "   THE GATE ON CONDITIONAL_DELETE_ENABLED. focommon/delete.py ships with the HEAD-compare path"
echo "   ACTIVE because a service model carrying ObjectIdentifier.ETag proves only that botocore"
echo "   will SERIALIZE the condition — not that S3 honours it. A serialized-but-ignored condition"
echo "   deletes a changed source silently, with versioning off, which is this plane's worst outcome."
echo "   RECIPE: take a real ETag, change the object, then delete it WITH the stale ETag (see §11)."
echo "   PASS: the delete is REFUSED. Only then flip CONDITIONAL_DELETE_ENABLED to True."
echo "   FAIL, or ambiguous: leave it False. The HEAD-compare path is correct, merely racier."

echo
echo "== 15. The execution role's IAM simulation, every denial PAIRED with a control =="
echo "   Against the DEPLOYED role, because a rendered policy is not the role that exists."
echo "   ROLE=arn:aws:iam::<account>:role/<project>-<env>-file-ops-execution-role"
echo "   Each denial below must be run beside an ALLOWED control on the same action — an implicitDeny"
echo "   alone cannot tell an ungranted action from a wrong resource ARN."
echo "     DENY:  s3:DeleteObject on $USER_SPACE_BUCKET/alice/athenaresults/r.csv"
echo "     ALLOW: s3:DeleteObject on $USER_SPACE_BUCKET/alice/reports/r.csv"
echo "     DENY:  s3:DeleteObject on $USER_SPACE_BUCKET/alice/anything/DO_NOT_DELETE.txt"
echo "     DENY:  s3:PutObject   on $USER_SPACE_BUCKET/alice/user_settings/s.json"
echo "     ALLOW: s3:PutObject   on $USER_SPACE_BUCKET/alice/out/r.csv"
echo "   Repeat every row against $SHARED_SPACE_BUCKET — the two buckets' Denies are written"
echo "   separately and a folder present in one and missing from the other is exactly the shape"
echo "   this catches."

# ── SPEC-191: the notification, its link and its payload ────────────────────────────────────────
#
# THE NOTIFICATION IS THE COMPLETION CHANNEL, not a courtesy. Everything below is therefore a
# failure of the plane when it is missing, even though the execution is green.
#
# INSTRUMENT THE TAB FIRST, EVERY TIME. The inbox poll is PAUSED while the tab is hidden, so a
# perfectly healthy run looks hung the moment you switch windows to read the CLI. Paste this into
# the console after every full page load (it is §1 of e2e.md):
#
#   Object.defineProperty(document,'visibilityState',{get:()=>'visible',configurable:true});
#   Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});
#   document.dispatchEvent(new Event('visibilitychange'));
#
# AND READ THE RAW ROW, not only the rendered one. The payload is not displayed anywhere until the
# browser's async model ships, so the only way to see it is the document itself: DevTools ->
# Network -> notifications.json -> Response. The bell polls every 60s, so it will be there within a
# minute of the run finishing; hit the refresh control on /notifications to force one sooner.

echo
echo "== 16. A wholly successful run produces ONE message that names the operation and the count =="
echo "   DO:  send a copy of \$USERNAME/fileops-check/nested/ into \$USERNAME/fileops-dest/."
echo "   EXPECT: exactly ONE new notification reading:"
echo "     Copied 1 item to \"fileops-dest\"."
echo "   and NOT one message per object, and NOT one per item. Clicking it lands you in"
echo "   fileops-dest/ — the DESTINATION, because that is where the result is."
echo "   AND THE PAYLOAD: the row in notifications.json carries payload.requestId equal to the"
echo "   requestId you sent, on this clean run with nothing to re-submit. Its absence is what would"
echo "   leave a browser's in-flight record unsettled until the machine's ceiling."

echo
echo "== 17. A PER-ITEM partial outcome, in ONE request =="
echo "   THE CHECK THE WHOLE PER-ITEM MODEL EXISTS FOR: one item refused while another completes."
echo "   FIXTURE (through the portal): create \$USERNAME/fileops-dest/one.csv so it is in the way,"
echo "   and leave \$USERNAME/fileops-check/nested/ alone."
echo "   DO:  send ONE copy request whose items are BOTH fileops-check/one.csv and"
echo "        fileops-check/nested/, destination \$USERNAME/fileops-dest/, onConflict \"refuse\"."
echo "   EXPECT: ONE notification, naming both halves —"
echo "     Copied 1 of 2 items to \"fileops-dest\". 1 needs your attention: \"one.csv\" - something"
echo "     is already in the way there. ... Sending it again with overwrite turned on replaces what"
echo "     is there, and that cannot be undone."
echo "   AND: nested/ really is at the destination, one.csv at the destination is UNCHANGED (check"
echo "   its Last modified), and the notification row shows a \"Review conflicts\" link."
echo "   FAIL: a whole-request refusal — nothing copied — or two separate notifications."

echo
echo "== 17b. THE SAME COLLISION UNDER \"overwrite\" SAYS SOMETHING ELSE =="
echo "   THE HALF §17 CANNOT SEE, AND IT IS NOT A SECOND SPELLING OF IT. \"overwrite\" does not"
echo "   mean \"write over anything\": the guard leaves a destination object whose Last modified is"
echo "   at or after the request's submittedAt alone, deliberately, so that a file which arrived"
echo "   after the user pressed the button is not destroyed. That item is refused with overwrite"
echo "   ALREADY ON, so §17's advice is the one sentence it must not get."
echo "   FIXTURE (through the portal): \$USERNAME/fileops-dest2/ holding old.csv, and both"
echo "   \$USERNAME/fileops-check/old.csv and \$USERNAME/fileops-check/new.csv to send."
echo "   DO:  1. Build the body — a copy of BOTH files into \$USERNAME/fileops-dest2/, onConflict"
echo "           \"overwrite\" — and stamp submittedAt NOW. The caller supplies that field and the"
echo "           plane only refuses one in the future, so this is the instant the guard measures"
echo "           against."
echo "        2. Upload fileops-dest2/new.csv through the portal, so it is newer than the stamp."
echo "        3. Send the body."
echo "   EXPECT: ONE notification —"
echo "     Copied 1 of 2 items to \"fileops-dest2\". 1 needs your attention: \"new.csv\" -"
echo "     something was put there after this was sent, so what is there was left alone rather"
echo "     than replaced. Please look at the destination - sending it again now would replace what"
echo "     is there, and that cannot be undone."
echo "   AND THE DATA, which is the half the sentence is about: dest2/old.csv WAS replaced (its"
echo "   Last modified moved to the run), and dest2/new.csv was NOT (it still holds what you"
echo "   uploaded in step 2)."
echo "   AND THE PANEL THE ROW LINKS TO, in the same sitting: click \"Review conflicts\". It reads"
echo "   \"Something was in the way, so Data Quarry left it alone\" and groups the item under"
echo "   \"Something is in the way\" — neither saying ALREADY, which is false here. The browser"
echo "   chooses that wording from the outcome alone, since the payload carries no reason code, so"
echo "   it says only what holds under both answers."
echo "   FAIL: §17's sentence — \"Sending it again with overwrite turned on ...\" — which names a"
echo "   setting this request already had on and so reads as a broken feature; or a panel saying"
echo "   something was ALREADY in the way, which contradicts the notification that opened it."

echo
echo "== 18. The payload carries what a RE-SUBMIT needs =="
echo "   Read the row for §17 out of notifications.json (Network tab -> Response). Its payload must"
echo "   carry, at minimum:"
echo "     requestId, operation:\"copy\","
echo "     source:{kind:\"personal\", name:\"\$USERNAME\"},"
echo "     destination:{kind:\"personal\", name:\"\$USERNAME\", prefix:\"\$USERNAME/fileops-dest/\"},"
echo "     conflicts:[{itemKey:\"\$USERNAME/fileops-check/one.csv\", kind:\"file\", sample:[...]}]"
echo "   THE SOURCE SPACE IS THE ONE TO CHECK — it is not derivable from an absolute key, and"
echo "   without it a re-submit built from this notification cannot name where the items came from."

echo
echo "== 19. A shared-space destination puts ?space= in the link, FIRST =="
echo "   NEEDS SHARED_SPACE. DO: copy a file from your personal space into the shared one."
echo "   EXPECT: the notification's link is /files?space=<name>&prefix=<name>/... — space first,"
echo "   as every plane's link puts it. Click it: you land in the SHARED space, with its name in"
echo "   the header."
echo "   FAIL, and it is a silent one: landing in your OWN files with no banner. That is what a"
echo "   link that does not name the space does — the route resolves the personal space and then"
echo "   discards a prefix that does not start with your personal root. (The order of the two"
echo "   parameters no longer matters to the row's feature gate, which parses the link.)"

echo
echo "== 20. A DELETE links to the folder its items shared, not to what was deleted =="
echo "   DO:  delete BOTH \$USERNAME/fileops-check/nested/ and \$USERNAME/fileops-check/one.csv in"
echo "        one request."
echo "   EXPECT: \"Deleted 2 items.\", and the link lands you in fileops-check/ — the folder that"
echo "   held them."
echo "   THEN repeat with a SINGLE folder item. The link must still land you in its PARENT. Landing"
echo "   inside the folder that was just removed — an empty listing where a folder used to be — is"
echo "   the defect this rule exists for, and it only appears with one item."

echo
echo "== 21. A key with a query character survives the round trip =="
echo "   FIXTURE (through the portal): a folder literally named  a&b?c  holding one file."
echo "   DO:  copy something into it."
echo "   EXPECT: the notification's link carries the prefix PERCENT-ENCODED (a%26b%3Fc), and"
echo "   clicking it lands you in that exact folder — not at your space root, and not in a folder"
echo "   named \"a\"."
echo "   This is the one link rule that differs from every other plane's: those interpolate"
echo "   constrained names, and this one interpolates an arbitrary user-controlled key."

echo
echo "== 22. A whole-request FAILURE also carries its requestId =="
echo "   DO:  re-run §5 (the space root refused outright)."
echo "   EXPECT: the refusal notification's payload carries {requestId: ...} matching what you"
echo "   sent. Without it, a browser tracking that request in flight never settles it — the run"
echo "   failed, so no outcome producer ever ran."

echo
echo "== 23. A message is capped, and says how much it is not showing =="
echo "   DO:  send a delete of SIX protected folders in one request (repeat §4's shape with"
echo "        athenaresults, saved_queries, archive, user_settings and two more items)."
echo "   EXPECT: ONE notification naming THREE of them and ending \"And 3 others not listed here.\""
echo "   A sample a reader could mistake for the whole list is worse than a count alone — and the"
echo "   inbox is capped at 200 rows and downloaded whole on every poll, which is what a message"
echo "   per item would flood."
