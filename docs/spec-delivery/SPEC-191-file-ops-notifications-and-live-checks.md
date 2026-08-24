# Completed Spec — SPEC-191: File Operations — Notifications, the Link & the Arc's Live Checks

## What was completed?

The file-operations plane now **tells the user what it did**. One producer at the end of the
machine turns the terminal into a single message with a link and a structured payload, and the
notifications wire shape gained the optional field that carries it. Nothing user-visible ships:
the browser still enqueues no file operation, so no user can receive one of these until SPEC-190.

- **The wire shape, both ends.** `cpcommon.notify.emit_notification` and the writer's `apply_create`
  gained an optional `payload`; `normalize` carries it back; `Notification` gained the type.
- **`lambdas/file-ops-notify`** — the plane's twelfth verb and its only outcome producer, wired in
  after `ReleaseLock` on **both** of that state's edges.
- **`focommon.messages`** — the per-item clause and the one-sentence run summary, for all 13
  outcomes.
- **`focommon.notify`** — `outcome_link`, `outcome_payload`, `emit_outcomes`, and `request_payload`
  on the failure path.
- **`focommon.paths.shorten_for_display`** — the guard's private shortener, promoted so the message
  and the sample cannot give two answers to "what does the user read".
- **A `Review conflicts` control** on a notification row, with its `GATED_SURFACES` row.
- **The arc's live checks** — `fixtures/file-ops-plane.sh` §16–23, three existing sections
  sharpened, an approval gate in `e2e.md` and five `owed.md` rows.

## What changed that a reader would not expect

**FR-005 (Help & guides) MOVED to SPEC-190, on the user's decision.** 191 builds first, so nothing
it ships is reachable — except Help, which deploys immediately. A guide saying folder operations
"run in the background and report by notification" would be false until SPEC-190 lands, and the
spec's own AC4 forbids documenting what is not wired end to end. The criteria travel unchanged.

**A COUNT cap could not bound the payload, and the measurement is why.** One conflicted item is
~200 bytes at ordinary key lengths and ~12,000 at this plane's caps: S3 keys are 1,024 bytes of
arbitrary UTF-8 and JSON escaping turns a control character into six. So the payload is bounded by
**bytes as well as count**, enforced by adding conflicted items only while they fit and setting
`more` when any are dropped — which is what makes the pathological case *safe* rather than merely
small. `FILE_OPS_NOTIFIED_PAYLOAD_BYTES` is **1 KiB**, from the marginal budget: the field may not
add more to the worst-case inbox than the row costs **with no payload at all**.

**The estimate was overturned twice, both times by measuring.** 4 KiB was written down first and
the first measurement refused it — and the binding case turned out to be the **plain** one, not the
escape-heavy one, because a control character expands six times inside the JSON payload and only
three in the percent-encoded link beside it, so the row a payload competes against is *smaller*
when the keys are hostile. The diff review then found the second error: that measurement compared
against a row **already carrying the payload head**, weighing the field against itself. The honest
allowance is **1,674 bytes**, not 3,047.

**The head's one unbounded term is capped separately.** Dropping conflicts cannot help when the head
alone is over budget, and nothing validates a destination prefix's LENGTH on the way in. A
hand-crafted envelope with a multi-kilobyte prefix would have pushed the payload past the writer's
ceiling and lost the **whole message**, on the queue whose DLQ is undrained, after the data had
moved. `FILE_OPS_NOTIFIED_PREFIX_BYTES` is S3's key limit — a longer prefix cannot produce a legal
destination key, so that run copied nothing and a re-submit of it is meaningless.

**`ReleaseLock`'s CATCH had to move too, not just its `Next`.** Left pointing at `Succeeded`, a
release that exhausts its `Retry` — one throttle is enough — completes the operation and tells the
user **nothing**, while SPEC-190's per-space gate, which settles on a notification carrying the
`requestId`, holds that space until the machine's ceiling. Both edges now reach the producer.

**The producer is the one Task whose catch reaches a TERMINAL rather than a release.** The lock is
already free by then, and a release is an **overwrite**, not a compare-and-set on the holder — so a
second one would clobber whichever execution had since acquired that space. The graph-walk test's
not-under-the-lock set names it explicitly, with the reason.

**A whole-request FAILURE carries `requestId` too, which is beyond the spec's ACs.** FR-001 AC3's
argument — a reader settles its in-flight record by matching the id — applies verbatim to a run that
failed before the producer ran, and that run settles nothing otherwise. Built deliberately, in
`focommon.notify`'s two failure emitters.

**Six reason codes are worded ONCE, not twice.** `source_missing`, `source_empty`, `copy_failed`,
`source_changed`, `source_delete_failed` and `delete_refused` already had bodies for the failure
sentence, so the item clause resolves through that same table; only the outcomes with no body of
their own are written out. The outcome table is deliberately **not registered as a resolver**:
`Resolver.__init__` marks every key a globally valid reason code, which would let
`TerminalError("duplicate")` pass raise-time validation and undercut `outcomes.py`'s rule that no
per-item outcome may be a whole-request failure reason.

**A `delete`'s link is the common folder of the items' PARENTS.** Over the keys themselves, a
single-item delete yields the item — linking the user into the folder that was just removed. The
parents make the one-item and many-item cases the same computation.

**`?space=` is minted FIRST, and that is not cosmetic.** `NotificationRow` gates the shared variant
on the literal `?space=`; the other parameter order slips the gate, the route never reads the space,
and the user lands in their own files with no banner while the message names a shared one.

**This plane's link is the first built from an arbitrary KEY**, so the prefix is percent-encoded at
mint — every other plane interpolates catalog-constrained names. `isSafeInAppPath` cannot help: it
inspects only the first two characters.

**The reader's id check is "characters that cannot change a URL", not "a UUID".** Every plane mints
`crypto.randomUUID()` today; a regex for that exact shape would couple the reader to one producer's
format and fail closed — silently dropping the field — the day a plane mints anything else.

**A pre-existing gap was found and NOT fixed here.** *(Fixed since, by SPEC-206 — the writer refuses a
`create` whose SQS-stamped `SenderId` names the portal role. The paragraph below records what was true
when this shipped.)* The portal role holds an **unconditioned**
`sqs:SendMessage` on the notifications request queue and the writer takes the body's `username` for
a `create`, so a signed-in browser can already plant a notification in another user's inbox. The
comment above that IAM grant asserts the opposite. Out of scope; what this spec owes and does is
make `apply_create` **refuse** (never truncate) an oversize payload, which is the only server-side
gate the field will ever have.

## What the diff review caught, and it was not cosmetic

**A resolved space carried no `kind` or `name`, so every notification would have shipped with NO
LINK.** `authz` resolved a space to `{bucket, root}`; the producer reads `kind`/`name`, got `None`,
refused to mint a link, and put nulls in the payload where a re-submit's spaces belong — **with a
green suite**, because every fixture in the notifier's tests hand-wrote the shape it wanted. FR-004
would have shipped as a no-op and FR-001 AC4's fields as nulls. The identity now rides out of the
resolver, where the claim has been authorized; the guard is one test that builds the notifier's
input from the real `authorize_source` and the real finaliser rather than a literal, verified by
mutation to fail without the fix.

**The summary sentence contradicted itself on `duplicate`.** Partitioning on "the success outcome,
or not" put it in the residue and opened with "Nothing was moved" — false, since its objects did
land and the link points at them, and flatly contradicted by the next clause. A `noop` read as a
failure for the same reason. The opening is neutral now (`N need your attention`), which is true of
every member of the residue.

**Three smaller ones rode along**: the `more` flag was set after the size check (so a trimmed
payload finished a few bytes over its own budget); the payload's declared TypeScript types promised
far more than `normalize` validated, which SPEC-190 would have trusted when it renders `itemKey` and
`sample` — the payload is now rebuilt field-by-field like the row around it, and a list shortened by
that rebuild sets `more` so it is never read as complete; and the writer's ceiling is now read out
of the Lambda by matching its two operands rather than evaluating them.

## Verification

`pytest lambdas/` (4,465 passing, 97.5% against a 95 floor), `ruff check`, `mypy`, the portal suite
(2,767 passing; coverage 92.86/89.19/92.28/94.79 against 91/86/89/93), `npm run build`,
`tofu -chdir=infra validate`, `scripts/validate_docs.py`.

**Live checks are written and OWED, not run** — the plane is reachable only by hand-crafted
envelopes, and the user-space bucket is writable only through the portal UI. Five `owed.md` rows
point at `fixtures/file-ops-plane.sh` §8b and §16–23.
