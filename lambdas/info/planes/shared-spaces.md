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

## The machine

`infra/modules/shared-spaces/state-machine.asl.json.tftpl`

`Validate → Route → { CreateSpace | AddMembers | RemoveMembers | Leave | DeleteSpace | ForgetSpace |
AcknowledgeMembership }`

`UnknownActionSeed` is the arm for an action the router does not recognise.
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
| `auth` | token verification and action authorization |
| `cache` | the per-user shared-connections cache in the user-space bucket |
| `casio` | this plane's door to `cpcommon.cas` |
| `config` | domain configuration |
| `membership` | per-user membership slots in Cognito custom attributes |
| `messages` | user-facing failure wording |
| `notify` | best-effort notification emit |
| `registry` | registry I/O — the source of truth |
| `teardown` | shared resource-teardown helpers |

The verbs are listed in [`../INDEX.md`](../INDEX.md).

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

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
