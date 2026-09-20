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
  alone**, which also ends the `sales.sales.orders` a qualified insert produced there.
- **A name SQL would misread arrives quoted, in Trino statements only.** `lib/sql.ts` gained
  `TRINO_RESERVED_KEYWORDS` (83 words) and `quoteIdentifierIfNeeded`. Inside the user's own open
  quote the insert is the bare name with its quotes doubled, closed only when nothing closes it
  already. `label` is never quoted, so filtering and reading are unchanged.
- **The record matches.** The register entry *Suggestions follow the statement, and a Trino insert is
  quoted where the name needs it* in `docs/decisions/analytics.md`, one clause added to that file's
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
- **Inside an open quote after a database name** — `from sales."` — nothing is offered, FR-005's
  criterion being flat that no table is suggested there. A narrower list, never a wrong insert.

## What changed from earlier specs?

- **SPEC-065's bare insert holds only outside a Trino statement now.** Its acceptance criterion and
  its `SqlCompletion` contract line carry superseded markers. The Hive DDL, a CTAS included, keeps
  the bare name: `CREATE TABLE … AS SELECT` is Hive at its head and Trino in its body, and the bare
  insert is the safe side of that fence.
- **SPEC-077's "schema-wide" autocomplete is narrowed on its column half**, tables staying
  schema-wide. `ARCS.md`'s existing SPEC-077 marker gained a second one saying so, since it was
  itself over-claiming.
- **`buildSqlCompletions` keeps its signature and its exact output**, reimplemented over an internal
  descriptor that carries the identifier **parts** rather than a joined string — joining first and
  splitting later would mangle a name holding a dot.

## Verification

- Formatter, both linters, both suites, mypy, `npm run build` and `validate_docs.py` green locally
  by exit code, plus what `ci.yml` runs on the branch. The worktree's install had no local `tsc`
  shim, which `check-compiler-major.mjs` refused rather than typechecking against the root's
  TypeScript 6; `npm ci` fixed it, and the same refusal is why a green build here means anything.
- **A 14-mutation battery, bracketed by baseline runs**, each plant seen red and reverted, with the
  source digest compared before and after. Four survived the first pass and were real blind spots
  rather than dead rules — a wrong database still resolving through a right table name, a
  parenthesised relation, a column-alias list's comma, and a qualifier read without its dot — each
  closed with a discriminating assertion and then re-planted.
- **The Monaco premises were read from the installed 0.56.0, not from the vendor's prose.** The `sql`
  language module exports only a Monarch tokenizer and a language configuration, registering no
  completion provider; its `autoClosingPairs` inserts the closing `"`, which is why the live check
  names the cursor-before-a-closing-quote gesture rather than the end-of-an-open-quote one. Beware
  `monaco.d.ts` on `wordBasedSuggestions`: it says "Defaults to true" above a union with no `true`
  member, and the registered default is `offWithInlineSuggestions`.
- **Live check: owed until run.** The steps are the three SPEC-244 rows in `docs/testing/e2e.md`
  §4.3. Nothing in them needs a second account or the operator, so it is an ordinary signed-in pass
  rather than an `owed.md` row.
