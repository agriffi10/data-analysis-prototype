# Spec: `user_settings/` Recovery from an Unreadable Document

**ID:** SPEC-159
**Status:** Draft
**Last Updated:** 2026-08-09
**Depends On:** SPEC-043 (saved queries), SPEC-048 (query history), SPEC-106 (the user-facing error-wording contract), SPEC-155 (`lib/s3Json.ts`, and the `lib/` → `features/` layering rule this must not break)

> **This spec adds no user-facing feature.** It finishes a fix that stopped halfway: the branch
> that closed the data-loss path left the resulting failure **permanent**, and this is the
> recovery route out of it.
>
> **It needs NO IAM change.** Everything it does is `GetObject` + `PutObject` inside the user's
> own prefix, both already granted. That is load-bearing and is stated as a constraint (FR-005),
> not left as a happy accident.
>
> **Rulebooks:** `docs/best-practices/react/react.md` (§19 comments, §21 tests).

## Overview

A user's saved queries and query history live in two JSON documents the browser
read-modify-writes: `{username}/user_settings/saved-queries.json` and `query-history.json`.

Until recently both parsed **forgivingly** — any body that was not `version: 1` with the right
array became the *empty* document — and then wrote back with an unconditional `PutObject`. So a
body the reader could not interpret was **committed as empty**: one Save replaced the whole
saved-query library with the query being saved. That is now fixed: the write path refuses a
document it cannot read instead of overwriting it.

**The refusal has no way out.** `user_settings/` denies `s3:DeleteObject`
(`portal-role-analytics.json.tftpl:69-71`), so the browser cannot remove the bad object.
`PutObject` is allowed — but overwriting is precisely what the fix forbids. There is no admin UI
(out of scope, `CLAUDE.md`) and the bucket is unversioned (deferred by decision, SPEC-138). So one
unreadable document permanently disables saving queries and recording history **for that user,
forever**, and the only remedy the message can honestly offer is "Contact the Administrator" —
whose only tool is the AWS console.

**The severity is low-probability and high-consequence, and the spec says so rather than inflating
it.** S3 `GetObject` is strongly consistent and returns whole objects, so a torn read is not a
real trigger; the realistic ones are a previously-committed bad document and a **future schema
version read by an older client**. But when it does happen it is unrecoverable in-app, silent
until the user tries to save, and it lands on the one folder the app deliberately made
tamper-resistant.

The fix is **quarantine-then-proceed**: copy the unreadable bytes to a sibling key, and only once
that copy is durably written, write the fresh document. That keeps the evidence *and* unblocks the
user, which neither the old behaviour (destroy it) nor the current one (refuse forever) does.

**A newer schema is not corruption, and must not be quarantined.** Quarantining a `version: 2`
document written by a newer tab would be a destructive downgrade — the fix causing the very class
of loss it exists to prevent. That case is a refusal with different advice, and it is the reason
FR-001 exists at all.

## Scope

### In Scope

- **A three-way parse outcome** for both documents: readable, *newer schema*, unparseable.
- **A quarantine primitive** in `lib/s3Json.ts`, issuing its own `CopyObjectCommand`.
- **Quarantine-then-proceed** wired into both write paths, with the copy as a hard precondition.
- **Three distinct user-facing outcomes**, worded in `lib/errorMessages.ts` per SPEC-106.
- **The accepted consequences, recorded** — quarantine objects are themselves undeletable.
- **The rejected alternatives, recorded** so they are not re-proposed.

### Out of Scope

- **Conditional (`IfMatch`) writes.** They close the *concurrent-writer* race, which is a
  different bug and is explicitly accepted today ("last-writer-wins on a single user's own file").
  They do nothing for an already-unreadable document, so they are complementary, not a substitute.
  Not pre-empted by this spec.
- **S3 versioning on the user-space bucket.** It would make this recoverable generically and is
  deferred by decision. This spec neither depends on it nor blocks it.
- **A user-facing "reset my saved queries" control.** A destructive affordance offered to a user
  who cannot inspect the document is worse than automatic quarantine.
- **Granting the portal role `DeleteObject` under `user_settings/`.** See Rejected Alternatives.
- **Any other `user_settings/` document.** `shared-connections.json` and `notifications.json` are
  written by Lambdas under ETag CAS and are read-only in the browser; the data-quality documents
  are read-only too. `writeJsonDocument` has exactly two callers and both are in scope here.
- **A Help & guides entry.** SPEC-074 documents shipped flows; this is an error path, not a flow.

---

## Functional Requirements

### FR-001: A newer schema is distinguished from an unparseable body

#### Description:

The write-path parser must report three outcomes, not two. A body that is valid JSON carrying a
recognised `version` field **greater than** the version this build writes is a *newer* document,
not a corrupt one. It is refused **without** quarantine, because overwriting it would downgrade a
document a newer client wrote — destroying data, which is the whole point of the spec.

#### Acceptance Criteria:

- [ ] A body that is not valid JSON is classified `unparseable`.
- [ ] A body that is valid JSON but not an object, or an object with no numeric `version`, is
      classified `unparseable`.
- [ ] A body with `version: 1` and a valid array field is classified readable and parses as today.
- [ ] A body with a numeric `version` greater than 1 is classified `newer`, **whatever else it
      contains** — including when its array field is missing or malformed.
- [ ] A `newer` body is never quarantined and never overwritten, on any write path.
- [ ] The display read continues to render the empty document for every non-readable outcome, and
      is still derived from the write parser so the two cannot disagree about validity.

### FR-002: An unparseable document is copied to a sibling key before anything overwrites it

#### Description:

On an `unparseable` outcome the write path copies the live object, server-side, to
`{username}/user_settings/{basename}.unreadable-{timestamp}.json` — same prefix, so the existing
`GetObject`/`PutObject` grants cover it and no IAM changes.

#### Acceptance Criteria:

- [ ] The quarantine key is the source key's basename with `.unreadable-{ISO-8601 basic UTC}.json`
      appended, under the same `user_settings/` prefix.
- [ ] The copy is a server-side `CopyObjectCommand` — the unreadable bytes are never read into the
      browser, so an arbitrarily large document costs no memory and no second `GetObject`.
- [ ] The quarantine key is unique per event, so a later event cannot overwrite an earlier
      quarantine.
- [ ] `lib/s3Json.ts` issues the command itself and imports nothing from `features/` — the
      SPEC-155 layering rule holds, and no `eslint` exemption is added.
- [ ] Both key segments are app-generated (a catalog-safe username, a fixed basename, a generated
      timestamp), so the `CopySource` needs no percent-encoding; a test pins the rendered value.

### FR-003: The overwrite happens only if the quarantine copy succeeded

#### Description:

The copy is a precondition, not a courtesy. If it fails for any reason, the write is refused
exactly as it is today — a failed quarantine must never become a silent overwrite.

#### Acceptance Criteria:

- [ ] A successful copy is followed by the fresh document being written, and the operation
      reports success.
- [ ] A failed copy leaves the original object byte-identical, issues **no** `PutObject`, and
      returns a failure.
- [ ] The refusal after a failed copy is distinguishable in its `code` from the refusal for a
      `newer` document, so the two can be worded differently.
- [ ] Quarantine runs at most once per write operation — a retry of the same operation does not
      produce a second quarantine object for a document already replaced.

### FR-004: The user is told which of the three things happened

#### Description:

All three outcomes reach the screen through `toUserMessage`, and each says what became of the
user's data. Wording lives in `lib/errorMessages.ts` and raw parser text is never rendered
(SPEC-106).

#### Acceptance Criteria:

- [ ] **Recovered:** the save succeeds and the user is told the previous file could not be read,
      that a copy was kept, and that their earlier saved queries are not in the new list.
- [ ] **Newer document:** the save is refused and the user is told to reload the page — the
      actionable cause is a stale tab, not corruption.
- [ ] **Quarantine failed:** the save is refused and the user is told nothing was changed.
- [ ] None of the three messages is the generic fallback, and none contains raw JSON, a parser
      message, or an S3 error string.
- [ ] Each message is reachable from the Query screen — asserted by rendering the flow, not by
      calling `toUserMessage` directly, which proves only that a mapping exists.
- [ ] Query-history writes stay silent per the existing `logBackgroundFailure` calibration; the
      history document is still quarantined and still recovers, without a toast per query run.

### FR-005: No IAM change, and the accepted consequences are recorded

#### Description:

The design is chosen so the portal role's policy is untouched. The consequences that follow from
that are stated rather than discovered later.

#### Acceptance Criteria:

- [ ] No `.tftpl` under `infra/modules/` is modified by this spec.
- [ ] A test asserts the quarantine key falls under the user's own prefix — the boundary the
      existing grants are scoped to.
- [ ] It is recorded that quarantine objects are themselves covered by the `user_settings/`
      `DeleteObject` deny, so neither the app nor the user can ever remove one, and only an
      administrator with console access can; and that this is accepted, because one object per
      genuine corruption event on a should-never-happen path is a smaller problem than the
      evidence being destroyed.
- [ ] It is recorded that a repeat event requires a second independent corruption — the document
      written after a quarantine is one the app serialized itself — so accumulation is not a loop.

---

## Data Model

```ts
// apps/portal/src/lib/s3Json.ts

/**
 * Why a document could not be used, when it could not be used.
 * `newer` is NOT a failure of the document — it is a failure of THIS build to be
 * current, and it is the one outcome that must never be overwritten.
 */
export type UnusableReason = 'unparseable' | 'newer';

/** What a write-path parser returns instead of a bare success/failure. */
export type DocumentParse<T> = {readable: true; value: T} | {readable: false; reason: UnusableReason};
```

## API / Interface Contract

```ts
// apps/portal/src/lib/s3Json.ts

/**
 * Copy an unreadable document aside so the caller may then overwrite it.
 * Server-side CopyObject — the bytes never enter the browser.
 * Returns the quarantine key on success; never throws.
 */
export function quarantineDocument(opts: {
  bucket: string;
  key: string;
  /** Injected for determinism in tests; defaults to the current time. */
  now?: Date;
}): Promise<ServiceResult<{quarantineKey: string}>>;
```

```ts
// The write path, in both services. Shape, not literal code:
//
//   parse the live body
//     readable → apply the change, write            (unchanged)
//     newer    → refuse: 'SavedQueriesNewerVersion' (no copy, no write)
//     unparseable →
//       quarantineDocument(...)
//         failed  → refuse: 'SavedQueriesQuarantineFailed'  (no write)
//         copied  → write the fresh document, and report the recovery
```

Error codes added to `lib/errorMessages.ts` — the existing `SavedQueriesUnreadable` /
`QueryHistoryUnreadable` pair is **replaced**, because after this spec an unreadable document is
no longer a terminal state:

| Code | Outcome |
|---|---|
| `SavedQueriesRecovered` / `QueryHistoryRecovered` | saved; previous file quarantined |
| `SavedQueriesNewerVersion` / `QueryHistoryNewerVersion` | refused; reload the page |
| `SavedQueriesQuarantineFailed` / `QueryHistoryQuarantineFailed` | refused; nothing changed |

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── s3Json.ts                  # + quarantineDocument, DocumentParse, UnusableReason
│   ├── s3Json.test.ts             # NEW — the primitive's own suite
│   └── errorMessages.ts           # + six codes, - the two this replaces
└── features/query/
    ├── savedQueries.service.ts    # three-way parse + quarantine-then-proceed
    ├── queryHistory.service.ts    # same
    ├── queryServices.test.ts      # + the three outcomes, per document
    ├── QueryWorkspace.tsx         # recovery + refusal reach the screen
    └── QueryWorkspace.test.tsx    # + the rendered outcomes
```

## Implementation Phases

**Phase 1 — The three-way parse.** Introduce `DocumentParse` / `UnusableReason` and reclassify
both documents' write parsers, keeping the display parsers derived. No quarantine yet: `newer` and
`unparseable` both still refuse, so this phase is a pure narrowing with no behaviour change beyond
`newer` getting its own code. Covers FR-001.

**Phase 2 — The quarantine primitive.** `quarantineDocument` in `lib/s3Json.ts`, with its own test
file covering the key shape, the `CopySource` rendering, the same-prefix boundary, and the failure
path. Not yet called by anything. Covers FR-002 and FR-005.

**Phase 3 — Wire it up and surface it.** Quarantine-then-proceed in both write paths, the six
codes in `errorMessages.ts`, and the outcomes rendered on the Query screen. Covers FR-003 and
FR-004.

---

## Rejected Alternatives

**Grant the portal role `DeleteObject` under `user_settings/` and delete the bad document.**
Rejected. The deny is a standing safety property of the folder, and trading it away for an
implementation convenience is the trade SPEC-157 declined when it made the refresh lock release by
overwriting rather than deleting. Quarantine reaches the same outcome without touching the policy —
and deleting would destroy the only copy of whatever the user actually had.

**Leave the refusal permanent and document "Contact the Administrator".** Rejected: that is the
bug. It also puts an operator in the loop for a fault the app can resolve itself, against a bucket
the operator has no tooling for.

**Overwrite on the second attempt ("click Save again to replace").** Rejected. It reintroduces the
exact data loss this arc closed, behind a confirmation the user cannot make an informed decision
about — they cannot see the document, so they cannot know what they are agreeing to discard.

**Repair the document in place (salvage the parseable entries).** Rejected as a guess. A body we
could not parse gives no principled way to decide which fragments are genuine, and a partial
salvage presented as a recovered library is a quieter version of the original bug.

**Write the quarantine copy from the bytes already in memory.** Rejected in favour of server-side
`CopyObject`. It would mean carrying an unbounded, untrusted body out through the parse contract —
the same "attacker-controlled value in a field" shape `dlq_drain` caps and serialises deliberately
— and it costs a second `GetObject`.

**A fixed quarantine key, overwritten each time.** Rejected. It bounds accumulation at one object
per document, but does it by silently overwriting evidence, which is the behaviour this whole arc
exists to stop.
