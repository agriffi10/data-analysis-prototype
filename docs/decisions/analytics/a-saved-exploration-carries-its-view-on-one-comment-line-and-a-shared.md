---
type: Decision
title: "A saved exploration carries its view on one comment line, and a shared space's is held (SPEC-247)"
description: "**A saved view is trusted by where its FILE was listed from, never by the database it names.** From a shared space's `saved_queries/`, which any member writes, it opens held, unlinked, and without URL transformers or pattern-matching Colors rules; the hold is read fail-closed. Its payload is read strictly and its SQL is never parsed — the checksum detects an edit, it is not a signature."
---

**The view rides inside the `.sql` file, on its last line, and that is the whole format.** A Data
Explorer save writes the SQL that ran, then `-- dataquarry-view:v1:<checksum>:<payload>` — a comment,
so the file still runs unchanged in Query and in Athena, and still one object, so `docs/decisions/storage/`'s
sidecar rule and SPEC-183's one-`PutObject` guard both stand. The payload is base64url over UTF-8
JSON: no quote, semicolon, comment terminator or newline for either lexer to trip on. The format
lives in `lib/savedViewLine.ts` and knows nothing of the Explorer's types, so Query's splitter test
can build a real body. **Only the last non-blank line is read**: the SQL above can hold a line that
starts like the marker, inside a multi-line literal, and a first-match parser misreads this build's
own save. A marker line anywhere else means text was added after it, which is an edit.

**The SQL is never parsed; the view is what reopens.** The checksum — FNV-1a over the SQL with the
byte-order mark, CRLF and trailing whitespace normalised away — detects an edit made in good faith,
so a file changed in Query is refused with **Open in Query** rather than half-restored. It is not a
signature: whoever can write the file can write a matching line. So the payload is read
**strictly** — it must equal what the tab store's own normalisers make of it, hold no key at any
level this build does not declare (the normalisers pass unknown keys through by reference, so the
comparison alone cannot see one), keep column widths to the whole pixels the resize handle stores,
and render within Athena's limit — and one this build would have to repair is refused whole. A file
larger than Athena's limit is refused before it is read: this build never writes one, and size alone
(tens of thousands of Colors rules, which survive the strip) stalls a page on every render. Inside
that bound a crafted file can still carry a few thousand rules, at well under a second a page; that
is accepted. The store's lenient read
of `sessionStorage` is untouched; the two answer different questions (keep a session's tabs; trust a
file). `ExplorationQuery` and `ExplorationPresentation` are therefore a FILE FORMAT now: changing
either needs a reader for the old shape or a new line version, not a session reset. The first such
reader is the retired view choice's, in [the table-only entry](the-explorer-shows-a-table-and-nothing-else-and-a-saved-view-still.md).

**Where the FILE came from decides how much of it is trusted — never the database it names.** Only
the owner writes a personal `saved_queries/`, and file sends land in a separate inbox, so a view from
there restores whole, runs, and stays linked. Any member writes a shared one, and a view's expression
is raw SQL (the bar passes it verbatim), its URL transformer turns cell values into links to wherever
the author points, and a `regex`, `like` or `ilike` Colors rule compiles the author's pattern into a
backtracking expression — `like`'s `%` runs collapse, but `%` separated by other characters still
nest, and each added `%a` multiplies the work, so an 18-character pattern stalls a tab for seconds on
one 40-character cell (re-measure by timing `likeExpression` in `formatting.ts` on `%a…%b`). So a view from a shared folder opens **held** (rendered, shown in Generated SQL,
not started, no cached rows under it), **stripped** of those transformers and rules with a note
counting them (a gradient rule stays: it shades by number and never runs its operator), and
**unlinked**, so a save cannot silently overwrite the author's version for every
member. Keying on the view's database instead would let a member drop a file over the victim's own
database and have it run unasked. The folder is judged by BUCKET, not by space id, because a shared
space's id is its name and nothing reserves `personal`. **Accepted residual:** a file copied into the
user's own `saved_queries/` (file operations allow that destination) or re-uploaded there is fully
trusted — copying it is the act of trusting it, as copying a script one then runs is (user decision,
2026-09-26). The hold is `ExplorationTab.awaitingRun`, persisted so a reload does
not run it, and read **fail-closed**: a malformed value is a hold with no note, never absent — the
saved-query link beside it drops a bad value, and here dropping is the direction that runs a
statement. **Run** releases it; so does an `apply` that changes the query, in the same update.

**A space the list lacks is refused only after a connections read that settles after the open,** as
a deep link's is. The trap: `useSpaceLinkPending` re-arms by setting its own state during render, so
in the render that first sees a new request it still answers for the previous one. The deep link
only derives a value from it; this flow ACTS on it, and acting in that render refused a space whose
read had not been asked for. The open settles one render later, once the wait is armed.

**Rejected.** A sidecar (`docs/decisions/storage/`); reading filters back out of the SQL (SPEC-243); restoring a
`sql`-source tab's view, which would re-run a statement taken from a file; stripping only `regex`;
a linear-time LIKE matcher, which is the real fix for that pathology and a larger one than this
spec; listing only files that carry a view, which reads every body; a signature, which the
personal/shared split makes unnecessary.

## History

### 2026-09-25

- **Settled:** SPEC-247.
