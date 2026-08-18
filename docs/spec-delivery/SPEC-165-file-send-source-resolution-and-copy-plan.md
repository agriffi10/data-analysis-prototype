# Completed Spec — SPEC-165: Send Files — Source Resolution & Copy Plan (inspect-source)

## What was completed?

Everything a send will copy, and where each object will land, is now worked out — once, in one
verb — and written down. A user still cannot send a file: nothing is copied, and no key is
written to any recipient's space. What exists is the plan that SPEC-166's manifest builder reads.

- **`fscommon.expand`** — item resolution (a `file` HEADs, a `folder` walks the shared paginator
  past its 1,000-key boundary), this plane's own exclusion rule, the overlap / duplicate /
  name-collision rules, the containment re-check on every listed key, and the two caps.
- **`fscommon.paths`** — `item_name`, `relative_key`, and `destination_key`, the one builder for
  `{targetRoot}shared_files/{sender}/{item}[/{relKey}]`; **`fscommon.authz.recipient_location`**,
  the twin of `authorize_source` that says which bucket and root a recipient's inbox sits in.
- **`fscommon.copy_plan`** — the plan at `{admin}/file-send/{requestId}/copy-plan.json`, with
  `expire-file-send-copy-plans` to clear it.
- **`file-send-inspect-source`** — the verb. Emits `{copyPlanKey, objectCount, totalBytes}` onto
  the request; no object key returns to the state.
- **ASL** — `Validated → InspectSource → Planned → Succeeded`, plus a **second** failure seed.
- **Three PRs**: infra (#421) before the code and the wiring (#422), then completion (#423).

## The exclusion rule is this plane's own, and reuse would have been a silent defect

`cpcommon.s3_listing.is_ignored` anchors `athenaresults/`, `user_settings/` and its
hidden-segment test at the **listing prefix**. That is right for the three planes that list a
table's or a check's own folder, and wrong here, where the listing prefix is whichever item the
user picked: sending `alice/reports/` would have dropped a user-made `reports/athenaresults/` —
which SPEC-164 records as an ordinary sendable folder — and any `_drafts/`, with **no refusal and
no message**. The hidden rule also exists because *Athena* ignores those paths, which says nothing
about a byte-for-byte copy.

So `list_data_objects` grew an optional `ignore` predicate rather than being forked: one
paginator still pages past 1,000 keys, and a plane whose exclusions are anchored somewhere else
says so at the call site. The default is byte-identical for the three existing callers and a test
holds that in both directions.

Two consequences worth carrying. A **genuinely empty file is sent** (the analytics rule drops
every zero-byte object; a folder placeholder is excluded by its trailing slash instead, the shape
`createFolder` writes) — so an **empty subfolder does not survive a send**, which is FR-001 AC4's
own choice. And the `{root}athenaresults/` exclusion has **no live path** through the shipped
front door, because validate-authorize refuses a root selection outright; it is written anyway,
for the reason SPEC-164 gave for writing that rule as containment rather than equality.

**`user_settings/` is excluded too, and it is not in FR-001 AC4's list.** Narrowing the analytics
set to the spec's three rules would have dropped it without anyone deciding to: it holds the
sender's notification inbox and shared-space connections cache, the browser hides it everywhere,
and unlike the two rules this plane deliberately does not reuse, anchoring it at the space root
preserves the exclusion with **zero** false positives — a user's own `reports/user_settings/`
still sends.

## Deliberate deviations

- **No `SEND_MAX_OBJECT_BYTES`.** Its table-share twin is sized by the copy verb's batch makespan
  against `COPY_TIMEOUT_SECONDS`, and none of that exists on this plane yet. The plan carries
  every object's size, so SPEC-166 enforces it with no second listing and still before any byte
  moves. FR-004 names two caps and this keeps to them.
- **No recipient product cap either**, for the same reason and to the same place. **Both** gaps
  carry a tripwire that fails the day SPEC-166 adds the cap, so neither is an oversight — and the
  per-object one matters more than it looks: `test_a_full_size_selection_copies_inside_the_engines_ceiling`
  certifies the **distributed** case only. One object is copied by one worker at 25 MB/s, so a
  single 1 TiB object is **43,980 s**, four times over the ceiling. That is table-share's recorded
  shape exactly ("*while `SHARE_MAX_TOTAL_BYTES` was 20 GiB the bound was implicit … raising the
  total to 1 TiB removed it without anything replacing it*"), and this plane starts at 1 TiB. The
  arithmetic is kept as a test so 166 inherits the size of the problem rather than re-deriving it.
- **`destination_key` and `recipient_location` ship with no production caller.** FR-003 puts the
  layout in scope here and its consumers are SPEC-166's; the sweep that forbids a second builder
  is what makes shipping the first early worth anything.
- **FR-001 AC5's zero-object refusal is whole-selection, not per-item.** A selection of
  `[empty_folder, folder_with_files]` succeeds and the empty folder contributes nothing. The AC's
  wording reads both ways; refusing a whole send because one of five folders turned out empty is
  the worse reading.
- **FR-004 AC1's "measured value" is what the walk had reached, not the true total.** The caps are
  enforced *during* the expansion, so nothing counted the rest — the refusal says
  "reached N and was still counting, over the cap of M" rather than a bare cap.
- **`copy_plan` has `write` but no `load`.** The reader belongs with its caller.
- **The plan key is the request id, not a digest.** Table-share hashes the fields identifying a
  share because it has no request id; this plane's is already the FIFO
  `MessageDeduplicationId`, so replay safety comes free and two similar requests cannot collide.
- **No component-inventory rows for `fscommon.paths`/`config`**, which Phase 5 asks for. The
  inventory is **browser-only** — every area file is scoped to `apps/portal/src/`, and no plane's
  Python layer appears in it, including the `fscommon` modules SPEC-164 shipped one spec ago.
  Opening a Python section for this plane alone would leave four others' layers looking like
  omissions rather than a convention. The layer's public surface is its docstrings.

## What changed from earlier specs?

- **`cpcommon.s3_listing.list_data_objects`** gained an `ignore` parameter, defaulted to today's
  rule. No behaviour change for table-builder, table-share or data-quality.
- **The `Validated` state lost its `"status": "validated"` literal** and its terminal role. It is
  kept, and its whole job is now the ASL/verb cross-check — a Task hands its output on whole, so
  nothing between two Tasks notices a renamed field.
- **The send-files acceptance script** — its first check now ends at `Planned`, and its file key
  must really exist, because inspect-source HEADs it.

## The caps are computed, and the dominant term is not the obvious one

`SEND_MAX_OBJECTS` (20,000) is sized by **the plan the verb holds in memory**, not by the
listing: ~45 MB serialised at S3's worst-case keys, peaking near 135 MB across the list, the
string and the bytes, against the 1024 MB in `locals.tf` — which the test **reads back**, so
raising one without the other fails the build. The timeout half is where the obvious model goes
wrong: a page-counting model gives 20 round trips and 4 seconds, and misses that a `file` item
costs its **own serial HeadObject**, so 200 files is 200 round trips and 40 seconds. The bound is
per-ITEM plus per-PAGE, and the item half dominates — pinned by its own assertion.

`SEND_MAX_TOTAL_BYTES` (1 TiB) is sized by the copy's **makespan** at the rate
`cpcommon.transfer` actually delivers — `MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND`,
500 MB/s, not the aggregate 4 GB/s the same constants suggest. 2,199 s against the 10,800 s
ceiling the identical engine already runs under.

## The failure path needed a second seed, and the fleet guard cannot see it

This plane's `RecordFailure` reads `$.raw`, which exists on **no** post-validate state — the
request is deliberately not threaded through, because the Pipe record carries the selection again
as an escaped string. A catch routed straight to `RecordFailure`, as every other plane's catches
are, raises an uncatchable `States.Runtime`: the execution dies before `NotifyFailure` and the
sender hears nothing, on exactly the failures SPEC-152 exists to report.

`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` identifies a seed
**structurally**, as a Pass whose `error.$` is `"$"` — the pre-identity shape. `InspectFailureSeed`
is the other shape (`"$.error"`, because its catch carries a `ResultPath`), so the fleet walk
skips it entirely. The local suite compensates with a walk that derives, from the machine, what
Step Functions actually leaves on the state at each catch — `ResultPath: "$.x"` means the task's
input plus `x`, no `ResultPath` means the error replaced everything. **Verified by mutation: six
edits, six failures**, including the one where the catch bypasses its seed, which an earlier
version of the walk passed vacuously.

## What the review round caught

All four were guards or rules that read as satisfied. Recorded because the shapes recur:

1. **`_collapse` deduplicated on the key alone**, and validate-authorize normalises a *folder*
   key to a trailing slash while leaving a *file* key untouched — so `{"file","alice/reports/"}`
   and `{"folder","alice/reports"}` arrived as one key with two kinds. Whichever came first won:
   the file reading sent one zero-byte placeholder and **none of the folder's contents**, and
   reported success. An outcome depending on the order of a JSON list, and the exact silent drop
   FR-002 exists to prevent. Keyed on `(kind, key)`, both survive to the overlap rule.
2. **The exclusions were applied only to a listing.** A `file` item is filtered by nothing
   upstream, so naming the prefix marker as a file copied it into someone's inbox, and naming a
   folder *as a file* copied its placeholder as a file. AC4 says excluded from the copy set; it
   does not say "when they turn up in a listing".
3. **The containment re-check was untested — deleting its body left the suite green** (measured).
   Its one test passed on a *different* check: an out-of-root listed key is also outside the item,
   so `relative_key` refuses it with the same reason either way. The re-check's only live content
   on that path is the **dot-segment** rule, and nothing exercised it.
4. **The per-object cap's gap had no tripwire**, only prose — the weaker half of the pair, and the
   half whose absence undermines a test that otherwise reads as satisfied.

Two guards were also decoration (`20000 > 200`, `pages < SEND_MAX_ITEMS`) and now assert the claim
rather than arithmetic on two constants. The local ASL walk gained Catch edges; it followed only
`Next`, which is harmless today and would not be once 166 adds a Pass behind a catch.

## Verification

`ruff check lambdas/` clean, `mypy` clean over the five layers, `pytest lambdas/` 2719 passed at
97.16% (100% on every module this spec added), `tofu validate` and `tofu fmt -check -recursive`
clean. Every fix above is mutation-verified: neutering `_checked`, reverting `_collapse` to
key-only, skipping the exclusions on the file branch and dropping `user_settings/` each turn the
suite red.

**Owed live check: `docs/testing/e2e.md` §4.9 (the one-account half) and `docs/testing/owed.md` — the receiving half needs a second account, and the 1,200-object pagination boundary is its own ledger row.** One folder of more
than 1,000 objects, whose plan's `objectCount` must equal the bucket's. The pagination boundary is
the one thing a fixture proves least — a fake that pages is only as honest as the person who wrote
it, and a verb that stops at one page reports a plausible smaller number rather than an error.

## Help & guides

**No change, and that is deliberate.** Nothing user-facing shipped — there is still no Send
control (SPEC-167), and nothing is copied. Documenting it now would break SPEC-074 FR-005.
