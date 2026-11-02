# Completed Spec — SPEC-244: Autocomplete Offers the Columns of the Tables the Statement Names

## What was completed?

- **Column suggestions follow the statement at the cursor.** `scopeAt` in
  `features/query/sqlCompletions.ts` resolves the tables that statement's `FROM` and `JOIN` name,
  and the popup then offers only their columns — with every accessible table and view still listed
  beside them, because a user adding a `JOIN` needs those. A column several of them declare is one
  suggestion whose detail names each, `<type> · <database>.<table>` joined by `; `. When nothing
  resolves, the whole catalog comes back, which is what a statement whose `FROM` is not typed yet
  deserves. The statement is the one `resolveRunStatements` would run with no selection, so
  **Run Statement** and the popup never disagree about which statement the cursor is in.
- **`query.sql.ts` gained four exports over the tokenizer it already had:**
  `sqlTableReferences` (the references and their aliases, with `CLAUSE_WORDS`), `isTrinoStatement`,
  `openQuoteStart` and `sqlQualifierBefore`. `splitSqlStatements` and `resolveRunStatements` are
  byte-identical to their previous text.
- **A dot opens the popup, and resolves what precedes it.** The provider declares
  `triggerCharacters: ['.']`, without which the reported gesture — an alias and a dot — showed
  nothing, Monaco treating `.` as a word separator. An alias wins over a table name and a table name
  over a database name; a database name offers that database's tables inserted as the **table part
  alone**, which also ends the `sales.sales.orders` a qualified insert produced there. A *two*-part
  qualifier that resolves to nothing (`SELECT sales.orders.`) still falls through to the whole
  catalog and can still produce a doubled name; FR-004 specifies that fall-through, so only the
  one-part gesture is fixed.
- **A name SQL would misread arrives quoted, where quoting is correct.** `lib/sql.ts` gained
  `quoteIdentifierIfNeeded` over `ATHENA_RESERVED_KEYWORDS` — **Athena's** published `SELECT` list
  unioned with Trino's 83, because Trino's omits `EXECUTE`, `FIRST`, `LAST` and `OF` and quoting
  from it alone left `first` and `last` inserted bare. Inside the user's own open quote the insert
  is the bare name with its quotes doubled, closed only when nothing closes it already. `label` is
  never quoted, so filtering and reading are unchanged.
- **The record matches.** The register entry *Suggestions follow the statement, and a Trino insert is
  quoted where the name needs it* in `docs/decisions/analytics/`, one clause added to that file's
  Fences identifier-escaper bullet, two component-inventory rows, the live check in
  `docs/testing/e2e.md` §4.3, and superseded markers in `docs/design/design-system.md`,
  `docs/specs/SPEC-065-…` (its acceptance criterion and its contract line) and `docs/specs/ARCS.md`.
- **Nothing user-facing needs a Help guide.** The Help has no autocomplete guide today and the spec
  puts adding one out of scope, so the sweep concludes with nothing to add.

### Deliberate deviations

- **Two exports beyond the spec's API contract**, `openQuoteStart` and `sqlQualifierBefore`, added to
  the contract in the same commit. Both are scans FR-004 and FR-005 describe in prose; they live in
  `query.sql.ts` because the quote rules and the tokenizer that knows what an identifier is are
  there, and a second copy in `sqlCompletions.ts` is the fork the analytics Fences warn about.
- **`skipQuoted` became a one-line wrapper over a new `scanQuoted`.** Forced, not chosen: the old
  return value is `buffer.length` for **both** an unterminated quote and one closing on the final
  character, so it cannot tell `SELECT "abc` from `SELECT "abc"`, and a completion inside an open
  quote would have overwritten a finished identifier. `scanQuoted` is the same body with its two
  exits reporting `terminated`; every existing caller keeps identical semantics.
- **The open-quote branch is skipped when the quote is on an earlier line.** Monaco discards a
  suggestion whose range starts on another line, so a stray unclosed `"` earlier in a multi-line
  statement would have cost the user every suggestion. It falls through to the plain word gesture
  instead.
- **FR-004's fourth acceptance criterion was a spec defect**, its buffer `from s.a b join s.b c`
  containing no `b.` for the cursor to sit after. Pinned to `select b. from s.a b join s.b c`,
  cursor at offset 9, keeping the alias/table-name collision the criterion exists to test.
- **Inside an open quote after a database name** — `from sales."` or `from "my space"."` — nothing
  is offered, FR-005's criterion being flat that no table is suggested there. The filter is by kind,
  so it also excludes the one-part names that branch produces, which *would* fit inside one pair of
  quotes. A narrower list, never a wrong insert.
- **A CTAS is now quoted, reversing this spec's own exclusion** (Andrew's call, 2026-09-20). It was
  the one exclusion whose failure was silent rather than loud, and both halves of the reasoning for
  it turned out false when measured. The register entry carries it.

## What changed from earlier specs?

- **SPEC-065's bare insert holds only where `isTrinoStatement` does not admit the statement.** Its
  acceptance criterion and its `SqlCompletion` contract line carry superseded markers. The Hive DDL
  keeps the bare name, because a double-quoted name is an error there; a CTAS does not, its whole
  statement being Trino.
- **SPEC-077's "schema-wide" autocomplete is narrowed on its column half**, tables staying
  schema-wide. `ARCS.md`'s existing SPEC-077 marker gained a second one saying so, since it was
  itself over-claiming.
- **SPEC-065's whole-catalogue builder is deleted**, the provider having been its only caller once
  the provider started building from the shared descriptor directly. Its three assertions moved onto
  the provider, where they exercise the live path instead of a projection nothing called. Descriptors
  now carry the identifier **parts** rather than a joined string, since joining first and splitting
  later would mangle a name holding a dot.

## Verification

- Formatter, both linters, both suites, mypy, `npm run build` and `validate_docs.py` green locally
  by exit code, plus what `ci.yml` runs on the branch. The worktree's install had no local `tsc`
  shim, which `check-compiler-major.mjs` refused rather than typechecking against the root's
  TypeScript 6; `npm ci` fixed it, and the same refusal is why a green build here means anything.
- **Mutation batteries, bracketed by baseline runs**, each plant seen red and reverted, with the
  source digest compared before and after. The first pass ran 14 plants and four survived, each a
  real blind spot rather than a dead rule — a wrong database still resolving through a right table
  name elsewhere, a parenthesised relation, a column-alias list's comma, and a qualifier read
  without its dot. Later passes added the Athena-only words, the case-folding half of the
  bare-identifier rule, and the `)` that closes a `FROM` list. One survivor is left deliberately:
  swapping the tokenizer's word list for Trino's changes no reachable behaviour, and the docstring
  says so rather than an assertion pinning an arbitrary choice.
- **The Monaco premises were read from the installed 0.56.0, not from the vendor's prose.** The `sql`
  language module exports only a Monarch tokenizer and a language configuration, registering no
  completion provider; its `autoClosingPairs` inserts the closing `"`, which is why the live check
  names the cursor-before-a-closing-quote gesture rather than the end-of-an-open-quote one. Beware
  `monaco.d.ts` on `wordBasedSuggestions`: it says "Defaults to true" above a union with no `true`
  member, and the registered default is `offWithInlineSuggestions`.
- **Live check: ran 2026-09-21, all four rows passed** (`docs/testing/sessions.md`, 2026-09-21
  evening). The steps are the four SPEC-244 rows in `docs/testing/e2e.md` §4.3.
- **One premise was settled from documentation, and has since been run.** The CTAS row passed
  against real Athena: the accepted column arrived as `"last name"` and the CTAS succeeded. That a CTAS
  takes Trino quoting *throughout* — head included — comes from AWS documenting its body as DML and
  its head taking Trino's `WITH (…)` property syntax. Both review frames found a defect of exactly
  this class in this change (a reserved-word list taken from the wrong vendor, and a "the failure
  would be loud" claim that was argued rather than measured), so the fourth live-check row exists to
  execute this one against real Athena instead of adding a third reading frame over it.
- **Known limits, each pinned by a test rather than claimed away:** every `FROM` keyword counts, so
  `EXTRACT(YEAR FROM order_date)` yields a reference that resolves to nothing; a three-part
  `catalog.schema.table` reads as its first two and falls back to the whole catalog; and suggestions
  still appear inside an unclosed `'` string literal, which is SPEC-065 behaviour this spec did not
  change.
