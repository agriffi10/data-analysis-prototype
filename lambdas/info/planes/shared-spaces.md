# Shared spaces — control plane

Creates and manages shared spaces: who owns one, who belongs to it, and what happens when someone
leaves. Access is a **membership principal tag**, so the roster is the authorization.

A shared space is a named collaborative space, where the name is at once the S3 prefix in the
shared-space bucket and the Glue database name — globally unique and non-renameable, exactly as a
username is for a personal space. The creator is the **owner**: they add and remove members
(validated against the User Pool via `ListUsers`/`AdminGetUser`, with unknowns silently dropped) and
they delete the space, which cascades through files, tables, the database, every slot and cache, and
the registry record. Members leave on their own; everyone sees one shared copy. **Create is
creator-only** — members are added after the fact.

This plane is a `Choice`-routed fan-out rather than a pipeline — one verb runs per request.

**Its queue has TWO producers**, which is true of no other plane. The API is one. The other is
`shared-space-transfer-reader`, a scheduled Lambda that reads an operator's CSV out of
`<admin-bucket>/operator-requests/inbox/` and enqueues requests — the door for the cases where the
person who should act is the person who is absent. Its header is `space,action,username`, its
`action` column is one of **`add`, `remove`, `transfer`**, and the rows sharing a `(space, action)`
become **one** request, so an operator-driven add is the same verb, the same authorization and the
same notifications as an owner-driven one. It runs under its **own** execution role, because the
boundary that admits its messages compares the `SenderId` against exactly that role.

Its name under-describes what it reads and is kept anyway: the role's unique id is half of that
`SenderId` comparison, so renaming rotates the value the boundary compares against, and any operator
file consumed in that window is filed away with every one of its rows refused. A misleading name is
paid for in a docstring; a rotated role id is paid for in lost work.

## The machine

`infra/modules/shared-spaces/state-machine.asl.json.tftpl`

`Validate → Route → { CreateSpace | AddMembers | RemoveMembers | Leave | DeleteSpace | ForgetSpace |
AcknowledgeMembership | TransferOwnership }`

`UnknownActionSeed` is the arm for an action the router does not recognise. **`RefusedSeed` is the
arm for an expected refusal**, and it is the router's FIRST branch so a refused request reaches no
verb whatever action it names — see *Why some refusals return where the rest raise* below.
`AcknowledgeMembership` flips the member's chip from pending to active and is display and
bookkeeping only — access is granted at add time. One shared **`orchestrator`** role covers the state
machine and every verb.

## Where the state lives

- **The registry is the source of truth:** `<admin-bucket>/shared-spaces/{name}.json`, writable by
  the pipeline alone. Name uniqueness comes from a conditional `PutObject` (`If-None-Match: *`);
  every mutator is ETag compare-and-swap. The admin bucket's expiry lifecycle excludes this prefix.
- **The per-user UI cache** is `{username}/user_settings/shared-connections.json`, written by the
  pipeline into each member's own prefix, carrying a per-entry status of `provisioning`, `active`,
  `failed` or `leaving`. A missing cache is an empty state, never an error.
  `cache.write_roster_to_all` fans the roster out on add, remove and leave.
- **The per-user membership index** is `<admin-bucket>/memberships/{username}.json`, holding
  `{version, username, spaces: [{name, status}], updatedAt}`. It is the projection that answers
  *which spaces is this user in* in one `GetObject`, which the registry — one object per space,
  keyed by space name — cannot do without a listing plus a read per space. Written under ETag CAS
  by the six verbs that move a Cognito membership slot, at the same consistency point the roster
  fan-out uses. **Never deleted:** a user with no spaces holds an empty list, because a deleted
  document and a user who was never a member are indistinguishable.
- **Results routing:** querying a shared database sets the per-query `OutputLocation` to
  `{shared-space-bucket}/{name}/athenaresults/{username}/`, which is delete-denied, mirroring the
  personal lock. Personal queries route to the personal `athenaresults/` unchanged.
- **Lake Formation:** the bucket is registered hybrid, and create-space issues the per-database grant
  to the shared portal role, exactly as the personal-database path does.

## The fences

- **Locks are objects claimed under ETag CAS, released by OVERWRITING.** With `DeleteObject` denied,
  "free" is a *state* rather than an absence. The holder is the **execution ARN**, because a request
  id identifies the message and Pipes delivery is at-least-once.
- **A partial teardown never frees the name.** `delete_objects` returns **HTTP 200 with a per-item
  `Errors` array**, so a partial failure reads as success. Raise, and leave the registry record —
  **the record IS the name lock**.
- **Every member sees the roster.** The join acknowledgement is display-only, since access is
  granted at add time.
- **No shared-space directory is published.** A full list would be more useful and is declined as a
  disclosure with no equivalent.
- **A space's name is format-checked nowhere server-side**, which is why every statement built from
  it must use the right escaper — see the table-share page.

## The layer — `shared-space-common/`

This layer is **top-level modules, not a package** — the only one shaped that way.

| Module | Holds |
|---|---|
| `auth` | action authorization — its verification adapter is gone, and `cpcommon.actor` supplies the actor |
| `cache` | the per-user shared-connections cache in the user-space bucket |
| `casio` | this plane's door to `cpcommon.cas` |
| `config` | domain configuration |
| `membership` | per-user membership slots in Cognito custom attributes |
| `membership_index` | the per-user membership index in the admin bucket |
| `messages` | user-facing failure wording |
| `notify` | best-effort notification emit |
| `registry` | registry I/O — the source of truth |
| `teardown` | shared resource-teardown helpers |

The verbs are listed in [`../INDEX.md`](../INDEX.md).

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

### `shared-space-common/membership_index.py` — why it does not inherit the fan-out's posture

It writes at the same point `cache.write_roster_to_all` does, after the registry commits, and it
deliberately does **not** copy that function's `except: log and continue`. A stale roster is
cosmetic — one member sees an out-of-date member list. A stale index is an authorization input
that is wrong, and on a removal it is wrong in the **granting** direction. So every failure raises
and the plane's per-verb `Catch: States.ALL -> RecordFailure` turns it into a failed run with a
notification. An implementer reusing the fan-out will find the tolerant version first; this is why
it must not be copied.

Two more differences from `cache.py`, each load-bearing:

- **A denial is not absence.** `cache.py` reads `AccessDenied` as a missing object, which is safe
  there only because its write is create-only. Here the same tolerance would read a
  present-but-unreadable index as "member of nothing". Both roles hold a `ListBucket` on the admin
  bucket conditioned to `memberships/*`, which is what makes S3 answer `NoSuchKey` at all.
- **A malformed document raises its own type.** Unreadable is not absent, and the two must not
  share a branch.

**Two placements are the whole of the ordering.** `create` writes the index *after*
`reg.finalize(..., "active")` and *inside* the provisioning guard: after, because a space still
`provisioning` yields no tag, so an index written mid-create is immediately wrong; inside, because
outside it a failure leaves an active space whose owner holds no entry — and once membership comes
from the index, that owner can neither reach the space nor delete it, since delete is gated on
membership. `delete` drops the entries inside its member loop, which runs *before* `reg.delete`:
the record is the name lock, so an index still naming a space whose name is free is an entitlement
to whatever is created next. **`forget`'s teardown path calls `reg.delete` too**, so it drops the
whole roster's entries rather than only the actor's — "a failed create is single-member" covers a
failed create and not a delete that failed partway, which writes `failed` on a record that keeps
its members.

**One residual, stated rather than left to be found:** a stored `status` is stamped at write time
and refreshed by nothing, so a `set_status` with no membership change leaves a not-yet-dropped
member's entry reading `active` for a space the registry calls `failed`. The registry stays the
authority on status; the index answers *which spaces*, and the sweep in `transition_plan.md` §3.11
is what reconciles the two.

### `shared-space-common/registry.py` — why a membership write is a delta

`save_members` takes **deltas** (`add=`, `remove=`, `acknowledge=`) and derives the new roster
inside its own compare-and-swap. It used to take the roster the caller had computed from
`event["registry"]` — a snapshot read before the request began — and assign it over the
freshly-read record. So the CAS re-read the record and then overwrote the one field it exists to
protect with a stale value: two overlapping requests on one space were **last-write-wins on the
roster**, and a concurrent remove reinstated a just-added member (SPEC-151 FR-004).

Nothing serializes those requests. `shared-spaces/pipe.tf` is `FIRE_AND_FORGET` and the FIFO
group id is one global constant, which `cpcommon.cas`'s module docstring says outright (it was
`casio`'s until SPEC-156 FR-001 moved the loop).

**Four callers, not three.** `acknowledge-membership` is one too, and it is the only one that
*adds* to `acknowledged`. Left out of the conversion, it would have kept passing a whole computed
list and kept the defect.

**`status` is no longer written by this path.** It used to be forced to `"active"`
unconditionally, which let a membership write racing a delete return a `deleting` space to
`active` — the cascade would then run against a record claiming to be healthy. Only a
`setdefault` remains, to heal a record written before the field existed.

### Why some refusals return where the rest raise

Three actions on this plane decide by RETURNING a `(code, message)` pair on the validated context
rather than by raising `AuthorizationError`: `transfer_ownership` through `auth.transfer_refusal`,
and `add_members` and `remove_members` through `auth.member_refusal`. That is not a style choice
and it is not optional.

> **SPEC-217 widened this from the transfer verb alone.** The two member actions left
> `OWNER_ONLY_ACTIONS` and now decide the same way, for the same reason and through the same
> `RefusedSeed` arm — which needed no change, having been written action-independent. Read "a
> transfer" below as any of the three. Full entry:
> [*The operator door widens to member management*](../../../docs/decisions/control-planes.md#the-operator-door-widens-to-member-management-and-that-is-a-threat-model-decision-spec-217).

The validator's `Catch` carries no `ResultPath` — you cannot merge a key into the raw SQS array it
was handed — so a raise there **replaces** the state, and `ValidateFailureSeed` seeds `actor: null`.
The notifier reads a null actor as no trustworthy recipient and stays silent. The refusals that
still raise can afford that; these three cannot, because a refusal that says "that person is not a
member" is useless without naming the person, and the composed failure wording is handed only an
action and a space.

**Two things an implementer will get wrong here**, both of which ship green:

- **`IsPresent` is TRUE for a present-and-null field.** Seeding `refusal: None` on the happy path —
  which this plane's own `ValidateFailureSeed` comment actively encourages, since a null value is
  safe there where a missing key is fatal — routes *every* request on the plane into the refusal
  branch. The key is set only when there is a refusal, and the Choice rule pairs `IsPresent` with
  `IsNull: false` so it is correct either way.
- **The Choice is not the only fence.** `set_owner`'s expected-owner check is a *lost-update*
  guard, and for a forged operator message nothing about the owner has changed — so it passes. The
  verb refuses a context carrying a refusal for that reason: without it, any failure of the routing
  completes a real transfer.

The full reasoning, and the rejected alternatives, are in
[`../../../docs/decisions/control-planes.md`](../../../docs/decisions/control-planes.md).
