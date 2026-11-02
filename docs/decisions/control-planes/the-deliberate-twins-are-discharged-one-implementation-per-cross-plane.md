---
type: Decision
title: "The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)"
description: "**`cpcommon` owns the algorithm; a domain layer owns its wording.** Do **NOT** merge the domain layers wholesale."
---

Four helpers were duplicated across the Lambda layers *on purpose*, each with a comment saying so
and naming the condition under which the copies should converge. Those conditions had all expired,
and in two cases the drift the comments warned about had already happened — `dqcommon`'s CAS twin
handled a racing 409 that `casio`'s did not and used a different retry cap, and `cpcommon/auth.py`'s
"one JWKS-verification path for the whole repo" docstring was false because `notifications-writer`
could not import it.

**Decided: `cpcommon` owns the algorithm; a domain layer owns its wording and its constants.** The
conditional-write CAS loop (FR-001), the failure-message resolver (FR-002), the results-location
builder (FR-003), the JWKS path (FR-004), the SQS envelope parser and the Athena DDL runner (FR-005)
each exist once. The domain message modules keep only their **tables**: `cpcommon.messages.Resolver`
gained `prefix`, `access_denied` and `fallback` templates and an opt-in `blank_unfilled`, so a plane
expresses its whole sentence as configuration. `Resolver.__init__` refusing a re-defined base code
is what had kept two planes out — both re-definitions were byte-identical restatements, so deleting
them was a provable no-op rather than a wording change.

**The blocker was `cpcommon.config` resolving eagerly** (FR-004). Six `_require`d environment
variables at *import* meant a function that set three could not import `cpcommon.auth` at all, so it
grew its own verifier. That is the general shape worth carrying: **an eager module-level requirement
does not merely inconvenience an importer, it forces a fork.** Config resolves lazily now and still
fails loudly at first use.

**Byte-identity was measured, not asserted.** Every reason in all three planes was rendered under
every argument combination against both implementations — 2214 messages per side. Exactly one row
differed: `malformed_event` under table-share, a shared base code that plane never declared, which
used to fall to `tscommon`'s unknown-code fallback and now reads what it means. It is unreachable
there today (table-share's only `parse_sqs_request` call raises `unauthorized`), and it is pinned by
a test rather than left to be rediscovered in an inbox. **Reading three implementations side by side
would not have found it** — that is the argument for rendering both and diffing, on any future
consolidation.

**Do NOT** read this as licence to merge the domain layers into `cpcommon`. The packages stay; only
genuinely cross-plane helpers moved.

> **The FENCE stands; its mechanism is superseded by SPEC-214.** There is no attach step and no
> matrix row to change — the image copies every `lambdas/*-common/` package to `/opt/python`, so a
> move between packages is an import change and nothing else. That makes the separation a code
> decision with no packaging left to enforce it, which is a reason to hold the fence more firmly
> rather than less. Full entry: *A guard is retired by proving its replacement, then deleting* in
> [`docs/decisions/infrastructure/`](../infrastructure/).

## History

### 2026-08-07

- **Settled:** SPEC-156.
