---
type: Decision
title: "A delete removes people, not things — and retention keys on a durable fact, never live status (SPEC-205)"
description: "**A shared-space delete removes PEOPLE, not things**, keyed on the durable `everActive` — never live `status`, which moves `active → deleting → failed` over intact data, and where `deleting` is **not** evidence a space was usable (delete is gated on ownership alone). **One predicate**, `is_destroyable`, routes the delete AND refuses the add; complements written twice drift silently both ways. Inert because the `owner` **field** is cleared, or for the member actions `emptiedAt` — so test it **as the original owner** AND on a live record. A name is never reusable. **The route and the owner are decided INSIDE the swap that claims the record** (`begin_delete`, for delete and forget), never on a read before it: a route read first tore down a space a create turned active in between. `finalize` refuses any record that is no longer its own reservation, so a create cannot turn a claimed space usable after the claim either (`a-delete-decides-its-route-on-the-record-it-claims-and-a-removal-cannot.md`). **A partial teardown never frees the name.** `delete_objects` returns **HTTP 200 with a per-item `Errors` array**, so a partial failure reads as success; raise, and leave the registry record — the record *is* the name lock."
---

Deleting a shared workspace ends every member's access, the owner's included, and destroys nothing:
the objects, the Glue database and the registry record all survive, and the record keeps
`status: "active"` with an empty roster. The bucket has no versioning, so the behaviour it replaces
could not be undone at all; this one is undoable by an administrator. Two costs are permanent and
product-visible, and both are said where users can see them: **the name is never reusable**, because
the record that locks it is never released, and **data a user asked to delete is retained**.

**Retention keys on `everActive`, a durable monotonic field, and not on live `status`.** A status
moves `active → deleting → failed`, and every one of those transitions describes a workspace whose
data is intact — so a route chosen from status destroys live data on a delete that failed once. The
field is stamped by `finalize` **only** on the active outcome, because `finalize` runs on both create
outcomes and an unconditional stamp marks every failed create ever-active, which refuses its owner's
legitimate retry and refuses to tear it down. An AST sweep holds it monotonic: no module may write it
anything but `True`, and `pop`/`del` count as writes.

**`deleting` is NOT evidence that a space was ever usable, and a draft of this spec said it was.**
The reasoning looked sound — only `delete_space` wrote that status then (forget's claim writes it too
since 2026-09-26, on a never-usable space only) — but deleting is gated on
ownership and nothing else, since neither the validator nor the authorizer inspects status. So an
owner may delete their own failed or still-provisioning create, and the verb writes `deleting`
*before* any teardown; an invocation that dies rather than raising leaves that status permanently,
because the machine records a failure without writing one. A `deleting` record can therefore name a
space that was never usable. The one-shot backfill stamps `active` **only**, and every other status
is a row a human dispositions — for a `failed` record **the discriminator is the space's resources
and its timestamps, never its roster**, since a failed create can have been added to and a failed
delete of a single-member space is single-member too. Even the resources collide: a create writes its
marker object second and its database third of eight steps, so most failed creates hold both.

> Found by executing it rather than reading it, which is why the criterion it replaces had survived
> two rounds of review.

**A partial teardown never frees the name.** `delete_objects` returns HTTP 200 with a per-item `Errors` array, so a partial failure reads as success; raise, and leave the registry record, because the record is the name lock.

## History

### 2026-09-26

- **Changed:** Forget's claim now writes `deleting` too, on a never-usable space only.

### 2026-08-31

- **Settled:** SPEC-205.
