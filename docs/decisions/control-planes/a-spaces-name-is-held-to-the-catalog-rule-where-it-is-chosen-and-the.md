---
type: Decision
title: "A space's NAME is held to the catalog rule where it is CHOSEN, and the refusal is create-only (2026-09-22)"
description: "**A shared space's NAME is held to the catalog rule where it is CHOSEN, and was held nowhere before.** One string is four things — a Glue database, an S3 prefix segment, a principal tag VALUE the portal role interpolates into a resource ARN, and, raw and deliberately, the table-build and table-share `MessageGroupId` — and every reader was written against `CATALOG_IDENTIFIER_RE` while only the browser's create dialog applied it. A live check made `live0922 odd` through the API: it provisions, uploads and queries, and **Create table and Table share are permanently impossible in it**, because SQS's key grammar admits no space. The create path now refuses `CreateNameUnusable` in the dialog's own words, and **the refusal is create-only on purpose** — a space already carrying such a name has to stay deletable, or its membership slot is stranded with it. The downstream refusals stay rather than being made redundant."
---

Found by a live check that set out to settle something else: whether the app's DDL quoting survives
a shared space whose name is not catalog-safe. It does. `live0922 odd` — a space character, chosen
because it is what STS's session-tag grammar admits where a backtick would have broken every
credential call the account makes — was created through a signed-in
`POST /v1/enqueue/shared-space`, Glue accepted the database name, files uploaded into it, Athena
answered, and `CREATE EXTERNAL TABLE`, `DROP TABLE` and `CREATE OR REPLACE VIEW` all ran under the
app's own quoting with the unquoted form refused `QuerySyntaxError` as the control.

**What it found instead is that the space can never build a table or share one.**
`apicommon/fifo.py`'s `_group_table_build` uses the **raw** database name as the SQS
`MessageGroupId`, and `_group_table_share` concatenates the same raw name as `{database}.{table}`.
SQS's key grammar is printable ASCII with no space, so `fifo._checked` refuses both derivations
before the send and `POST /v1/enqueue/table-build` comes back `InvalidRequest` every time. Two
features are permanently unusable in a space the create path was happy to make, and the owner is
told about a queue key.

**The missing check was upstream, and it is the only place one closes all four readers at once.** A
space name is a Glue database, an S3 prefix segment, a principal tag value the portal role
interpolates into a resource ARN, and the two group ids — four consumers all written against
`cpcommon.config.CATALOG_IDENTIFIER_RE`, none of which applied it. Nothing server-side did:
`apicommon.bounds` bounds the field's LENGTH and its budget sentence cited "the catalog identifier
rule a creatable space name already answers to", which was the premise rather than a check, and
`shared-space-validate` applied no format rule at all. `shared-space-common/auth.create_refusal`
now does, returning `CreateNameUnusable` — a RETURN VALUE, because a raise in that validator is
caught by a state that seeds a null actor and the notifier then tells nobody — and the sentence
ends with `cpcommon.config.CATALOG_IDENTIFIER_RULE`, the same string the browser's create dialog
shows under the field, held equal to the TypeScript by
`lambdas/test_catalog_identifier_browser_mirror.py` so one rule is not described two ways.

**Hashing the two group ids was the rejected alternative.** It would have made table build and
table share work for any name in one line each, and `_group_table_build`'s docstring argues for raw
deliberately, so the reasoning was there to replace. It was rejected because it fixes two of the
four readers and hides the other two: the name would still be a principal tag value, still a Glue
database, and still the thing `apicommon.memberships._from_index` refuses — where an unsafe name
fails the WHOLE index rather than the entry, so one such space costs its member every credential
the moment `MEMBERSHIP_SOURCE` becomes `index`. It would also move the group id of every existing
space at once, so messages in flight across the deploy would be ordered under two different keys.
A name the rule does not admit is better refused at the door than made to work halfway down.

**The refusal is create-only, and that is the decision, not an omission.** `live0922 odd` exists in
production, is active, and holds one of its owner's ten membership slots. Applying the rule to
every action would make the one verb that can recover the slot — the delete — the one verb the name
refuses, and the same for leave and forget. A test drives a delete of that exact name through the
validator so the narrowing cannot be tidied away later.

**Nothing downstream was relaxed.** `fifo._checked` stays, because it turns an opaque SQS failure
into a named one and it is the only thing standing in front of a space named before this refusal;
so does the index source's check, which is still the last point before a name becomes an
entitlement. `_group_table_build` previously argued from the premise that the rule was applied
somewhere and `_from_index` from the premise that it was applied nowhere; both now say where it is
applied and what still gets past it.

## History

### 2026-09-22

- **Settled:** entered the register.
