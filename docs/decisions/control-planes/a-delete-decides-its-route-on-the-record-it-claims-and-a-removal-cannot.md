---
type: Decision
title: "A delete decides its route on the record it claims, and a removal cannot take the owner off the roster (2026-09-26)"
description: "`registry.begin_delete` is the first write of delete and forget and decides route and owner inside its swap; `save_members` refuses a removal naming the current owner, and `finalize` refuses a record absent, `deleting`, re-owned or last written by another request."
---

**Found by the same data-loss audit.** Two races on the shared-spaces plane, neither losing file
bytes, both apply-green. Each verb decided something on a read and acted after it, and what it
decided was not re-checked on the record it then wrote to.

**A removal could strip the owner.** The validator refuses a leave by the owner and a removal
naming the owner, on the record it loaded. A transfer to that member committing after the load
made the leave or removal complete against the new owner: owner bob, bob not on the roster, his
Cognito slot cleared and his index entry dropped — and the add normalises an owner out, so no verb
could give him either back. `TransferTargetNoLongerMember` closes only the other order. **One
predicate, `registry.refuse_removing_owner`, now refuses such a removal twice:** on a fresh read
the verb takes before it clears anything, which covers the ordinary window between the validator
and the verb with nothing to repair; and inside `save_members`' swap, whoever calls it, which
keeps the roster rule absolute for a transfer landing after that read. Refusing the whole removal
mirrors the validator's own `MemberRemoveOwner`, and the user reads the existing `OwnerChanged`
sentence, which is true of both verbs.

**The second refusal comes after the slots are cleared**, because clearing first is what keeps a
faulted leave or remove retryable. So `membership.reinstate_owner` gives back the NEW OWNER's slot
and card, and no one else's; the other cleared names stay listed without a slot — a denial the
owner mends by removing and re-adding them, reachable only when a transfer commits during the
verb's clearing pass, a Cognito read and write plus a cache write per name. **Two reviews each
reproduced this restore granting**, and the second instance is what made it structural rather than
a third patch. A first draft granted on a roster read before the grant, and a delete emptied the
space in between. The next granted first and confirmed with a read after, which still leaked: a
removal that had cleared the member early committed after the space went to them and back. What
holds now is an invariant, not a check: **every writer that ends someone's place on a roster
revokes AFTER a write the confirming read can see** — a delete and a forget claim before they
revoke, and a leave and a remove now clear the slot and card again after their own commit. So
whatever ends the ownership is either seen by that read, which takes back the slot and the card
(both written before it), or revokes after the grant.

**The destroy decision was not bound to the record destroyed.** Delete read the record, chose its
route with `is_destroyable`, then wrote `deleting` re-checking only the owner; forget wrote nothing
before its teardown and never re-checked the owner at all. And `finalize` rebuilt the record from a
literal, overwriting a `deleting` claim. So the owner's create retry going active either side of
the delete's first write was torn down after reporting ready, and a second dismiss validated
against a name its actor had already freed tore down the next user's reservation (the database
marker already kept a user's personal catalog out of reach). **`registry.begin_delete` is now the
first write of both verbs**: one swap that refuses an absent record, decides the route on the
record it read, re-checks the owner, writes `deleting` and stamps `everActive` on the emptying route
so the record reads as the route it took. A write landing after its read fails the swap, and the
retry decides again. Forget passes `only_if_destroyable`, so a usable space is still left unwritten,
and a record that changed hands takes its cache-only path. **`finalize` refuses a record that is
absent, `deleting`, owned by someone else or last written by another request**, on both outcomes, so
nothing can turn a claimed space usable while it is torn down, and a create racing a teardown fails
and says so. The request-id clause is the one a review showed was needed: a delete whose teardown
faults writes `failed` over its own claim, and without it the create's finalize then took the
record back to active over a revoked grant and a deleted marker. Its one cost is a denial: a create
whose index write fails after `finalize` succeeded cannot record `failed` if another writer landed
in between, so the space stays active with the owner's slot rolled back. `set_status` lost
its `expected_owner`, whose one caller was the delete's first write.

**What it costs:** a forget whose teardown faults now leaves `deleting` rather than the status it
found, as a killed delete does, so the owner's create retry is refused as taken until the forget is
retried from the card it removes last.

## History

### 2026-09-26

- **Settled:** entered the register.
