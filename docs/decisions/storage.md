# Storage, and the fact S3 is not a filesystem

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [File ops = filesystem UX](#file-ops--filesystem-ux)
- [A partial teardown never frees the space name (SPEC-151)](#a-partial-teardown-never-frees-the-space-name-spec-151)
- [An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)](#an-unreadable-settings-document-is-quarantined-never-deleted-and-never-overwritten-spec-159)
- [The file-send plane is its own, and its front door is bounded by a chain (SPEC-164)](#the-file-send-plane-is-its-own-and-its-front-door-is-bounded-by-a-chain-spec-164)
- [A received file lands in `shared_files/{sender}/`, and one function builds every key (SPEC-165)](#a-received-file-lands-in-shared_filessender-and-one-function-builds-every-key-spec-165)
- [The file-send exclusion rule is anchored at the space root, not the listing prefix (SPEC-165)](#the-file-send-exclusion-rule-is-anchored-at-the-space-root-not-the-listing-prefix-spec-165)
- [The expansion caps are sized by memory and makespan, and the obvious models miss both (SPEC-165)](#the-expansion-caps-are-sized-by-memory-and-makespan-and-the-obvious-models-miss-both-spec-165)
- [An expected refusal is a return value, and a conflict is per item NAME (SPEC-166)](#an-expected-refusal-is-a-return-value-and-a-conflict-is-per-item-name-spec-166)
- [The transfer caps are three, and each is measured against a different budget (SPEC-166)](#the-transfer-caps-are-three-and-each-is-measured-against-a-different-budget-spec-166)
- [One producer says every per-recipient outcome, and the link carries the recipient's own root (SPEC-167)](#one-producer-says-every-per-recipient-outcome-and-the-link-carries-the-recipients-own-root-spec-167)
- [A saved query is a FILE, and the folder holding it is ordinary except in one respect (SPEC-173)](#a-saved-query-is-a-file-and-the-folder-holding-it-is-ordinary-except-in-one-respect-spec-173)
- [Every `DO_NOT_DELETE.txt` is hidden by BASENAME, and the whole arc needs no IaC change (SPEC-173)](#every-do_not_deletetxt-is-hidden-by-basename-and-the-whole-arc-needs-no-iac-change-spec-173)
- [`saved_queries/` is gated on `query`, and the gate is not the refusal (SPEC-173)](#saved_queries-is-gated-on-query-and-the-gate-is-not-the-refusal-spec-173)
- [A save chooses its space, and one KEY rule decides what that replaces (SPEC-175)](#a-save-chooses-its-space-and-one-key-rule-decides-what-that-replaces-spec-175)
- [A file operation on more than one file belongs on a plane, and the boundary is the SELECTION (SPEC-187)](#a-file-operation-on-more-than-one-file-belongs-on-a-plane-and-the-boundary-is-the-selection-spec-187)
- [The file-ops lock's loser WAITS where the table-builder's is refused (SPEC-187)](#the-file-ops-locks-loser-waits-where-the-table-builders-is-refused-spec-187)
- [An item copied into itself is refused PER ITEM, where a containment breach fails the request (SPEC-187)](#an-item-copied-into-itself-is-refused-per-item-where-a-containment-breach-fails-the-request-spec-187)
- [The source deletion removes only CONFIRMED-COPIED keys, never a prefix listing (SPEC-187, diverging from SPEC-169)](#the-source-deletion-removes-only-confirmed-copied-keys-never-a-prefix-listing-spec-187-diverging-from-spec-169)
- [The collision unit is the derived destination KEY, and that is what preserves merging (SPEC-188)](#the-collision-unit-is-the-derived-destination-key-and-that-is-what-preserves-merging-spec-188)
- [A conflict is one item's outcome, and the list is created once and carried forward (SPEC-188)](#a-conflict-is-one-items-outcome-and-the-list-is-created-once-and-carried-forward-spec-188)
- [The commit gate is per ITEM, so the graph proves less than SPEC-169's did (SPEC-189)](#the-commit-gate-is-per-item-so-the-graph-proves-less-than-spec-169s-did-spec-189)
- [The source deletion: what it removes, and what it is conditional on (SPEC-189)](#the-source-deletion-what-it-removes-and-what-it-is-conditional-on-spec-189)
- [Bytes go to S3 presigned; small text goes through the API (SPEC-198)](#bytes-go-to-s3-presigned-small-text-goes-through-the-api-spec-198)
- [An upload's shape is the server's decision, and a part is sized so the expiry premise stops mattering (SPEC-216)](#an-uploads-shape-is-the-servers-decision-and-a-part-is-sized-so-the-expiry-premise-stops-mattering-spec-216)
- [The folder-recursive functions are deleted, not ported, and the flag stops being a fallback (SPEC-198)](#the-folder-recursive-functions-are-deleted-not-ported-and-the-flag-stops-being-a-fallback-spec-198)
- [The free-name probe moved to the API, not to the plane (SPEC-198, amends SPEC-187)](#the-free-name-probe-moved-to-the-api-not-to-the-plane-spec-198-amends-spec-187)
- [An app-managed path is built by one function per tree, and a sweep refuses a second (SPEC-218, superseded in part by SPEC-219)](#an-app-managed-path-is-built-by-one-function-per-tree-and-a-sweep-refuses-a-second-spec-218-superseded-in-part-by-spec-219)
- [Both homes of a moving folder are admitted before either is written to (SPEC-219)](#both-homes-of-a-moving-folder-are-admitted-before-either-is-written-to-spec-219)
- [The folders moved, and six Deny mirrors did not move with them (SPEC-220)](#the-folders-moved-and-six-deny-mirrors-did-not-move-with-them-spec-220)

## Fences

The product presents filesystem UX over a store with **no move or rename**: every one is
`CopyObject` + `DeleteObject`, folder operations are recursive and **non-atomic**, and collisions
warn and confirm. Versioning is off, which is what makes a failure between those two steps
unrecoverable — revisit before real user data lands.

- **A received file lands in `shared_files/{sender}/`, built by ONE function** — an AST sweep forbids
  a second. Keying by item **name** forces the two refusals an overlapping selection needs.
- **Exclusion rules anchor at the listing prefix**, which is whichever item the user picked — reuse
  elsewhere silently drops files.
- **A duplicate is `(kind, key)`, never the key alone.** One key can arrive as both a file and a
  folder; collapsing on the key ships a zero-byte placeholder and reports success.
- **Saved queries are ordinary `.sql` files** in a visible folder with exactly one protection: the
  folder itself is undeletable. Every `DO_NOT_DELETE.txt` is hidden by **basename**.
- **An unreadable settings document is quarantined, never deleted and never overwritten**, and a
  **newer** schema is refused untouched — the parse is three-way, version checked before shape.
- **Bytes go to S3 presigned; small text goes through the API**, and the document route's **byte cap
  is what holds the line** — without it it is a second upload path that works perfectly to 6 MB. The
  routes never parse and never re-serialise. Bytes go over **`XMLHttpRequest`**, which is a
  requirement: `fetch` fires no upload-progress event, so it uploads correctly and leaves the bar at
  0% — assert an **intermediate** value. **The SERVER decides whether an upload is one `PUT` or
  multipart**, so the browser holds no threshold; a URL is minted immediately before redemption,
  **per file or per part, never batched**, and a retried part **re-mints**. Aggregate progress is
  the per-part **maximum**, monotonic across a retry. The 5 GiB ceiling is a refusal on the
  **declared** size — a courtesy, not enforcement, since the API keeps no record of an upload.
- **The four folder-recursive browser functions are DELETED, not ported** — that loop belongs on the
  plane. So `asyncFileOperations` off makes a folder **unavailable** — and any multi-item selection
  too, since the gate refuses every shape the routing rule sends to the plane — refused **at the
  control**: Copy, Move and Delete are `aria-disabled` with the reason. The
  services' **per-item** `PlaneRequired` refusal, which lets the files beside a folder go through,
  is reachable only past the control: a copy or move whose destination resolves to no known space,
  or any gesture confirmed after the flag turned off while its dialog was open — the control
  decides when it renders, `dispatch` when it runs.
- **The free-name probe moved to the API, not to the plane** — 999 round trips would be strictly
  worse than the loop it replaced. `numberedName` lives in Python only, and **exhaustion is now
  distinguishable from failure** (409 + `attempts`), which it was not.
- **An app-managed path is BUILT by three functions per tree** — the SINGULAR builder is where a
  write goes, the PLURAL one is every root-anchored comparison, and the SEGMENT one is every
  any-depth scan. The plural spelled both homes as literals while a moving folder had two, so that
  moving the write could not drag every comparison to a third place; with one home left it
  delegates, and each tree guards the delegation directly because no VALUE can tell a derived
  prefix from a literal one. A CI sweep refuses a declaration or construction outside the owners,
  and **no builder normalizes** (the FIFO group id digests one).
- **A rule that mirrors a SHARED-bucket Deny scans segments, and it must scan for the folder's
  segments rather than its NAME.** The shared Denies put a wildcard where the space name goes and an
  S3 resource wildcard matches `/`, so they reach the folder at any depth — which is why these rules
  exist. Six of them were written as `name in segments`, fed by no builder, and every one silently
  outlived the move: the Deny became `*/system_settings/archive/*` while they went on refusing
  `finance/archive/`, a folder that is now the user's. **This class fails SAFE**, which is what let
  it sit unnoticed behind a green suite — a pair test that only asserts the refusal cannot see it,
  and only a row expecting `null` at the retired name can. They all read `app_managed_segments` now.
- **A rule that builds its prefix from a PARAMETER is invisible to that sweep** — two were — so it
  owes a pair test instead. And **a pair test asserts which folder the refusal NAMES, not just its
  reason code**: once the parent prefix joins the same list, a rule that learned one home still
  refuses the other, same code, different rule. A pair test can also be structurally vacuous — where
  every second home is a descendant of a prefix already in the list, no key distinguishes the two
  builders, and only saying so keeps the test honest.
  What breaks the coming move is **depth**, not spelling: a `{root}{name}/` rule stops matching at
  depth two and denies nobody. `archive` is **three facts** and only the receipt folder moves; the
  vault segment and `arcommon.plan.PREFIX` stay, pinned equal by an `ACCEPTED_` tripwire.

## File ops = filesystem UX

Download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md → *Constraints that shape the system*.

## A partial teardown never frees the space name (SPEC-151)

`delete_objects` and `batch_delete_table` both answer **HTTP 200 with a per-item `Errors` array** — a
key or table that failed individually does not raise. Both return values were discarded, so a
partially-failed teardown was indistinguishable from a complete one, and `delete_space` went on to
`reg.delete(space)` — the line commented "LAST — the name is now free to reuse". The next space
created with that name would inherit another tenant's objects.

Both helpers now raise `teardown.TeardownIncompleteError`, and the rule is: **a teardown that could
not finish must leave the registry record intact.** The record is what reserves the name, so keeping
it is what stops reuse; the caller's existing `except` already records a terminal `failed`, and
`reg.delete` is inside the `try` it never reaches. `forget-space` inherits this for free — both verbs
share the helpers.

Three details that are decisions rather than implementation:

- **Counts, never keys.** The message reaches logs and the registry's `failed` record, and the field
  rule binds what a call site chooses to emit. "3 object(s) under `sales/` could not be deleted" is
  enough to tell a partial failure from a total one.
- **Every page is attempted before raising.** A denial on one key must not strand the rest of the
  space's objects, and the count is only meaningful whole.
- **The Glue raise lands BEFORE `delete_database`.** Dropping a database whose tables survived is how
  the catalog and the bucket start disagreeing.

This meets **SPEC-054**'s written acceptance criterion — teardown leaves "never a dangling …
half-deleted resource" — which had been recorded and never implemented. **Do NOT "improve" this by
deleting the record and reporting the failure elsewhere:** the record IS the lock.

## An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)

A `user_settings/` read-modify-write that cannot read the live body **copies it aside and then
writes**, rather than refusing forever (the previous behaviour) or committing the empty document
over it (the behaviour before that). The copy is a **precondition**: if it fails the write is
refused exactly as before. **A failed quarantine must never become a silent overwrite.**

The refusal it replaces had no way out. `user_settings/` denies `s3:DeleteObject`, the bucket is
unversioned, there is no admin UI and there never will be (out of scope) — so one unreadable
document permanently disabled saving queries and recording history for that user, and the only
honest advice was "Contact the Administrator", whose only tool is the AWS console.

**A newer schema is not corruption, and quarantining one would BE the data loss this prevents.**
The classifier (`lib/s3Json.classifyDocument`) reports three outcomes, not two, and checks the
version **before** the shape — a `version: 2` document is newer whatever else it contains, because a
newer schema is free to have renamed the field this build validates. A newer document is refused
untouched and answered with "reload the page"; only `unparseable` is ever copied.

**The quarantine key carries a random token as well as a timestamp, and that is load-bearing.**
`CopyObject` copies whatever is live at copy time and nothing binds the copy to the body that was
classified. Two tabs finding the same corrupt document in the same second, keyed on a clock alone,
would collide: the first sets the corrupt bytes aside and repairs the document, the second copies
the now-**repaired** document over the first one's quarantine object — destroying the only surviving
copy, on a folder that denies delete. The token makes the loser write a redundant object instead.
Do **not** "simplify" the key back to a bare timestamp. (The ordinary last-writer-wins race on the
document itself is untouched and still accepted; `IfMatch` writes are a separate, complementary fix
that this neither needs nor blocks.)

**No IAM change, deliberately.** Everything is `GetObject` + `PutObject` inside the user's own
prefix — which is why the quarantine key is a sibling of its source rather than a separate folder.
Two consequences follow and are recorded here rather than discovered later:

- **Quarantine objects are themselves undeletable.** They inherit the `user_settings/` delete deny,
  so neither the app nor the user can remove one — only an administrator working directly in the
  console can. Accepted: one object per genuine corruption event is a smaller problem than the
  evidence being destroyed.
- **Accumulation is not a loop.** The document written after a quarantine is one the app serialized
  itself, so a second quarantine requires a second, independent corruption.

**Rejected, and recorded in the spec so they are not re-proposed:** granting the portal role
`DeleteObject` under `user_settings/` (trades away a standing safety property for convenience, and
destroys the only copy of what the user had); "click Save again to replace" (reintroduces the loss
behind a confirmation the user cannot make informed, since they cannot see the document); repairing
the document in place (a guess presented as a recovered library); writing the copy from bytes
already in memory (carries an unbounded untrusted body out through the parse contract, and costs a
second `GetObject`); and a fixed quarantine key overwritten each time.

## The file-send plane is its own, and its front door is bounded by a chain (SPEC-164)

**Decision.** "Send these files to Bob" gets its **own control plane** — its own FIFO queue, DLQ,
Pipe, Standard state machine, execution role and `fscommon` domain layer — rather than becoming a
mode on table share's.

**Why not a mode.** The two features share an *algorithm* (`cpcommon.transfer`) and nothing else:
different request contract, different authorization question, different failure vocabulary. Folding
them together would put one queue and one DLQ under two unrelated user features, and the DLQ drain,
which names the feature by the DLQ a request lands on, would report a dead-lettered send as a
share. The pattern is reused; the resources never are.

**The envelope is flat, and that is a contract with a shared security path.** `actor` is the raw ID
token at the **top level**, not `actor.idToken`. The spec was written nested and was amended during
the build, because SPEC-126's drain reads `body.get(token_field)` flatly and `_redacted` replaces
**top-level keys only** — a nested token would have (1) resolved no recipient on every
dead-lettered send, silently, since the drain swallows and returns, and (2) written the raw JWT to
CloudWatch, whose audience is far wider than the queue's. One envelope shape across five planes
beat teaching a shared security path a second one.

> **Still true, and no longer about a token (SPEC-201, 2026-08-30).** The reasoning holds and its
> conclusion was right twice over: the flat field is what the drain redacts, and the *reason* it
> had to be flat is exactly why the API's `identity` block is **nested** — a flat verified `actor`
> would have overwritten the very field four planes were verifying. The flat field itself is now
> a legacy carrier: no plane reads it, the drain blanks it as a stale-message token, ~~and it is
> removed from the wire when the API stops writing one. It stays in each plane's allowed-field set
> until then, deliberately~~ **— superseded by SPEC-201's second step:** the API no longer writes
> it, and it stays in each plane's allowed-field set anyway, deliberately — tightening it turns a
> pre-cutover message into `malformed_event` instead of the `unauthorized` refusal that path is
> meant to produce.

**Source authorization is about the space's status, never the member's join chip.** A `personal`
source must equal the verified username; a `shared` source needs `cpcommon.registry
.is_active_member`. The spec's original wording ("`pending`, `leaving`, absent") named a status
that does not exist and one that is a *member* concept — reading it that way would have reversed
**SPEC-073**, denying a send for files the same user can already browse, download and table-share.

**Containment is three rules, and the third was found by review.** (a) the root comparison is
trailing-slash-normalised, so `alice2/` is not inside `alice/`; (b) any `.`/`..` **path segment** is
refused, because `"alice/../bob/x".startswith("alice/")` is `True` — not exploitable against S3
today, but the same string becomes the item name in the destination key; (c) `athenaresults/` is
refused as the folder, as anything beneath it, **and as any folder that CONTAINS it**. (c) exists
because selecting the space root passes (a) and (b), and SPEC-165 expands a folder by listing its
prefix — in a shared space that is other members' query results leaving with the send. Folder keys
are normalised to a trailing slash for the same reason: `ListObjectsV2(Prefix="alice/athenaresult")`
matches `alice/athenaresults/…`. The results rule is **new for this plane**, not a reuse:
`protectedFolders.ts` keeps three deliberately divergent lists and in none of them is copying *out*
of that folder refused.

**Two caps, because there are two quantities, and the byte one is bounded by a CHAIN.**
`SEND_MAX_ITEMS` (200) bounds per-item work — two containment checks now, one `ListObjectsV2` per
folder in SPEC-165. `SEND_MAX_ITEM_BYTES` (96 KiB) bounds the serialised selection. **A count cap
cannot bound bytes**: S3 keys are arbitrary UTF-8 and JSON escaping expands `"` to two bytes and a
control character to six, so 200 items at a 1024-byte key measure 216 KB of ASCII or 1.2 MB of
`\x01`. And **a byte cap measured against the state alone is not enough either**: the browser's SQS
body carries the selection, the Pipe re-escapes that body into the record it hands to
`StartExecution`, and that input is capped at 256 KB too — so a quote-heavy selection arrives at
**twice** its measured size, and an over-limit request cannot start an execution at all. Both wrong
models shipped in review and each read as satisfied. The producer mirrors both caps (a request too
large for `StartExecution` never reaches the verb that would refuse it) and a test holds the
TypeScript numbers against the Python ones.

**Do NOT** reintroduce a single cap, and do not raise either without re-running
`test_config_fscommon`, which computes all three links.

**The failure path reads the request from the context object.** `validate-authorize`'s input is the
Pipe's JSON *array*, so its Catch has no object to merge a `ResultPath` into and the error
**replaces** the state — taking the only copy of the caller's token with it. The seed therefore
reads `$$.Execution.Input`, which survives whatever the Catch did; reading `$$` in a **Pass** state
is SPEC-157's recorded shape. Without it `NotifyFailure` takes its no-recipient branch on every
single failure — SPEC-152 satisfied on paper and silent in practice, on exactly the cold-start and
timeout failures it exists for. **Threading the request through the state instead was tried and
rejected**: the Pipe record carries the same selection again as an escaped string, so it roughly
doubles the payload for the whole run.

**FR-006 — the user-space bucket policy's allowlist is hand-maintained, and this is the shape that
rots.** An explicit resource-policy Deny beats an identity-policy Allow, so a plane whose execution
role is missing from `user-space-bucket-policy.json.tftpl` is denied by the bucket however correct
its own grants are. For a send the failure is asymmetric enough to read as a code bug: every
`space` recipient succeeds (the shared-space bucket has no bucket policy) and every `user` recipient
fails `AccessDenied`. The change is three parts — a variable in `modules/data`, the
`templatefile()` argument, root wiring — with the ARN a **constructed string**, because an
unknown-at-plan ARN inside a list silently drops the change.
`lambdas/test_user_space_bucket_allowlist.py` pins it three ways and was verified against a
deliberate omission.

---

## A received file lands in `shared_files/{sender}/`, and one function builds every key (SPEC-165)

**Decision.** Everything a sender sends lands at
`{targetRoot}shared_files/{sender}/{itemName}[/{relKey}]`, computed by a single
`fscommon.paths.destination_key`, with `shared_files` a named constant and a test sweep forbidding
any verb from composing its own.

**Why namespaced by sender.** This is what a recipient sees forever, and it is the decision with
the longest half-life in the arc — a layout is not something a later spec can quietly change, since
files are already sitting in it. Mirroring `shared_tables/{table}/` buys three things at once: two
senders sending `reports/` never collide, provenance is visible in the file browser with no
metadata lookup and no second request, and the recipient's own top level stays theirs rather than
accumulating a folder per sender's whim.

**Why the destination is keyed by ITEM NAME, and what that forces.** The alternative — preserving
the sender's path — leaks their folder structure into someone else's space and makes the
destination depend on where a file happened to live, so `alice/deep/nested/q1.csv` and
`alice/q1.csv` would arrive differently for no reason the recipient can see. Keying by name means
`a/reports/` and `b/reports/` would interleave into one folder, so that selection is a
**whole-request refusal naming the collision** — as is a selection where one item contains another
(copying the object twice and silently dropping one are both worse than a clear refusal). A
**repeated** item collapses instead: there is one right answer and no ambiguity about intent.

**A repeat is `(kind, key)`, and the key alone is not enough.** validate-authorize normalises a
`folder` key to a trailing slash and leaves a `file` key exactly as it arrived, so
`{"file","alice/reports/"}` and `{"folder","alice/reports"}` reach the expansion as one key with
two kinds. Collapsing on the key kept whichever came first: the file reading sent one zero-byte
placeholder and **none of the folder's contents**, reporting success, with the outcome depending on
the order of a JSON list. That is precisely the silent drop this rule exists to prevent, arriving
through the one part of it that was supposed to be safe.

**Why one builder.** The destination tests can only ever prove the ONE builder is right; a verb
concatenating its own would pass every one of them while writing somewhere else, and the symptom
would be files in the wrong inbox rather than an error. The sweep reads the AST for a
`shared_files` literal or an f-string composing the constant, exempting docstrings and the
declaration **by node identity** — an earlier version skipped the `Expr` and not its `Constant`
child, and flagged two module docstrings. Verified against four deliberate violations, including
one placed after a docstring.

## The file-send exclusion rule is anchored at the space root, not the listing prefix (SPEC-165)

**Decision.** `fscommon.expand` carries its own ignore predicate — folder placeholders, the prefix
marker, and `{root}athenaresults/` — and `cpcommon.s3_listing.list_data_objects` grew an optional
`ignore` parameter rather than being forked or reused as-is.

**Why not reuse `is_ignored`.** Every rule in it is anchored at the **listing prefix**. That is
right for the three analytics planes, which list a table's or a check's own folder, and wrong here:
the listing prefix is whichever item the user picked. Sending `alice/reports/` would have dropped a
user-made `alice/reports/athenaresults/` — which SPEC-164 explicitly records as an ordinary
sendable folder — and any `_drafts/`, with **no refusal and no message**. A silent drop from a send
that reports success is worse than either copying it or refusing it. The hidden-segment rule also
exists because *Athena* ignores such paths, which says nothing about a byte-for-byte file copy.

**Why a parameter rather than a second paginator.** The pagination genuinely is shared, and it is
the part a fixture proves least — the 1,000-key boundary is where a truncated listing returns a
plausible smaller number rather than an error. One paginator, and a plane whose exclusions are
anchored elsewhere says so at the call site. The default is byte-identical for the three existing
callers, held by a test in both directions.

**Two consequences, both deliberate.** A genuinely **empty file is sent** — `is_ignored` drops
every zero-byte object, and a folder placeholder is excluded by its trailing slash instead, the
shape `createFolder` actually writes — so an **empty subfolder does not survive a send**. And the
`athenaresults/` exclusion has **no live path** through the shipped front door, because
validate-authorize refuses a root selection outright; it is written anyway, for the reason SPEC-164
gave for writing that rule as containment rather than equality.

**`user_settings/` is excluded too, and it is NOT in the spec's list.** Narrowing the analytics set
to the three rules FR-001 AC4 names would have dropped it without anyone deciding to: it holds the
sender's notification inbox and shared-space connections cache, `protectedFolders.ts` hides it
everywhere in the browser, and — unlike the two rules this plane deliberately does not reuse —
anchoring it at the space root preserves the exclusion with **zero** false positives. Narrowing an
exclusion set is a decision; this one had not been made, only inherited by omission.

**The exclusions apply to a selected FILE as well as to a listing**, and applying them only to the
listing was a real defect. Nothing upstream filters a `file` item — validate-authorize normalises a
*folder* key to a trailing slash and leaves a file key untouched — so naming `{root}DO_NOT_DELETE.txt`
as a file copied the prefix marker into someone's inbox, and naming a folder *as a file* copied its
zero-byte placeholder as a file. AC4 says excluded from the copy set; it does not say "when they
turn up in a listing".

## The expansion caps are sized by memory and makespan, and the obvious models miss both (SPEC-165)

**Decision.** `SEND_MAX_OBJECTS` = 20,000 and `SEND_MAX_TOTAL_BYTES` = 1 TiB, each computed by a
test. The per-object cap and the recipient product cap are **deferred to SPEC-166**, not omitted.

**What sizes the object cap is the plan in memory, not the listing.** `inspect-source` holds the
whole plan as a list of dicts, serialises it and encodes that — three live copies at the write. At
S3's worst-case 1024-byte keys an entry is ~2.4 KB, so 20,000 objects is ~45 MB and peaks near
135 MB, against the 1024 MB in `locals.tf` **which the test reads back**: raising the cap without
raising the memory fails the build.

**And the timeout half is where a page-counting model goes wrong.** Twenty `ListObjectsV2` pages is
four seconds and reads like the whole answer. The term it drops is that a `file` item costs its own
**serial** `HeadObject`, so 200 files is 200 round trips and forty. The bound is per-ITEM plus
per-PAGE, the item half dominates, and an assertion pins that so a future reader re-derives rather
than trusts it.

**The byte cap is a makespan, not a bandwidth.** `cpcommon.transfer` hands one whole object to each
worker and part-copies serially inside one, so the denominator is
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` — 500 MB/s, not the ~4 GB/s the same
constants suggest under an aggregate reading. That is the mistake SPEC-161 found twice, in review
rounds, after it read as satisfied both times.

**Why two caps are deferred rather than guessed, and why BOTH need a tripwire.** The per-object
cap and the `recipients × bytes` product are measured against the copy verb's
`COPY_TIMEOUT_SECONDS` and the machine's top-level `TimeoutSeconds`, and this machine has neither.
The copy plan already carries every object's size, so SPEC-166 enforces both with no second listing
and still before any byte moves.

**The per-object gap is the one that undermines a passing test, and it first shipped in prose
only.** 500 MB/s is reachable only when the bytes are spread across the worker pool; ONE object is
ONE worker at 25 MB/s, so the makespan test certifies the **distributed** case and a single 1 TiB
object is **43,980 s** — four times over the ceiling it compares against. That is table-share's
recorded shape word for word ("while `SHARE_MAX_TOTAL_BYTES` was 20 GiB the bound was implicit …
raising the total to 1 TiB removed it without anything replacing it"), and this plane *starts* at
1 TiB. Both gaps carried a `hasattr` tripwire that **failed the day SPEC-166 added the cap**, and
the arithmetic was kept as an assertion so 166 inherited the size of the problem rather than
re-deriving it.

> **SUPERSEDED in part by SPEC-166.** The caps arrived — `SEND_MAX_OBJECT_BYTES`,
> `SEND_MAX_TRANSFER_ITEMS`, `SEND_MAX_TRANSFER_BYTES` — with the `TimeoutSeconds` they are
> measured against, and the `hasattr` tripwires were removed by the computed bounds that replaced
> them. Full entry: *The three transfer caps are each measured against a DIFFERENT budget
> (SPEC-166)*.

## An expected refusal is a return value, and a conflict is per item NAME (SPEC-166)

**Decision.** `check-target-absent` returns `{status, recipient, reason, detail}` for the two
refusals it expects — a recipient validate-authorize could not resolve, and a name conflict — and
its Map item's `Catch` is left for faults nobody predicted. The conflict is decided by **item
name**: one delimited listing of `{targetRoot}shared_files/{sender}/`, compared against the names
the selection would create. A taken name refuses **that recipient**; nothing is merged and nothing
is overwritten.

**Why not raise, as table-share's guard does.** A conflict has to name the colliding item, and a
`TerminalError` cannot carry one past the Map item's `Catch`: its `tokens` are deliberately kept
out of the exception message (they would corrupt `failure_reason`'s colon split) and its `detail`
is operator text that may quote raw service output, which SPEC-106 forbids rendering. Parsing a
filename back out of a Step Functions `Cause` would be fragile *and* a rule break. The collector
therefore reads two record shapes and decodes the raw `{Error, Cause}` only for the unpredicted one.

**Why a delimited listing rather than a probe per item.** Two round trips per item is 20,000 serial
calls for a full selection against a full recipient list — and a `MaxKeys=1` probe at
`Prefix={inbox}{item}` **cannot answer the question at all**: S3 orders keys lexicographically and
`/` (0x2F) is not the lowest byte a key may carry, so `notes.txt-old` sorts before
`notes.txt/part-0` and the one key returned reads as "clear" over an occupied destination. The
listing is bounded by what that sender previously sent to that recipient, not by the size of the
send.

**A name is a name whatever it holds.** A previous send of the file `notes.txt` conflicts with a
new send of the folder `notes.txt/`, because `destination_key` gives both the same base.

**Neither the guard nor the collector notifies.** Every per-recipient outcome is told to the sender
once, from the terminal summary, by SPEC-167's producer. Table-share notifies from its own guard
because it has no such producer; copying that here would send two messages about one conflict.

**Two fail-open holes, both found in review and neither visible to the suites as written.** The
guard cleared every recipient when the selection arrived empty (no names ⇒ no collisions ⇒ `ok`,
over an inbox that already held the send) — three lines from a missing *actor* that already failed
closed. And the collector reported universal success when the `transfer` block was absent, without
making a single S3 call; it is closed by an invariant already on the event, that the manifest
builder cannot report zero items while a recipient cleared the guard.

**Not closed: the guard is TOCTOU.** Two sends of the same item name from the same sender to the
same recipient, submitted close together, can both clear it. Inherent to check-then-copy with no
lock, and table-share has the same shape. **— Superseded in part 2026-09-15: "close together"
means before the first run's copy of that name lands, which on a large send is up to the
three-hour ceiling, because the group id orders only the starts; and the second run then
overwrites what the first delivered, a file the recipient edited in between included. The repair
is decided: [the group id entry](control-planes.md#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide).**

## The transfer caps are three, and each is measured against a different budget (SPEC-166)

**Decision.** `SEND_MAX_OBJECT_BYTES` **10 GiB**, `SEND_MAX_TRANSFER_ITEMS` **50,000**,
`SEND_MAX_TRANSFER_BYTES` **3 TiB**, all enforced in `inspect-source` before the plan is written,
and the two product caps measured on the **requested** recipient count.

**Each is a different budget, and using one model for all three is how table-share's own bound came
to be wrong twice.** The per-object cap is bounded by `COPY_TIMEOUT_SECONDS`, the batch verb's own
Lambda timeout — a batch is exactly one round of the worker pool and one object is one worker, so a
batch costs its slowest object. The item cap is bounded by the **memory** the two verbs either side
of the Map hold the manifest in, read back from `locals.tf`. The byte cap is bounded by the whole
run's **makespan** against the machine's `TimeoutSeconds`, at
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s and **not** the ~4 GB/s the
same constants suggest multiplied together.

**The per-object cap is the one whose absence made every other model a half-truth.** SPEC-165
recorded it as owed and kept the arithmetic: without it the worst legal case was a single 1 TiB
object on one worker — 43,980 s, four times the ceiling — while `test_a_full_size_selection_copies
_inside_the_engines_ceiling` read as satisfied. It is table-share's value exactly, deliberately:
same engine, same batch size, same timeout.

**`SEND_MAX_TRANSFER_ITEMS` deliberately diverges from table-share's 20,000.** That plane's
transfer cap equals its own object cap, so at full size it permits one recipient — fine when a
share is one table. A 2,000-file folder to a 30-person team is the ordinary case here. The computed
memory ceiling is ~150,000 items; 50,000 takes a third of it.

**Measured before the guard, on purpose.** Counting only the recipients who clear their conflict
check would let the expensive half of the work happen first, and would make a refusal depend on
what someone else's inbox happens to hold.

## One producer says every per-recipient outcome, and the link carries the recipient's own root (SPEC-167)

**Decision.** A single verb at the end of the machine turns SPEC-166's terminal summary into
messages: one to the sender per recipient outcome, one to each recipient who actually received
something — a ``user`` directly, a ``space`` through its registered OWNER, never its membership.
Its link is `/files?prefix={recipientRoot}shared_files/{sender}/`, with `?space=` as well for a
space.

**Why one producer rather than a decorator per verb.** Table share notifies from its guard, its
collector and its create verb because each is the only place its own outcome is known. Here every
per-recipient outcome reaches one flat list before anything is said, so one place can say each
thing once — and a decorator on the guard would make a conflict two messages. It is also what
lets the guard return its expected refusals as records: the colliding item name has to reach the
producer, and a `TerminalError` cannot carry one there. The whole-REQUEST verbs still notify
from their decorators, and must: a request that dies before this state never reaches it.

**A failed recipient is told nothing.** They have no part in the send, nothing to do about it, and
being told would leak that the sender tried.

**Why the link carries the recipient's root.** `FilesPage` keeps a `?prefix=` only when it starts
with the resolved space's `rootPrefix` and ends in `/`, so a root-relative prefix is silently
discarded and the recipient lands at their space root — a link that looks like it worked. A test in
`test_file_send_notify.py` drives the handler, reads the route's path, parameters and gate,
`rootPrefix`'s own definition, and the literals `NotificationRow` and `isSafeInAppPath` test a link
with, out of the TypeScript rather than restating them, and checks that each recipient's prefix is
the inbox the copy writes to, since a link to the space root survives the route too. The check's
first version, in SPEC-167's build, pinned only the gate and compared against a hardcoded value,
which would have stayed green through the rename it existed to catch. The two tests SPEC-167
shipped, one on the route rule and one on `isSafeInAppPath`, were deleted with their file when the
suites were cut to their entry points (`a41bda69d`), which is why this one drives the handler. The
same cut took the handler test's own link assertions, and coverage could not notice, because the
handler still ran the function.

**The link is feature-gated, and that was a review finding.** With `files` off it was a live anchor
into the unavailable page; with `sharedWorkspaces` off the space link resolved the personal space
and dropped the prefix — the exact failure the full-key rule exists to prevent, reachable from flag
state alone. `NotificationRow` now gates a MAP of flag→match rather than one hard-coded prefix, with registry rows for both — and the space arm matches on `?space=`, because that variant differs in its query rather than its path.

**The double-submit guard is the in-flight ref, NOT the queue's dedup id.** FR-003 AC5 said
otherwise and was amended in build: the `requestId` is minted per SUBMIT, because it is also what
makes a retry possible — reused across a failed attempt, the second send is swallowed by the queue
and the user gets an error, presses the button again, and nothing at all happens. The trade is a
first send whose response was lost being retried as a new request, which the conflict guard then
refuses per recipient and tells the sender about.

**A refusal must be reachable to be a refusal.** The dialog's Send control stays ENABLED with no
recipients: `submitDisabled` made the inline refusal dead code where an acceptance criterion was
supposed to be, and a test asserting only "the button is disabled" passed over it. A disabled
button also explains nothing to the user who typed a name and forgot to commit it.

---

## A saved query is a FILE, and the folder holding it is ordinary except in one respect (SPEC-173)

**Decision (2026-08-11).** Saved queries move out of `{username}/user_settings/saved-queries.json`
and become `.sql` objects in `{root}saved_queries/`, a folder at a space root. The folder is
**visible, browsable, uploadable into, a valid move/copy destination and free to hold subfolders**;
individual files inside it may be deleted by anyone with access to the space. Exactly one thing is
protected: the folder **itself** cannot be deleted or renamed. It appears in
`UNDELETABLE_ROOT_FOLDERS` and in **neither** of the other two lists, and a test asserts that
absence, because `protectedFolders.ts`'s three lists answer three questions (see / paste / destroy)
and this folder is the second case that proves they are not a union. Rename is a move — S3 has
neither — so ~~`moveFolder`'s existing refusal covers both with no new guard.~~ **— superseded by
SPEC-198:** one move refusal still covers both, though `moveFolder` is deleted. A folder move or
rename runs on the file-operations plane, whose `source_refusal` (`focommon/protected.py`) refuses
the folder as a move source; the browser states the refusal first, through
`undeletableRootFolderRefusal(folderPrefix, rootPrefix, 'move')` and `undeletableSelectionRefusal`
for a selection made only of protected folders (*The folder-recursive functions are deleted, not
ported*, below).

**What keeps the load list coherent is a FILTER, not a write lock.** Because anyone may drop a CSV
or a folder tree in, the store offers **top-level `.sql` files and nothing else**; that filter is a
requirement with tests rather than a precaution, and `Delimiter: '/'` is load-bearing beside it
(`saved_queries/archive/old.sql` is a file in a folder, not a saved query). The depth check is
asserted in the service too, so one-level-ness is a property of the STORE and not of one request's
parameters. A folder the user cannot treat as a folder is a folder they will fight, and a saved
query nobody can throw away is one that accumulates forever — the narrowness is the design.

**The key is the identity and the filename is the name.** There is no id and no record, because a
`.sql` file cannot carry one without a sidecar this feature deliberately does not have. The listing
returns S3's own (lexicographic) order, unmodified: sorting by last-modified across a paginated
listing is the lie SPEC-123 records about the data-quality runs index — the newest query may sit on
page nine, and a client-side re-sort of the loaded pages makes rows the user has already seen jump
between pages as later pages arrive.

**The queries in the old store are abandoned, not migrated** (user decision). The portal is
pre-production with no real users, and a migration is code with one execution and no way to test
its second run. The document is left in place (`user_settings/` denies delete) and the store's code
is **deleted**, so there is one saved-queries system in the tree and no second definition of what a
saved query is.

**Three user-visible losses, each accepted on its own reasoning.** The drawer loses its **SQL
preview**: a `.sql` object carries no body until it is read, so a preview means a `GetObject` per
row on every open — twenty-five round trips to show twenty-five one-line snippets. **Every Save now
asks for a name**, a linked tab's included, pre-filled and selected, where SPEC-043 wrote back
silently: a user about to overwrite a file should be told which file, in which space. And the
collision check moves from a case-insensitive scan of the loaded array to a **HEAD on the exact
key** inside `writeSavedQuery` — the scan stopped being sound once the list is paginated and the
target space may not be the one on screen — so `Report` and `report` are now two saved queries,
because S3 keys are case-sensitive.

**The dirty marker is a SESSION SNAPSHOT, and its gap is stated rather than discovered.** SPEC-043
compared a tab's buffer with the `sql` field on a store row; there is no such field. The workspace
keeps a `key → sql` map of what this session last saw — the body fetched when a query was opened,
or the buffer just written by a save — and marks a tab dirty against that. A tab restored from
`sessionStorage` after a reload therefore shows no marker until it is opened or saved again. The
alternative was a `GetObject` per linked tab on every mount, which is the same trade the preview
line lost.

**Do NOT build:** a sidecar metadata file beside each `.sql`; a recursive listing (a `.sql` file
the user tucks into a subfolder is a normal file, reachable from the file browser and not from the
editor); a write lock or an allowed-extensions guard on the folder's contents; a migration from the
JSON store; or an autosave of any kind — FR-010 is a tripwire test with a zero-`PutObject` count,
because the failure it guards is silent and lands in someone else's shared space.

---

## Every `DO_NOT_DELETE.txt` is hidden by BASENAME, and the whole arc needs no IaC change (SPEC-173)

**Decision (2026-08-11).** `useFileBrowser` hid one exact key, supplied by its caller. It now hides
any object whose last path segment is `DO_NOT_DELETE.txt`, at any depth, in either bucket — and the
`markerKey` parameter is **deleted**, along with the prop threaded through `DestinationPicker`,
`MoveDialog`, `CopyDialog`, `FileBrowserDialogs`, `FilesPage` and `StartQualityCheckDialog`. A
source sweep asserts no caller passes one; `DestinationPicker`'s props stopped being a union as a
result.

**The reasoning generalises further than this folder.** Both bucket policies deny
`s3:DeleteObject` on a wildcard resource ending in the marker's own basename, and `*` in an S3
resource ARN matches `/` — so *any* object with that name, anywhere in either bucket, is already
undeletable. Showing one offers an action this application's own IAM refuses, which is the
SPEC-150 FR-007 mistake waiting to happen. That same reading is what lets the whole
saved-queries-in-spaces arc ship **no `.tf` or `.tftpl` change**: the marker at
`{root}saved_queries/DO_NOT_DELETE.txt` is covered at that depth and any other, and every read,
write, list and delete the store needs is already granted by `UserPrefixObjects` /
`SharedSpaceObjects` and their listing statements.

**It is the arc's load-bearing premise, so it is pinned and it owes a live check.** A test reads
the two `.tftpl` files and asserts each `Deny` still ends in `/*/DO_NOT_DELETE.txt`, so a later IAM
edit that narrows the wildcard fails in a local `pytest lambdas/` run rather than in production
— CI no longer runs pytest (`docs/process/ci-and-deploy-traps.md`), so the guard is only as good as the pre-push run. But a passing test over a
template is not a refusal: **a real delete of a real marker, refused, is owed** (SPEC-173 FR-009),
in both a personal and a shared space. Until it is run the reading is corroborated, not discharged
— the same class of evidence that had SPEC-144 FR-001 reversed mid-build.

The saved-queries marker gets its **own body text**: `PREFIX_MARKER_BODY` says the file keeps "your
personal storage space" active, which is wrong in a shared space and wrong about what this folder
is. It reuses `PREFIX_MARKER_FILENAME` exactly, and a test says so, because the IAM protection keys
on that basename.

---

## `saved_queries/` is gated on `query`, and the gate is not the refusal (SPEC-173)

**Decision (2026-08-11).** The folder is a Query feature wearing a file-browser row, so it is a
`GATED_SURFACES.query` **registry** row — the same shape as "Create table", the row SPEC-163 calls
the one everyone forgets — and not a per-component opt-in. With the flag off it leaves the file
browser's listing **and** the destination picker together, because a destination the user cannot
see is not a destination; that is the one place the gate touches an otherwise ordinary folder
operation, and it is presentation: it removes a way of *asking* and revokes no grant.

`DestinationPicker` reads the flag **itself** rather than taking it from its four callers, so every
picker in the app inherits the rule from one place. The cost is real and accepted: the picker now
requires an auth context, which one bespoke a11y tree had to be given.

**The delete/rename refusal is unconditional, and structurally so** — ~~`deleteFolder`/`moveFolder`
take **no flag**, so there is no state in which the gate can reach them. That is the argument, and
it is stronger than the test FR-008 AC3 asks for: a service-level test cannot render "with the flag
off" because the service never reads one. The refusal is tested directly and the structural claim
is recorded in the test's own comment.~~ **— superseded by SPEC-198:** `deleteFolder` and
`moveFolder` are deleted, and the argument holds of what refuses in their place. Neither
`undeletableRootFolderRefusal` nor `undeletableSelectionRefusal` in `protectedFolders.ts` takes a
flag, and neither does the plane's `source_refusal`, so there is still no state in which the gate
can reach the refusal. `fileBrowserPure.test.ts` tests the browser's refusal for `saved_queries/`
directly; the test comment that recorded the structural claim went with SPEC-198's rewrite of the
service tests. "You cannot see it" and "you cannot destroy it" are different guarantees, and only
one of them survives a stale cached flag document.

## A save chooses its space, and one KEY rule decides what that replaces (SPEC-175)

**Decision (2026-08-12).** The Save dialog asks for a **destination** as well as a name, and the
destination it opens on is **the tab's own space when the tab is linked, else the space SPEC-174
already remembers** — one memory of "the space I am working in", written on every successful save
and shared with the load surface. Two memories were the obvious alternative and are rejected: the
user has no model of a saving-space distinct from a loading-space, so two values can only ever
disagree in a way nothing on screen explains. A linked tab whose space is no longer offered falls
through the same path a stale stored id does, to personal.

**Everything that turns on "is this the same file?" goes through one predicate**,
`isLinkedSavedQuery(link, space, name)`, and it judges the **key** — not the space, and not the
name. Three behaviours read it: the dialog's promise that a submit replaces the file the tab was
opened from, the host's `overwrite` on the write, and therefore whether FR-003's Replace confirm is
raised at all. Split across two call sites each computing its own version, the dialog could promise
an in-place replace while the host wrote a new object. A different name in the tab's own space is a
different file; so is the same name in another space.

**A linked tab's unchanged re-save is confirmed ONCE.** Every save prompts — SPEC-043's silent
write-back is gone — and the prompt has already named the file and the space, so a Replace confirm
on top of it asks about the thing just answered. `SaveQueryRequest` therefore carries `{space,
name}` and **not** `overwrite`: the dialog cannot ask for a silent clobber, because the host is the
only thing that decides one.

**Choosing another space is a copy, and the absence of a delete is the decision.** One `PutObject`
into the new space, the original left alone, the tab re-linked to the new file. Moving is not
offered: a saved query a colleague may be running now must not disappear because someone copied it
elsewhere, and a move across buckets is a copy-then-delete whose second half can fail alone.

**A write failure keeps the dialog open with the destination intact.** The realistic failure is a
shared space whose membership was revoked mid-session, returning `AccessDenied` — and the user's
next move is to pick another destination, which a toast over a closed dialog takes away from them.
The message is `toUserMessage`'s, inline on the field (SPEC-106), and the space control stays
interactive.

**Validation runs on submit; `submitDisabled` does not stand in for a refusal.** SPEC-167 records
this exact failure in the send dialog — a disabled control made an inline refusal dead code, and the
test asserting "the button is disabled" passed straight over the acceptance criterion. The same
reasoning governs FR-007: with no writable space the Save control still **opens** the dialog, and
the dialog **explains itself**, rather than the toolbar rendering a mute disabled button.

**The registry gains a row, and it is not a duplicate.** FR-008 predicted none — every surface here
lives inside `/query`, which the registry gates as a route. But the dialog's destination control is
a **second instance** of the `sharedWorkspaces` choice, and the existing *Shared spaces in the
saved-queries selector* row renders the **drawer**: nothing would notice if this control stopped
being gated, and this is the worse of the two failures, because it offers a colleague's space as a
**write** target. That is SPEC-167's own precedent for the send dialog's recipient kind. The row was
**verified against a deliberate violation** — passing the ungated list reddens exactly that row and
nothing else, measured — rather than trusted.

**A typed `.sql` extension is LOWERCASED, correcting SPEC-173's `basenameFor`.** FR-002 AC4 wanted
`report`, `report.sql` and `report.SQL` to be **one** key; 173 only skipped the *appending*, so
`report.SQL` was a second object — and since `savedQueryName` strips the extension
case-insensitively, the two rendered **identically** in the load list, on the tab and in the Replace
confirm. The reachable failure is not the ambiguity but the overwrite behind it: a tab linked to
`…/report.SQL` pre-fills `report`, which resolves to `…/report.sql`, so the confirm truthfully
offers to replace `report` and **clobbers a file the user never opened** while the one they did is
orphaned. The **stem is deliberately untouched** — `REPORT` and `report` stay two names, which is the
case-sensitivity this same spec keeps — and a `.SQL` object already in a bucket still lists and
opens; only the save path normalises, so re-saving a tab linked to one is a visible Save-as rather
than a silent clobber.

**Two of this spec's tests could not fail, and a third guarded the wrong mechanism.** All three are
recorded because the pattern recurs. (1) The default-space fork (`linkedSpace ?? defaultSpace`) was
only ever exercised where the two **agree** — `onSaved` calls `selectSpace` and keeps them in
lockstep — so either operand could be deleted with the suite green; the bug it hid writes a **copy
into a shared space** and re-links the tab, with every visible cue consistent. (2) **jsdom
implements no implicit form submission**, so "Enter on the space control does not submit" passed
whatever `FormDialog` did; the guard is asserted through **`defaultPrevented`** instead, and
`FormDialog` now intercepts `<select>` as it always intercepted `<input>` — a browser submits a form
from a closed select, and `DestinationPicker` had the same exposure. (3) FR-003 AC4's "does not list
the folder" counter cannot catch the SPEC-043 regression it names, because an **in-memory scan
issues no listing**; the force comes from a test where the loaded list and S3 **disagree in both
directions**.

---

## A file operation on more than one file belongs on a plane, and the boundary is the SELECTION (SPEC-187)

An operation stays in the browser **if and only if the selection is exactly one item and that item is
a file**. It is a property of the selection, never of the operation: the same selection routes the
same way for copy, move and delete.

**The first draft of this rule was measured against the wrong quantity.** It said an operation goes
async only when it must LIST to know what it touches — coherent, and wrong: a file-only copy or move
of K files is a sequential loop of `HeadObject` + `CopyObject` + `DeleteObject`, up to 3K round trips
from the user's laptop, which is precisely the cost the plane exists to remove.

A single folder is enqueued, **including a folder rename** — forced rather than chosen, since a
rename is one `CopyObject` per contained object and cannot be bounded without listing. It is the case
a reader assumes is synchronous, so the rule's test names it.

**The empty selection is a precondition, not an answer.** Without it, "not exactly one item" routes a
zero-item selection to the plane, which refuses an empty source as a request-shape error minutes
later, by notification.

The rule has **one home**, and the sweep that enforces it counts IMPORTERS rather than parsing for
the rule: a boolean over `kind` and `length` has no recognisable syntactic signature, so an AST sweep
would fire on every legitimate branch in the file browser. That is the opposite call from SPEC-165's
key-builder sweep, where the signature *is* recognisable.

## The file-ops lock's loser WAITS where the table-builder's is refused (SPEC-187)

Both locks exist because delivery ordering is not execution ordering. They differ on what happens to
the loser, and the difference is the scope of the lock rather than a preference.

SPEC-157's lock is per **table**, and a contended refresh is a genuine conflict: two runs would
compute an identical definition from the same files, so refusing is the honest answer. This lock is
per **space** and covers all three operations — so deleting a folder in `alice/a/` and then copying
one in `alice/b/` is disjoint and entirely safe, and refusing it would produce a reliable
out-of-band refusal after the UI had already accepted the request.

So the loser **waits and retries**, with a bounded give-up that then refuses with a notification.
Three consequences that only hold together:

- **The waiter steals a stale lock itself**, on every re-acquire rather than only the first. That is
  what makes the give-up bound independent of the steal threshold.
- **The give-up bound is strictly LESS than the machine's `TimeoutSeconds`.** The naive chain is
  unsatisfiable and must not be re-derived: requiring give-up ≥ the steal threshold, with the
  threshold > the ceiling, forces give-up > the ceiling — and the waiter is a state *inside* the
  machine, so the ceiling would kill it before its refusal could fire, surfacing as a bare
  `TIMED_OUT` rather than the message the design promises.
- **Waiters are unordered, and that is accepted.** The Pipe starts executions `FIRE_AND_FORGET`, so N
  submissions against one space become N concurrent waiters polling one key with no queue discipline.
  Ordering would need a real queue; the browser's own busy gate already makes this rare from one
  session.

**A cross-space copy or move takes TWO locks, in digest-sorted order, or neither.** Keying only on
the source leaves the destination unserialized — A moves `alice/reports/` into `marketing/` while B
deletes `marketing/reports/`, different source digests, both run. Sorted order is what makes two
locks safe: unordered acquisition deadlocks when two requests cross in opposite directions. The verb
releases the first if it cannot claim the second, so a waiter never holds a lock across the `Wait`
and the give-up path has nothing left to free.

**One case can still strand a lock and is accepted rather than solved:** a fault inside the acquire
verb between the two claims returns nothing, so no tag reaches the state and the first lock is held
with nobody able to name it. The staleness steal is the recovery, and it is the same universal
recovery the top-level timeout needs — splitting the claims into two states would double the loop
and reintroduce the partial hold the design avoids.

## An item copied into itself is refused PER ITEM, where a containment breach fails the request (SPEC-187)

The plane's front door has two kinds of refusal and the split is not stylistic.

**Whole-request, raised:** a key outside the actor's own root, a dot segment, a `targetName` that is
not one usable segment, and two selected items whose derived destinations collide. These are
statements about the REQUEST — there is no sensible partial execution of one that names a key outside
the actor's space, and where two items collide neither of them is the wrong one, so there is no item
to fail and no way to choose.

**Per item, returned as an outcome record:** a protected folder, a same-key no-op, and an item whose
destination is inside its own subtree. The browser has always carried on with the rest — a select-all
delete at a space root deletes what it may and reports the folders it may not — and a whole-request
refusal would turn that into deleting nothing.

The into-itself case is the one that could have gone either way. It is per item because it is a
statement about ONE item's own pairing rather than about the request's legitimacy, which makes it a
**user-visible divergence from today's browser**, where it refuses the whole gesture.

**A collision is between two DIFFERENT items, and an exact repeat is not one.** The identity is
`(kind, key)`, never the derived key alone: the same item named twice lands on itself, which is
idempotent, while two different items landing on one key lose a file. Collapsing on the derived key
alone refuses a request that does exactly what it says — and it is the same rule SPEC-165 recorded
for file-send, arrived at from the other direction.

**The protected-location rules run FIRST, before either pairing rule.** An item the user may not
touch should be told so rather than told that nothing happened: `move alice/archive/ → alice/`
derives its own key, so a pairing-first order answers "no-op" to a request the plane actually
refuses, and two protected folders answer the same request differently depending on which list they
are on.

**Where each item LANDS is judged too, not only the prefix it is put into** (2026-09-16). The prefix
is the folder a request names and every item lands one name below it, so a prefix-only rule accepted
moving `sales/stage/_data-quality-reports/` into `sales/`, or renaming a folder `shared_tables` at the
root — in a shared space, one member replacing another's data-quality reports, which that plane reads
back between its verbs. validate-authorize runs the destination rules over each item's derived key,
per item, as `destination_name_reserved`. It sits AFTER the same-key no-op, which writes nothing, and
before into-itself, in every bucket pairing. `_data-quality-reports/` and everything in it is refused
as a delete or move source, root-anchored like the plane's only write. **No execution-role Deny backs
either, by choice**: the role has no principal tag to anchor a Resource at a root, so
`*/_data-quality-reports/*` reaches a user's own nested folder too, and every file-ops rule would have
to refuse it at any depth or the Deny fails a run part way through. Results-conversion's role takes
that trade for one save location; here it would refuse copying, moving and deleting a folder the
browser shows as the user's own.

**The space root is refused as an item, and it is the third way to select a protected folder.** Every
protected rule matches the named folder or something below it; none looks UP. So one item of
`alice/` passes all of them while naming a subtree containing `athenaresults/`, `user_settings/`,
`archive/` and every marker — a request this plane's own IAM refuses part-way through, which is the
mismatch those rules exist to prevent. The browser cannot express it, so refusing costs nothing.

## The source deletion removes only CONFIRMED-COPIED keys, never a prefix listing (SPEC-187, diverging from SPEC-169)

Recorded here because SPEC-188 and SPEC-189 must honour it and neither is written yet.

SPEC-169's archive rollback lists the source prefix precisely so it catches objects a batch copied
before it died. **Here the same technique loses data.** An object written into the source folder
between expansion and commit — by an upload, a single-file operation, or another plane, none of which
take this plane's lock — was never copied, and a prefix-listing delete would remove it silently and
unrecoverably, with versioning off.

The accepted cost is an **orphan**: it survives, stranded in a folder the user believes moved, which
is visible and recoverable where the alternative is neither.

**It forbids LISTING THE SOURCE PREFIX at deletion time. It does not forbid re-reading the PLAN**,
which is how the keys actually arrive — the transfer engine reports counts and never keys, because a
failed-key list is the unbounded term that breaches the state limit on the Map.

**And the gate is per ITEM, not one boolean over the run.** SPEC-169's is all-or-nothing because
before per-item outcomes the planned set and the confirmed-copied set were identical. They are not
here: a skipped item is planned and not copied, so deleting plan keys would remove the user's source
file while the destination still holds the colliding object that displaced it — a direct,
unrecoverable substitution.

## The collision unit is the derived destination KEY, and that is what preserves merging (SPEC-188)

The destination guard asks, per selected item, whether anything is already where that item's objects
would land. **What it compares is each derived destination KEY, never the destination subtree**, and
the difference is a capability rather than a nuance.

~~That is what the browser does today: `moveFolder` and `copyFolder` intersect `sourceKeys.map(destKeyFor)`
against the listed destination.~~ **— superseded by SPEC-198:** that was the browser's rule until
`moveFolder` and `copyFolder` were deleted. A folder operation now meets this guard only on the
plane, where `_collisions` in `file_ops_check_destinations.py` heads each item's derived destination
keys — the same unit, so merging survived the move. So copying `reports/` into `out/` while `out/reports/notes.txt`
already exists — where no source key maps onto that key — is legal today and stays legal. "The
destination subtree holds anything" is a stricter test that reads as tidier and would silently
remove **merging into an existing folder**, which is how people actually use a file browser.

**It heads every key rather than listing the destination, and a listing structurally cannot serve
the check.** `CommonPrefixes` carries no `LastModified`, `Size` or keys, so a delimited listing
cannot answer the overwrite predicate below the first level; and `ListObjectsV2` never returns a
per-key 403 — an `AccessDenied` fails the whole listing. HEADs are also bounded by **our own**
`FILE_OPS_MAX_OBJECTS` rather than by the size of someone else's destination folder.

**A 403 counts as OCCUPIED, in both modes**, inherited from the archive guard for the same reason: a
key this role cannot head is one it must not overwrite, and under `overwrite` it yields no
`LastModified`, so "an existing object" must never be read as "the ones we could head". A head that
faults for any other reason refuses its item; it never falls through to clear.

**`refuse` short-circuits and `overwrite` cannot**, and the asymmetry is stated because a shared
early exit would silently make `overwrite` sample-dependent — a newer object *anywhere* in an item's
key set refuses it, so the whole set has to be asked about. The corollary is that the ordinary case
costs a full sweep either way: a clean item is always `objectCount` heads, which is what the verb's
timeout is sized for.

**The overwrite predicate reads `submittedAt` from the PLAN with no fallback to the state**, and an
unusable instant refuses the request rather than degrading the mode. A fallback would reintroduce
exactly the substitution `plan_superseded` exists to catch, and a silent degrade would apply refuse
semantics — *with* the short-circuit that mode must never take — to a request the user confirmed as
an overwrite.

**The conflict sample is bounded by the STATE, not by taste.** Every conflicted item carries its
sample from the guard to the notification, and Step Functions caps a state at 256 KB. Measured at the
selection byte cap with every item conflicted, one full-length path per item is all that fits — so a
sampled path is shortened from the middle to `FILE_OPS_SAMPLE_PATH_CHARS`, which keeps the basename,
and three of them fit with room over. An ordinary path is untouched.

## A conflict is one item's outcome, and the list is created once and carried forward (SPEC-188)

Three verbs decide per-item outcomes — validate-authorize (the protected locations, the no-ops and
the into-itself refusals), inspect-source (`source_missing`, `source_empty`, and every expanded item
provisionally `cleared`) and check-destinations (`cleared` → `conflict`). **None of them creates the
list. Each takes it as input and returns all of it.**

The rule exists because of how a verb's result reaches the state: it REPLACES the path it is merged
into rather than appending to it. Wired the obvious way, the destination guard would silently drop
the two producers before it — and those are exactly the outcomes the per-item model exists to carry.
`focommon.outcomes.carry_forward` is the one function that merges, and it replaces an entry **in
place**, because a person reads this list and a revised verdict must not reorder it.

**An item an earlier verb decided is never expanded**, which is a rule rather than an optimisation. A
same-key no-op's destination subtree IS its source subtree, so expanding it would have the guard
report every one of its own objects as a collision and flip a reported success into a refusal. It
also keeps the same-key comparison — a security-adjacent rule — in exactly one verb.

**Whole-request refusals still raise, and the split is the one SPEC-187 set.** Two items where one
contains the other, and every cap, fail the request; a missing file and an item that resolves to
nothing fail alone. **The overlap check is asked of the WHOLE selection, before the decided items are
dropped**, because an item can be decided and still be the container: a move of `saved_queries/` and
`saved_queries/2026/` has the parent refused as protected and the child untouched by any rule, so a
check over the survivors would move the subtree out of the folder whose own refusal exists to keep it
there.

**Only a proven absence is `source_missing`.** A 403 or a KMS refusal is a statement about what could
be READ; reporting it as a per-item miss drops the file from the plan silently, moves everything
else, and names the user a cause that is false. Those fail the whole request.

**The plan is the object that knows what the run will touch, and it is passed by pointer.** At the
object cap the list is tens of megabytes against a 256 KB payload limit, so it is written to
`{admin_bucket}/file-ops/{requestId}/plan.json` and only the key and the counts ride. It carries
`requestId`, `submittedAt`, `onConflict` and the **execution ARN**; the last is what makes the
request-id reuse guard retry-safe. Every task on this machine carries a three-attempt `Retry`, so a
transient fault after the write is ordinary: a guard refusing any occupied prefix — the archive's
shape — would refuse the request it had itself just planned and tell the user their id had been used
before. Comparing the execution refuses the case the check exists for and admits the one the machine
creates.

**The ETag rides on every plan object because the listing already carried it.** `ListObjectsV2`
returns it in `Contents` at zero marginal cost, and this is the only verb that lists the source — so
it is the only cheap producer of the field a later conditional delete turns on. Getting it any other
way is a `HeadObject` per object, which is a round trip per object where a listing is one per
thousand. `cpcommon.s3_listing` gained `list_data_records` for it, and `list_data_objects` is now a
projection of that function, so there is still exactly one paginator in the fleet.

## The commit gate is per ITEM, so the graph proves less than SPEC-169's did (SPEC-189)

SPEC-169's gate is one boolean over the whole run and its guarantee is **graph-level**: the rollback
arm cannot *reach* `DeleteSource`. A per-item plane produces runs that are simultaneously committing
and non-committing, and **Step Functions has no per-item `Choice` over a list** — so that guarantee
is not available here. Rather than inherit a sentence that no longer holds, this plane asserts the
weaker property honestly and buys the rest at two other layers:

- **the walk asserts exactly one thing** — an empty `deletable` set cannot reach `DeleteSource` — and
  says in its own docstring that it does **not** assert the per-item property. A walk claiming more
  than it proves is worse than one claiming less;
- **the per-item half is a collector unit test with a named mutation** (an item with one failed
  object must not appear in `deletable`), plus **`delete-source`'s subset assertion at the boto
  boundary** — checked against the keys actually handed to `DeleteObjects`, never over the filter's
  own output, which would re-check the filter with the filter.

**Both gates enumerate their positive cases and default to not deleting.** `NeedsSourceDeletion`
names `move` and `delete` explicitly; a state whose `operation` was lost or mistyped reaches
`FinaliseOutcomes`. The first draft had the deleting arm as the `Default` — fail-open, and the
opposite of every neighbouring gate on this fleet.

**The skip branch is recognised positively.** A `delete` reaches the collector with the Map skipped
and every still-`cleared` item deletable. Implemented as the natural negative — *no `mapRun`,
therefore the skip branch* — a `move` arriving without an export would mark every cleared item
deletable and the next state would delete a source nothing had copied.

## The source deletion: what it removes, and what it is conditional on (SPEC-189)

**It deletes the plan's keys, never a prefix listing** (SPEC-187 Premise 1). This plane's lock
serialises its own executions and nothing else — not uploads, not create-folder, not the six other
control planes — so an object written into a source folder between the expansion and the commit was
never copied, and a prefix delete would remove it silently and unrecoverably with versioning off.
The accepted cost is an **orphan**, which is visible and recoverable where the alternative is
neither. A plan **re-read** is not a prefix listing, and per-item gating makes "the plan keys of a
fully-succeeded item" and "the keys confirmed copied" the same set.

**A conditional delete is NOT replay-safe the way an unconditional one is.** `arcommon.delete` rests
its whole `Retry` story on S3 reporting an already-absent key as deleted — true only *without* a
condition. With one, a key the previous attempt removed comes back on the **error** side, so a verb
that deleted five batches of twenty, hit a throttle and retried would report every one of those five
as a failure and the user would be told a completed move half-failed. "Gone" is therefore success and
only a genuine mismatch is `source_changed`.

**409 is handled distinctly from 412, diverging from `cpcommon.cas.is_precondition` on purpose.**
That predicate collapses them and is right to: a compare-and-set retries on either. A conditional
delete is not a CAS — a **412** means the object changed, terminal for that item because its
destination copy now holds stale bytes; a **409** means a concurrent delete or put won the race,
which is retryable. One module answering "did my write lose?" and another answering "why did my
delete not happen?" are different questions, and a shared helper would have to give one answer to
both.

**The HEAD-compare path is ACTIVE and the conditional one ships behind a flag.** Reading
`ObjectIdentifier`'s members off the live service model proves botocore will *serialize* the ETag; it
does not prove S3 *enforces* it, and a serialized-but-ignored condition deletes a changed source
silently. `CONDITIONAL_DELETE_ENABLED` flips only once a live probe shows a wrong-ETag delete is
genuinely refused on these buckets.

**A `delete` operation's deletions are unconditional, and conditionality is the CALLER's explicit
flag.** A move's condition protects bytes that were just copied; a delete has no copy, and an object
modified since the expansion is still one the user asked to remove. Inferring the flag from whether
ETags happened to be supplied made a delete conditional on an empty string, which mismatched every
object and reported `source_changed` having removed nothing — found by a fixture, not by reasoning.

**`assert_item_deletable` is per item and runs BEFORE the transfer.** A whole-list refusal would be
the whole-request reversion this arc's model forbids — and on a `move` it runs after the copy, so it
would leave every item copied and nothing deleted: a full duplicate of the entire selection. The
placement matters as much as the scope: a personal folder holding a **nested** `athenaresults/`
passes the front door (the browser's rule is root-anchored in a personal space) and expands into the
plan, so a post-copy-only refusal would leave it fully duplicated and undeletable — a state the user
cannot resolve through this plane at all.

**It mirrors the IAM POLICY, not the browser rule.** IAM cannot express "at the space root only": a
`Resource` wildcard matches `/`, and this role carries no principal tag to pin one segment the way
the portal role's `${aws:PrincipalTag/username}` does. The strict side is taken — any-depth on both
buckets — and the divergence is handled per item rather than hidden.

## Bytes go to S3 presigned; small text goes through the API (SPEC-198)

Every S3 call the browser made is a route now, with one split running through the middle of it: a
**document** — a JSON settings file, a `.sql` saved query, a folder marker — travels **in the
response body**, and a **file** travels **directly between the browser and S3** under a presigned
URL. Compute never touches a file's bytes.

**The document route's byte cap is what holds that line.** Without it the content route is a second
upload path that bypasses presigning entirely and works perfectly up to Lambda's 6 MB synchronous
response ceiling — which is to say, for every document the app actually authors, and for a good
number of files too. `MAX_DOCUMENT_BYTES` is computed against that ceiling divided by the worst-case
JSON escape expansion, because `json.dumps` at its default `ensure_ascii=True` renders a non-ASCII
BMP character as a six-byte `\uXXXX` escape where UTF-8 stored three: a 4.5 MB CJK document that
fits the cap by its stored size doubles on the way out and fails as a **fault** rather than as a
refusal.

**The document routes never parse.** Parsing server-side is the wrong implementation that looks
identical: it works for every healthy document and turns an unparseable one into a 500 — which puts
SPEC-159's whole quarantine path out of reach, because the classifier never sees the body it must
classify as unreadable. Re-serialising on write is the same defect from the other side: it changes
key order and whitespace, which breaks nothing visible and breaks byte-identity.

**An upload is one `PUT` over `XMLHttpRequest`, and the transport is a requirement.** *(The
transport requirement stands; "one `PUT`" was superseded by SPEC-216 — see the note below.)* `fetch` fires
no upload-progress event, so a `fetch` implementation uploads correctly and leaves the progress bar
at 0% until it jumps to 100% — a shipped feature deleted by a transport choice, with every "the
upload succeeded" test still green. The assertion is on an **intermediate** value, and
`XMLHttpRequest` is confined to one module by a sweep that widens the existing `fetch` one: a rule
forbidding `fetch` and silent about `XMLHttpRequest` permits the same escape hatch under another
name.

**Three consequences of one `PUT` where `lib-storage` auto-multiparted, stated rather than
discovered.** (1) The 5 GiB ceiling **does not move** — it is exactly the single-`PUT` cap and
exactly what the configured maximum already clamped to, and `maxUploadBytes()` now clamps to it so
an operator who raises the configured value gets a refusal rather than an `EntityTooLarge` from S3
at the end of a long transfer. (2) There is **no part-level retry** any more: a dropped connection
restarts the whole file. Accepted; the route trio a later spec would add is
`create-multipart` / `sign-part` / `complete-multipart`, named here so it is added rather than
rediscovered. (3) `MULTIPART_PART_SIZE` and `PART_CONCURRENCY` are gone.

> **Superseded in part by SPEC-216 (2026-09-01).** (2) is reversed — part-level retry exists again,
> and the route trio named above was built with a fourth for abort. (1) still holds, but for a
> different reason and it is worth knowing which: S3 used to enforce the ceiling *unforgeably* by
> refusing an over-size single `PUT`, and multipart has no such limit, so the ceiling is now a
> server-side refusal in the create route. (3) still holds — the names came back in
> `multipartUpload.ts` — only `PART_CONCURRENCY`, and meaning what it always meant, though at a
> different value and against a different budget. `MULTIPART_PART_SIZE` did not come back; the
> only live constant of that name is `cpcommon/transfer/copy.py`'s, which is 1 GiB and is a
> server-side `UploadPartCopy` range, unrelated. Full entry: *An upload's shape is the server's
> decision, and a part is sized so the expiry premise stops mattering*, below.

**The URL is minted per FILE, at the moment that file starts.** A batch mint ages while the queue
drains: with three files in flight and a 15-minute window, the fiftieth file's URL would be signed
long before it was redeemed, pass preflight cleanly and 403 at the end. The mint therefore lives
*inside* `uploadFile`, which is what makes "per file" structural rather than a convention.

## An upload's shape is the server's decision, and a part is sized so the expiry premise stops mattering (SPEC-216)

An upload is no longer one `PUT`. `objects.upload` answers **either** a presigned `PUT` **or** a
multipart plan, and three more routes sign each part, assemble them and abandon them.

**The threshold is one quantity, and the browser never learns it.** "What fits inside one presigned
window on the slowest connection this product supports" bounds a part *and* bounds the largest
object that can be trusted in a single `PUT` — so `MULTIPART_THRESHOLD_BYTES` **is**
`MULTIPART_PART_BYTES`, bound by identity rather than restated. It is computed, not chosen:
`clamp(MIN_SUPPORTED_UPLINK_BYTES_PER_SEC × PART_URL_EXPIRY_SECONDS / PART_WINDOW_SAFETY_FACTOR,
5 MiB, 5 GiB)` = 112,500,000 bytes, and its test states that number so moving any input is visible.
The uplink floor (2 Mbps) is a **product decision stated as one**. The generator emits types, not
constants, so a browser-side fork would need a second copy of a policy number — and a drifted copy
sends files down the wrong path with **nothing failing**. Rejected in favour of one decision site.

**This makes the design correct under either reading of the expiry premise, which is not the same as
settling it.** SPEC-198 accepted, unmeasured, that S3 evaluates a presigned expiry at request
*receipt*. A part minted immediately before it is sent and sized to finish in *half* its window is
sound either way. The premise stays owed, because it still governs a presigned **download**.

**Where the design would fail silently, and what holds each one.** A part that cannot be placed by
its number corrupts the object with S3's blessing — every ETag is genuine, the assembly succeeds,
and the user is told it worked; parts are therefore written **by index**, and the guard needs the
one retry shape where a later part settles first. A plan whose parts cannot cover the file
truncates it and reports success; the browser checks the **arithmetic**, not just that the members
are present. Aggregate progress is the per-part **maximum** — never last-value-wins, which makes the
bar fall on a retry, and never a running sum; a failed attempt's high-water mark is deliberately
kept. And every discard is fired **without** the caller's signal and **without** being awaited: the
queue holds the row until the upload resolves, so an awaited discard leaves a user watching a
progress bar for the client's whole timeout on the arm they meet most often.

**Three things the retirement had to preserve rather than delete.** `UPLOAD_URL_EXPIRY_SECONDS` is
**kept** — it stopped being the retiring route's constant the moment the create route's single
branch used it. The marker-key refusal and the window, clamp, content-type and occupied-key
assertions were **re-pointed** at the new route *before* the old one went, because a deletion leaves
nothing for a reviewer to read. And `test_presign.py`'s two parameterised suites cover upload *and*
download, so only their upload case was removed.

**The ceiling is refused here, and refusing is not enforcing.** S3 used to hold it *unforgeably*
by rejecting an over-size single `PUT`. Multipart has no such limit, and nothing replaces it: the
declared `size` is a **planning input** that nothing verifies, `sign_part` cannot bound a part
number by the plan's count and `complete` cannot check what was sent, because by design the API
keeps **no record of an upload** — and a `ListParts` audit per upload was declined. So a client
that deliberately under-declares can still assemble an object above the ceiling. What the refusal
buys is real but narrower than enforcement: an honest over-size upload fails at create rather than
after its bytes, and the ceiling is not silently **209×** what the product states. Closing the gap
needs server-side upload state, which is a different decision from this one. Its arithmetic is integer throughout, because a caller's number is
arbitrary-precision and float conversion turns an expected refusal into a 500 carrying a stack.

## The folder-recursive functions are deleted, not ported, and the flag stops being a fallback (SPEC-198)

`deleteObjects`, `deleteFolder`, `moveFolder` and `copyFolder` are **gone from the browser**, along
with `listAllKeysUnderPrefix`, `deleteInBatches` and their `onProgress(processed, total)` shape.
Arc A moved every operation whose cost grows with object count onto a control plane; porting these
would have recreated that loop inside a Lambda under a 29-second integration ceiling, and it would
have worked — for small folders, in every test anyone writes.

**`asyncFileOperations` therefore switches a capability off rather than to a slower route.** It used
to be a fallback: with it off, a folder copy, move or delete ran in the browser instead. With the
browser's recursive primitives gone there is nothing to fall back to, so a folder operation is now
~~**refused per item**, with the files selected alongside it still going through~~ **— corrected:
the same change refuses it at the control.** With the flag off, a folder or any multi-item
selection leaves Copy, Move and Delete `aria-disabled` with a reason that does not promise "later"
(`planeReasonFor` in `useFileBrowserDialogs`, pinned for a folder Delete by
`fileOpsDispatch.test.tsx`). The multi-item half is not the deletion's doing: it is the gate
refusing every shape the routing rule sends to the plane. `deleteObjects` went with the recursive
functions, so a multi-file delete is a loop of single deletes — which is what copy and move already
were — though a gesture reaches it with more than one item only through the race below: the
control refuses such a selection with the flag off, and the plane takes it with the flag on.

~~**The refusal is per item, not per request, and that is the whole design of it.** A whole-selection
refusal would lose the files a user picked beside the folder.~~ **— corrected:** the per-item refusal
is the services' half, and the control refuses the whole selection before it when the flag is off —
a folder delete that reached the confirm would ask *"Delete the folder “…” and everything inside
it?"* and then delete nothing. Where the per-item refusal is reached, it still keeps the files picked
beside the folder. The message names the folders that did not move; the code is `PlaneRequired`,
which is authored wording rather than passthrough, because every occurrence says the same thing.

~~**Two paths reach it, and the second is easy to miss.** `useFileBrowserDialogs`'s `routesToPlane`
returns false when the flag is off *and* when a chosen destination resolves to no known space — so
the refusal is reachable with the flag ON.~~ **— corrected: two paths reach it, and neither goes
through the control** — a copy or move whose chosen destination resolves to no known space, which
`dispatch` runs in the browser with the flag ON; and any gesture confirmed after the flag turned
off while its dialog was open, because the control decides when it renders and `dispatch` reads
the flag again when it runs. Recorded because a reader checking only the flag would conclude the
path is dead in production.

## The free-name probe moved to the API, not to the plane (SPEC-198, amends SPEC-187)

`firstFreeName` walked `(1)` … `(999)` with a `HeadObject` per candidate, inside the browser. Behind
the API each probe becomes a browser → API → S3 round trip, which is **strictly worse than what it
replaced** — so the walk is one route, `POST /v1/objects/free-name`, declared `idempotent: true`
(the route SPEC-197 FR-008 names as the reason idempotency is declared rather than derived from the
method: a POST that resolves a free name is a read).

**`numberedName` moved to Python and the TypeScript copy is deleted.** Two implementations of a
naming rule look identical until one of them changes.

**Exhaustion and failure are now distinguishable, and they were not.** The old loop returned `null`
both when 999 names were taken and when a probe errored, and the caller rendered one sentence for
either. The route answers **409 `Conflict`** with `params: {attempts}` on exhaustion; anything else
carries its own code.

> **This amends two written records in place.** `ARCS.md`'s residual note and SPEC-187's table row
> both say *the probe stays in the browser*. It left the browser for the **API**, not for the plane —
> the distinction matters, because the plane would have made a same-folder copy asynchronous.

## An app-managed path is built by one function per tree, and a sweep refuses a second (SPEC-218, superseded in part by SPEC-219)

Three folders the app fills for the user — `athenaresults/`, `archive/` (the receipt folder) and
`shared_tables/` — are moving under a real `system_settings/` prefix over three specs. The obvious
hazard is spelling: the names appeared as literals in four browser modules and eleven fleet modules.
The real hazard is **depth**. Nearly every rule about those folders was anchored at depth one, as
`` `${rootPrefix}${name}/` `` in the browser and `f"{root}{name}/"` on the planes, and at depth two
each comparison stops matching **silently** — a Deny-mirroring predicate that offers a write IAM
refuses, an exclusion that stops excluding, a reserved-root check that lets the folder be archived
and then deleted. `fscommon.authz` had already written the warning into its own docstring.

**The decision: the unit is a builder per fact, not a constant per name.** `lib/appManagedPaths.ts`
and `cpcommon/app_managed.py` declare the names and own the one depth-one anchor (`appManagedPrefix`
/ `app_managed_prefix`, with per-fact wrappers); every anchored construction calls it, so the move is
one edit per tree. Membership lists keep their members and only spell the moving names through the
owner — this changed how a path is *built*, never who is in a list, because the lists answer
different questions on purpose.

> **SUPERSEDED BY SPEC-219 on both counts.** There are now **two** builders per tree: the singular
> one is where a WRITE goes, the plural `app_managed_prefixes` / `appManagedPrefixes` is what every
> root-anchored COMPARISON calls, and ten fleet call sites plus four browser ones moved to it — so
> the move is no longer one edit per tree. And the membership lists **did** gain a member:
> `system_settings` joined five fleet lists and three browser ones, because the prefix the folders
> move into is itself reserved. See *Both homes of a moving folder are admitted before either is
> written to*.

**No builder normalizes.** Each is a pure string over what it is handed, and each caller keeps its own
`normalize_root`. The reason is the API's FIFO group id, which digests the vault prefix: a builder that
normalized would answer 500 on an empty space name the contract admits, and re-key the id for a
slash-carrying one. Byte identity was proved by comparing thirteen before/after strings, the FIFO
digests for empty, slash-carrying and ordinary names among them.

**`archive` is three facts, and exactly one moves.** The receipt folder (`RECEIPT_FOLDER`, space
bucket, moves) and the Glacier vault's key segment (`VAULT_ARCHIVE_SEGMENT`, archive bucket, hashed
into FIFO ids, stays) live in `cpcommon` because two packages each need them. The admin bucket's
control-plane scratch prefix stays as `arcommon.plan.PREFIX`: one consumer, pinned by its own layer
against the IAM grant and the lifecycle rule, and a domain layer owns its constants. An `ACCEPTED_`
tripwire pins all three equal today and says *revisit when the receipt folder moves — do not delete*.

**The population is pinned, not derived.** `test_app_managed_template_population.py` spells the
IAM templates naming a moving folder in a space bucket — eight when this was written, nine since the
results-conversion plane joined the trunk during SPEC-219 — per file, per folder **and per anchoring
segment** (so a path replaced in place reddens it, not only a file joining), and separately the two
naming the admin bucket's `archive/*` that must never gain a sibling. The asymmetry it records
decides the next spec's shape: shared-space Denies are `*/athenaresults/*` and an S3 `*` matches
`/`, so they keep matching after the move; personal ones are anchored at the principal tag and stop
— the unprotected window at cutover is personal-space-only.

**A sweep, not a review, holds it.** `scripts/validate_app_managed_paths.py` refuses a new declaration
or construction outside the owners: Python by AST (a folder-name constant, an f-string or
concatenation building the prefix — from a literal or from an imported name — a module-level
`"archive"`, or `"archive"` beside another managed name in a collection), TypeScript by regex over
comment- and regex-literal-stripped source. It is scoped to **construction**, never to the word:
`archive` is also a mode, a service name and dozens of user-facing sentences, and a bare `'archive'` in TypeScript
is refused only beside another managed name or as a module-level `const`. Its fixture corpus asserts
the *reason* each rule reports and silence on the shapes it must not flag, and every rule and the CI
wiring were mutation-tested. Do **NOT** widen it to the word, and do **NOT** union the membership lists.
What shipped, module by module: `docs/spec-delivery/SPEC-218-one-builder-per-app-managed-path.md`.

## Both homes of a moving folder are admitted before either is written to (SPEC-219)

> **The window this opened is CLOSED (SPEC-220, 2026-09-09).** Each folder has one home again: the
> objects moved, the old prefixes are proved empty and their statements are gone, so nothing below
> describes the current tree. It is kept because the SHAPE is the reusable part — admit additively,
> move, then narrow — and because the narrowing found what admitting additively could not: the
> builders carried every root-anchored rule and none of the six that scan segments. Read the
> entry below this one for what is true now.

Relocating an app-managed folder relocates two things at once: the IAM Deny keyed on its literal
path, and every rule that compares a key to that same path. The window between them is one in which
the data is writable and nothing fails, so this spec opened the destination first and left the
writes where they were.

**One PLURAL builder per tree beside the singular one.** `app_managed_prefixes` /
`appManagedPrefixes` return every root-anchored location a folder may occupy — two for a member of
the moving set while both homes are admitted, one for anything else. Every rule whose answer depends
on DEPTH goes through it; a rule that already reaches any depth by segment keeps the singular and is
asserted at the new home instead. The singular, which is where a write goes, is untouched.

**Both elements are literals, and neither is derived from the singular.** That duplication is the
whole mechanism: derived, moving the write would drag every rule's second home to a third location
that holds nothing. The invariant is not visible in any value — a derived home and a literal one
agree exactly while the singular is depth-one — so it is guarded directly: Python monkeypatches the
singular and asserts the plural is unmoved, TypeScript reads the function's own body, because a spy
cannot intercept an in-module call.

**A folder that is not moving gets exactly one location.** No phantom home: nothing treats
`{root}system_settings/user_settings/` as the settings folder. What refuses a paste or an archive
beneath the new prefix is the prefix's own membership of the reserved lists, by that name.

**Two acceptance criteria could not both hold, and the mechanism changed rather than the goal.**
Naming the reserved folder before anything beneath it, and naming `archive` for a key inside the
receipt folder's new home, are incompatible under one first-match loop. Splitting the direct and
beneath arms from the ancestor arm into two passes satisfies both, and the name is appended last
everywhere. In the browser the item loop stays outermost — hoisting it inside the passes lets a
later item's direct hit outrank an earlier item's ancestor hit, changing a shipped message, and
exactly one test stands between the two shapes.

**Traps this paid for.** A pair test can be structurally vacuous rather than under-specified: once
the parent prefix joins the same list, every second home is a strict descendant of it and no key
distinguishes the two tuples through `startswith` — the test proves the list membership and cannot
prove the re-pointing. And adding the parent to a list gives every rule a neighbour that refuses the
same fixture with the same reason code, so a pair test must assert which folder the refusal NAMES.


## The folders moved, and six Deny mirrors did not move with them (SPEC-220)

`athenaresults/` and the receipt folder now sit under `system_settings/`; their objects were copied
and the sources deleted (`finish` run `34415666578`, 788 deleted, 0 refused; `prove-empty`
`34415782105`), and the old-anchor statements came out. `shared_tables/` did **not** move — those
tables were sent to the space and are the user's to edit — so it keeps its depth-one anchors and the
`system_settings/shared_tables/` ones SPEC-219 added additively came out instead. A depth-one
**Allow** came out too: results-conversion held `s3:GetObject` on `*/athenaresults/*`, and every
other anchor removed was a Deny, so that one's survival would have been an escalation over a path
the narrowing makes ordinary rather than a de-restriction.

**The builders carried the anchored rules; they did not carry the any-depth ones.** A rule mirroring
a SHARED-bucket Deny cannot compare a prefix — the Deny's wildcard sits where the space name goes and
matches `/`, so it reaches the folder at any depth — so it scans segments instead. Six did, and all
six scanned for the bare folder NAME, fed by no builder: `writeLockedPrefix.ts`,
`focommon.protected._is_at_or_below`, `focommon.delete.assert_item_deletable`,
`apicommon.protected._is_write_locked`, `arcommon.plan._assert_deletable_folder` and
`rccommon.paths.protected_refusal`. After the move each refused writes, deletes and archives IAM
permits, in a folder the user made and called `archive`.

**Five were found by chasing one reviewer finding through the tree; the sixth was found by a
security review AFTER the count had been written down.** It was the worst of them: `results-conversion`
refused a destination the browser's picker had just started offering, so *Save results* could send a
user to a folder the plane would reject. Enumerate such a population from the tree, never from the
instances that happen to redden a test — the safe-failing ones redden nothing.

**The reason it survived a green suite is the direction it fails in.** Over-refusal produces no
error anyone reports — a control greys out — and every pair test asserted only that the refusal
happened. So the pair tests were **inverted rather than collapsed**: each keeps two rows, and the
retired home's row expects `null`. A single row would pass just as happily against a rule still
anchored at depth one, which is the regression the narrowing can introduce. `app_managed_segments`
is now the one home for the segment form, as `app_managed_prefixes` is for the prefix form.

Do **NOT** re-reserve the three names at a space root: after the narrowing `alice/athenaresults/` is
an ordinary user path, and the dialogs' refusal of those names *directly inside* `system_settings/`
is partial by construction — uploads, pastes and plane-side moves create folders without the
validator. A root-aware, all-paths guard is its own spec. `scripts/migrate_system_settings.py` stays
and every mode now refuses `narrowing_already_merged`, which is what makes the destructive workflow
inert rather than merely un-dispatched. Full write-up:
`docs/spec-delivery/SPEC-220-move-the-app-managed-folders-then-narrow.md`.
