---
type: Decision
title: "A filter is conditions and groups built by pointing, and the expression box is gone (SPEC-251)"
description: "**A filter is a tree: the top level is AND, OR lives in a group, and groups nest two deep.** An item of `query.filters` may be a `FilterGroup`, so code that walks it goes through `isFilterGroup` and never assumes a `ColumnFilter` — a walk that reads `.column` off every item compiles wherever the type is loose and misses the conditions inside groups. The column menu, **Filter by value…** and Order and filter edit a column's **top-level** conditions only; an edit that passes a filter through hands an untouched condition back as the stored object. A flat list renders byte for byte as before groups. The free-text `expression` is **read-only**: kept, rendered and removable, never written, since converting it needs a parser that drops what it missed."
---

**The box goes, and a builder takes its place (Andrew, 2026-09-28, on an outside review).** Users do
want OR and several conditions on one column, and until now the only way to say either was raw SQL
in the *Filter expression* box — which is Query's job. **Filter rows…** builds conditions and groups
by pointing, in a staged dialog whose Apply is one execution however much changed.

**The top level is AND, and OR lives in a group.** That was already the rule at the top level, so
every stored filter list is a valid filter as it stands and nothing migrates. It is also what keeps
the menus simple: a filter set from a column's menu always narrows, where a top level that could be
OR would make a menu gesture either widen the result or wrap the whole filter in a new group.
Groups nest two deep — a group, and one more level inside it — which says both
`(a or b) and (c or d)` and `(a and b) or (c and d)`; the stored-document gate holds the same bound,
and its depth counter was mutation-tested both ways after a four-deep fixture let an off-by-one
through that a three-deep one catches.

**The menus stop at the top level.** `setFilter` and `clearFilter` replace or remove a column's
top-level conditions and leave groups alone, because a condition inside an OR group means something
the menu cannot show. `filterOf` answers only for a column's single top-level condition, since a
single-filter surface showing one of two would edit it as the whole — and Order and filter re-sets
only the columns it shows a select for, since its old loop re-set every list filter through
`setFilter` and would have merged two conditions into one. The header's mark follows
`isFilteredAnywhere`, and Clear filter is refused, with its reason, when a column's conditions are
all grouped.

**An untouched condition is handed back as the stored object.** The builder keeps each row's stored
condition beside its draft and returns it whole unless the row changed, so a field the builder does
not show survives an edit elsewhere; SPEC-249's `includesNull` is the case in view. A changed row on
a column the result no longer lists keeps the stored `valueKind`, since a type lookup there falls
back to text and would quote a number. A list row's **Pick values** mounts SPEC-249's picker only
when pressed, because mounting is the billed listing, and passes it no narrowing, since the builder
cannot know until Apply which neighbours a row is ANDed with.

**A flat filter renders byte for byte as before.** Nothing is cached across a deploy — the execution
cache is in memory and so is the record of failed statements — so this is not about the cache; it
is the proof the change is additive, carried by the existing renderer tests' unchanged strings.

**`is like` / `is not like` fold capitals and have no escape character.** They sit beside four text
operators that ignore capitals, and switching `contains` to `is like` to add a wildcard should not
lose rows by case. The pattern goes through `sqlLiteral` alone, so `%` and `_` stay wildcards and no
pattern is one Athena refuses to parse; finding a literal `%` or `_` is what the literal operators
are for, and the hint under every pattern field says so. That matches the Colors rules'
"matches (% and _)", which has no escape character either. The hint rides on the operator table
(`hint`), so all three value inputs show it.

**A stored expression is kept, not converted.** Turning free SQL into conditions needs a parser,
and whatever it missed would vanish without a word. So `expression` stays in the model, renders as
it always did, and shows verbatim beneath the filter row with **Remove SQL condition** and, under
the `query` flag, **Open in Query**. Keeping the field's name means no stored document is rewritten and
the saved-view line stays at version 1. A saved view that USES a group is refused whole by a page
loaded before this change — never partly applied — and a flat one opens there as it always did.

**What moved to Query.** Comparing two columns, a function such as `TRY_CAST` — the guide's advice
for numbers in a CSV text column — and a pattern that minds capitals are SQL, and the guide that says so
is *Save an exploration as a query*, since **Open in Query** goes with the `query` flag and that
guide goes with it; *Filter and sort* stays flag-neutral. One row's picker is open at a time and
closes when its row stops being what was pressed for, since each remount is a billed listing.

**Rejected.** A top level that can be OR; groups nested without a bound; parsing a stored expression
into conditions; the menus editing conditions inside a group; an escape character for `is like`.

An item of `query.filters` may be a `FilterGroup`, so code that walks it goes through `isFilterGroup` and never assumes a `ColumnFilter`: a walk that reads `.column` off every item compiles wherever the type is loose and misses the conditions inside groups.

## History

### 2026-09-28

- **Settled:** SPEC-251.
- **Changed:** The *Filter expression* box was replaced by **Filter rows…**; a stored expression stays read-only.
