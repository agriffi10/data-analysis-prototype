---
type: Decision
title: "A conflict is one item's outcome, and the list is created once and carried forward (SPEC-188)"
description: "Per-item outcomes live in one list that each verb takes as input and returns whole, merged only by `focommon.outcomes.carry_forward`; an item an earlier verb decided is never expanded, and only a proven absence is `source_missing`."
---

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

## History

### 2026-08-17

- **Settled:** SPEC-188.
