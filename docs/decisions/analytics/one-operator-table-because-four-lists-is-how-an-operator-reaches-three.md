---
type: Decision
title: "One operator table, because four lists is how an operator reaches three of them (SPEC-238)"
description: "**A blank CSV field is `''`, not NULL, so the null tests never reach it** — every CSV table is all-string under OpenCSVSerde, and the grid draws the two apart as `NULL` and `(empty)` because they are different. **Is empty** asks for both; it is also the only Colors operator that matches a NULL cell. **Every filter operator is one row of `FILTER_OPERATOR_SPECS`**, and the labels, the offer order, which field an operator reads, which column types offer it, how its value is rendered and the stored-document check all derive from it — a new operator that reaches some consumers and not others is the failure this shape exists to prevent, and the one that failed SILENTLY was the stored-document check, which discarded a whole session's tabs over an operator it had not heard of. A membership test over that table uses **`Object.hasOwn`, never `in`**, which admits `toString`. A rendered statement is refused before it starts when it exceeds Athena's **262,144-byte** `QueryString` limit, measured in UTF-8 bytes. A list may hold `''` and name NULL (`includesNull`, only where the table's `listsNull` says), and `canonical` must compare it, or ticking NULL is an apply that changes nothing."
---

Four testers asked the Data Explorer's column menu to match part of a value, several values at once,
or a blank cell. Two of those reports had one cause: a table built from CSV files stores a blank
field as an empty string, so `IS NULL` correctly matches nothing and the cells the grid labels
`(empty)` were unreachable by name. The spec adds **contains, does not contain, starts with, ends
with, is one of, is not one of, is empty, is not empty** to the filters, **is empty / is not empty**
to the Colors rules, and a refusal for a statement Athena would reject for its length.

**The operators were enumerated in four places and each miss failed differently.** A map of operator
symbols in the renderer that `Exclude`d the two null tests, so a new member rendered `undefined`
into the middle of a statement and sent it to `StartQueryExecution`; an offer-order array and a
label `Record` in the pure edits; and a plain `Set<string>` in the stored-document check — the one
that failed **silently**, discarding a session's tabs whole rather than reporting anything. The fix
is structural rather than four more entries: one `FILTER_OPERATOR_SPECS` table keyed by the union,
carrying each operator's label, which field it reads, which column types offer it and whether the
column's `valueKind` decides how its value is rendered. Everything else derives, and the renderer
became a second `Record` over the whole union, so a missing entry is a **compile error** in both.
The one derivation a type cannot check — the stored-document gate — is guarded by a test that
restores a tab carrying every operator, asserting the population size first so it cannot pass
vacuously.

**`Object.hasOwn`, never `in`, for the membership test.** `in` walks the prototype chain, so
`'toString'`, `'constructor'` and `'__proto__'` all pass it. Wired through the check and the
renderer, a stored tab carrying `operator: 'toString'` rendered `WHERE [object Object]` — the exact
failure the check exists to prevent, reintroduced by the structural fix itself. Found at the plan
gate by a reviewer that built it and ran it.

**Case is folded by Trino on both sides** — `lower(col) LIKE lower(pattern) ESCAPE '\'` — rather
than by lowering the value in the browser, because JavaScript's case rules and Trino's disagree on
some characters and lowering one side applies one rule to the pattern and the other to the column.
The pattern doubles every backslash, then escapes `%` and `_`, then adds the operator's own
wildcards, and `sqlLiteral` runs **last** over the finished pattern, so a quote can never leave the
literal. The four text operators quote their value whatever the column's type, which is why the
numeric refusal at both value inputs follows the **operator** and not the column: a rule keyed on
the column would refuse a `contains` the renderer accepts.

**A list is `values: string[]`, never a delimited `value`.** A delimiter is a character a cell can
hold, so splitting one back out makes some real values unfilterable, silently. The stored-document
check refuses a list holding a number, a `null`, an empty string or a line break, which is what lets
an edit pre-fill the one-value-per-line field line for line and get the same list back.
(**Superseded in part by SPEC-249, 2026-09-28:** a list may now hold the empty string and name NULL,
and the field carries both as boxes — see [the entry](a-columns-values-are-a-list-you-tick-and-a-list-may-hold-empty-and-null.md).) Rendering
de-duplicates and sorts by UTF-16 code unit, so two lists holding the same values are one statement
— which is the execution cache key, and therefore one bill rather than two. The **1,000**-value cap
is an input bound, not the query's limit: the real limit is Athena's statement length, measured
directly, because a thousand long values exceed it where a thousand short ones do not. That length
check counts UTF-8 **bytes**, since the API reference does not say which unit it means and a byte
count is never below a character count.

**Rejected:** raw `LIKE` / `NOT LIKE` operators and case-sensitive variants in the menu — those are
the expression bar's job, and the guide now points there for the conditions the menus genuinely
cannot say. **Not built:** reading blank CSV fields as NULL, which would change what existing tables
return; relabelling `(empty)`, which is accurate; a length check in the Query workspace, where the
user wrote the statement and Athena's own refusal is the honest report.

> **Superseded (SPEC-251, 2026-09-28) — the raw `LIKE` rejection ONLY.** The expression bar is gone,
> so its reason went with it: **is like** and **is not like** are filter operators now, with `%` and
> `_` as wildcards, capitals folded by Trino on both sides as here, and no escape character.
> Case-sensitive variants stay rejected, and the four text operators above stay literal. Everything
> else in this entry still stands; the full reasoning is [the SPEC-251 entry](a-filter-is-conditions-and-groups-built-by-pointing-and-the-expression.md).

**Is empty** asks for both `''` and NULL, and it is also the only Colors operator that matches a NULL cell; the grid draws the two apart as `NULL` and `(empty)`. A rendered statement is refused before it starts when it exceeds Athena's **262,144-byte** `QueryString` limit, measured in UTF-8 bytes. A list names NULL through `includesNull`, only where the table's `listsNull` says, and `canonical` must compare it, or ticking NULL is an apply that changes nothing.

## History

### 2026-09-28

- **Changed:** A list may hold the empty string and name NULL, and the typed field carries both as boxes.
- **Changed:** With the expression bar gone, **is like** and **is not like** became filter operators; case-sensitive variants stay rejected.

### 2026-09-20

- **Settled:** SPEC-238.
