---
type: Decision
title: "A report may carry the user's ROWS, and it is bounded by the size it is read through (SPEC-240)"
description: "**A durable artefact may carry the user's ROWS; nothing that fans out may.** A data-quality report holds up to five duplicated rows cell by cell — the first figure in this fleet that is the user's data rather than a measurement of it. The notification, the runs-index row and every log line still carry counts and keys only, held by an EQUALITY between two runs of the same report with and without samples, never a substring search for the fixture's values. And **the writer's cap is the only cap, because the reader's is a refusal**: above `apicommon.s3_config.MAX_DOCUMENT_BYTES` the page cannot open the report at all, so every other finding is lost with the part that made it big — assemble-report measures what it is about to write, DROPS the samples, then shortens the per-file lists from their ends, longest first, each counting what it left out, and never truncates a figure or an entry. The re-declared `DQ_REPORT_MAX_BYTES` is held EQUAL to that number, not under it, by a fleet-level test, since the two planes may not import each other. A third cap sits between them and is a different question: `csv`'s 131,072-character field limit, which one samples cell can exceed — raised from what the statement can return, **never below the reader's default**, and restored after the one read."
---

Every figure this fleet produces until now is a MEASUREMENT of the user's data — a count, a ratio, a
file name. A data-quality report now carries up to `DQ_DUPLICATE_SAMPLE` (5) of the duplicated rows
themselves, cell by cell, because the count alone could not answer the question a tester actually
asked: *which* rows repeat. That crosses a line the rest of the fleet does not, and three
consequences follow that are easy to miss one at a time.

**The report object is the only place those cells may appear.** A report is written to the
requester's own prefix and read back by them through a signed request. A notification fans out, a
runs-index row sits on a dashboard, and a log line is retained and readable by whoever can see the
plane — so none of them may carry a cell. `dq_assemble_report` holds the parsed result in memory and
projects only counts and keys onto what it threads onward, and
`test_no_sampled_value_reaches_the_notification_the_index_or_a_span` asserts the notification text,
the index entry and the span fields **equal** between two runs of the same report that differ only in
whether the statement returned samples. An equality, not a substring search for the fixture's
values: a search only ever covers the strings somebody thought to look for.

**A cap on the WRITER is the only cap there is, because the reader's is a refusal.** The page reads a
report through `objects.readContent`, which refuses a document over
`apicommon.s3_config.MAX_DOCUMENT_BYTES`. Above that a report is not a large report, it is an
unreadable one — and every other finding in it is lost with the part that made it big. So
assemble-report serializes, measures what it is about to write, and drops the samples if that is what
keeps the document openable, saying so in the report, and then shortens the per-file lists (below).
Dropping and shortening are the only reductions it makes: truncating a figure would hand back a
number that is wrong rather than a report that is thinner.
`DQ_REPORT_MAX_BYTES` is re-declared in `dqcommon.config` rather than imported — the API ships inside
its own function's package, and a layer reaching into it would couple every data-quality verb to the
API's configuration — and `lambdas/test_data_quality_report_contract.py` holds the two **equal**, in
both directions, at the fleet level, which is the only place the two planes may be imported into one
process. Equality, not a bound: the cap is not a safety margin under the reader's limit, it IS the
reader's limit, and a one-sided assertion would let the writer drift in the direction it permits.
The reader's limit is on the **stored** body; under it the route also refuses a response that
escapes past Lambda's ceiling (the storage register's document-cap entry), which the writer does
not measure. A report is written at `ensure_ascii`, so only its quotes and backslashes cost more on
the way out — four bytes each, nine for a `\uXXXX` escape — and only a report about a third quotes
and backslashes can pass the ceiling under the cap. One that did would be refused with its samples
and its per-file lists still in it, where shedding them might have let it open. That residual is accepted because the
density does not come from the report's own shape: the object and column caps bound how many
strings it holds, each costing two quotes, and a `\uXXXX` escape is one backslash in six bytes. A
report at the cap gets to a third only when its file keys or values are themselves made of characters
JSON escapes short — quotes, backslashes, newlines, tabs; column names cannot be, since the name rule
refuses them.

**The reader between them has a cap of its own, and it is not the document's.** `csv` refuses a field
past a process-global limit of 131,072 characters, and assemble-report re-raises everything but a
missing object — so one oversized cell fails the whole report rather than one figure. The duplicates
cell is the only one this check can push past it, because it carries whole rows rather than single
values and a wide table multiplies it by the column count. **That holds only because the profile's
offending values are cut in the statement too**, at the same `SAMPLE_VALUE_CHARS`, on the `max_by`
key as well as the value — a cut the profile statement did not make until after this entry was
first written, so one column's sampled stray values, totalling more than the limit between them,
made a cell past it and failed the report over a figure that is only an illustration.
`report.duplicates_field_size_limit`
computes the figure from what the statement can return and **never returns less than the reader
already had**: at twenty grouped columns the computed figure is below the default, and returning it
would tighten the reader on cells that parse today — a raise that quietly becomes a lowering is how a
guard starts causing the failure it was added to prevent. The raise is scoped to that one read and
restored in a `finally`, because the limit is process-global and this verb parses three results on a
container that is reused.

**The statement that produces them keeps today's when it cannot.** The samples ride the query that
already counts duplicates, through the n-ary `max_by` the offending-value samples use, keyed on the
count left-padded to 19 digits — `bigint`'s width, so the pad never truncates — followed by the row's
own JSON, so the five kept are the most-repeated with ties broken by their text and a retry writes the
same report. The grouped columns are projected under positional aliases, which is what lets a source
column named `cnt` or `duplicate_rows` exist without colliding with the statement's own output names.
A source with an `array<…>` or `struct<…>` column keeps the previous statement **byte for byte** and
records its samples as omitted: Trino documents no cast from either to varchar, and a cast the engine
refuses fails the whole statement — trading the count that works today for a sample.

**Measured: what decides a report's size is the CHARACTER SET of the user's values, multiplied by
the column count.** Every figure that carries a value is bounded in CHARACTERS
(`MAX_SAMPLE_VALUE_CHARS`) and spent in BYTES, and the writer serializes at `ensure_ascii`, so JSON
escapes a control or BMP character to six and an astral code point to twelve, as a surrogate pair —
the unit trap this area's fences name. At `DQ_MAX_COLUMNS` 200, `MAX_SAMPLE_VALUE_CHARS` 200 and
`DQ_DUPLICATE_SAMPLE` 5, every column carrying a full `sampleOffending`, serialized as the write
serializes:

| whole report | ten offending values a column | five | five, with samples |
|---|---|---|---|
| printable ASCII (1 char) | 441,486 B — 14% | 232,486 B — 7% | 441,610 B — 14% |
| control or BMP (escapes to 6) | 2,441,486 B — 78% | 1,232,486 B — 39% | 2,441,610 B — 78% |
| astral (escapes to 12) | **4,841,486 B — 154%** | 2,432,486 B — 77% | 4,841,610 B — 154%, **dropped: opens** |

against a cap of 3,145,728 B. At ten an astral report was over the cap with nothing in it to drop,
so it was written, the API refused to serve it as `PayloadTooLarge`, and the page showed "That
request was too large" — advice to try again with less, which the user cannot follow — in place of
a check that had run and found things. **`DQ_OFFENDING_VALUE_SAMPLE` is five**, which is what the page
already showed — it rendered the first five of ten, and `max_by(x, x, n)` returns them in rank
order — so the page shows exactly what it did, and only a hand-downloaded `report.json` is thinner.
Measured with five, the drop now rescues the astral band, and a BMP report — Cyrillic, Greek, CJK,
accented Latin, most human writing — keeps its samples where at ten it lost them.
`test_the_largest_report_the_statements_can_return_is_written_where_the_page_can_read_it` builds the
astral worst case at every bound, per column and per file, from the constants and holds the written
document under the cap with every offending value intact, so raising any of `DQ_OFFENDING_VALUE_SAMPLE`,
`MAX_SAMPLE_VALUE_CHARS`, `DQ_MAX_COLUMNS` or `DQ_DUPLICATE_SAMPLE` is measured against the cap
rather than argued about. **Rejected:** keeping ten and dropping them second, which needs a new report field and a page
change and loses the examples on exactly the reports that most need them; and cutting each value at
200 escaped bytes instead of 200 characters — a static bound, but one that shortens every non-ASCII
example on every report, a Cyrillic one to about 33 characters and an emoji one to about 16.

**The per-file lists are shortened, longest first.** They are bounded in count and not in bytes, and
they grow with the file count and the key length rather than the column count. The
cross-file disagreements name, for each disagreeing file, every column it lacks and every one it
adds — up to `DQ_MAX_COLUMNS` names across up to `DQ_MAX_OBJECTS` files. Column names are ASCII,
since create-temp-tables refuses any name outside `cpcommon.columns`' rule, so the character-set
multiplier does not reach this list; its length does. Over 1,000 files split evenly between two
disjoint 100-column schemas, `report.cross_file` alone serializes to:

| column names | `crossFile` alone |
|---|---|
| 24 characters | 2,740,040 B — 87% |
| 44 characters | 4,740,040 B — 151% |
| 255, the name rule's ceiling | 25,840,040 B — 821% |

The row counts carry every file's key, and a key is not held to ASCII, so 1,000 keys serialize to
120,001 B (4%) at 100 ASCII characters, 545,001 B (17%) at 100 characters of which 85 are Cyrillic,
and 720,001 B (23%) at 700 ASCII ones — and that
last, added to the one-file astral worst case above (2,432,486 B), crosses the cap after the samples
are dropped. The cross-file list is over the cap in plain ASCII with no samples and no offending
values. A third list is bounded the same way: each column's `otherSpellings`, the case variants merged
from other files, which a folder whose every file spells every column its own way fills to one name
per file.

So once the samples are gone, those three lose their last entry one at a time, always from whichever
is longest in serialized bytes, until the report fits — and only then: a report that opens is written
exactly as before. Each writes how many it left out beside itself as `<field>Unlisted`
(`dq_assemble_report.UNLISTED_SUFFIX`) and the page says how many more there are. Nothing is cut
inside an entry, since a file listed with some of its missing columns would be a wrong figure. Each
drop is priced rather than the report re-serialized, and
`test_every_drop_is_priced_exactly_and_taken_from_the_longest_list` holds the price to the
serializer at every cap. The fixture of
`test_the_largest_report_the_statements_can_return_is_written_where_the_page_can_read_it` is every
bound at once — 1,000 files keyed to S3's 1,024 bytes in astral characters, half carrying all 200
columns of 255-character names and half only the first, every file spelling every column its own
way, top issues each naming 199 columns, ten encoding examples, astral offending values and samples.
Run through `report.build` and serialized before and after `_within_document_cap`, it measures
61,390,523 B uncapped and 3,143,984 B written, the three lists ending at 108,851 B, 119,029 B and
122,433 B. A report written over the cap before this shipped is refused by the document route; the
page says it is too large to open and to run the check again, not the generic "try again with less",
which asks a user who sent nothing to send less.

**What the shortening does not reach.** It measures the stored bytes, so a report the route refuses
for its escaped response (above) is written with its lists whole, and for that report the page's
advice to run the check again is wrong: a re-run writes the same report. And a drop is priced
with the count it writes, so a column whose only spelling is shorter than
`,"otherSpellingsUnlisted":1` makes the report larger when it is emptied — on a report where the
spellings are the longest list, a few such columns can show a count where listing the spelling would
have fit. Skipping a drop that grows the report is not the fix: a column of short spellings grows on
its first drop, so the spellings could never shrink.

**Rejected: a fixed order** — cross-file, then row counts, then spellings — the shape first proposed.
It empties each list before touching the next, so it drops every row count to make room for spellings
that were the reason the report was large; on the same fixture it wrote 352,052 B of spellings and no
file that disagrees or row count. **Rejected: each column's spellings as a list of its own**, which
lets two hundred short lists between them take the room the one cross-file list needs — measured,
351,854 B of spellings and again no files. The spellings compete as one list, the last column's going
first. **Rejected: a fixed number of files always**, which bounds a count and not bytes — 50
disagreeing files at the name ceiling are 2,584,001 B (82%) — and changes reports that open today;
and **grouping identical disagreements**, the better page for a split export, but unbounded for an
unusual source, so the shortening is owed either way.

The same factor is why `duplicates_field_size_limit` allows twelve characters per source character
rather than six: Trino's `substr` cuts by code point, so a sampled value can be
`SAMPLE_VALUE_CHARS` astral ones. Sized at six — which it was, until the figures above were
measured — a genuinely emoji-heavy wide table would fail the whole report on a cell the statement
was entitled to return.

**The method, so the next reader re-measures instead of trusting** (the figures move with
`DQ_OFFENDING_VALUE_SAMPLE`, `MAX_SAMPLE_VALUE_CHARS`, `DQ_MAX_COLUMNS` and `DQ_DUPLICATE_SAMPLE`,
and the cross-file ones with `DQ_MAX_OBJECTS`, at the values stated above): build a report through
`report.build` over a `DQ_MAX_COLUMNS`-wide source, serialize it with
`json.dumps(..., sort_keys=True, separators=(",", ":"))` — what `dq_assemble_report._serialize`
does, so the figure is the one the cap compares — and read its length. **Make the columns
numeric-DOMINANT with a few stragglers**, or `_column` writes no `sampleOffending` at all and the
report measures about 23 KB: a first attempt at these figures did exactly that and read 1% of the
cap. Then run it three times — a printable ASCII letter, a control character, an astral one — and
each of those twice, with and without the samples attached. Two classes cannot show that the spread
is the character set rather than the figure, and one pass per class cannot show which band the drop
actually rescues. For the cross-file list, call `report.cross_file` over `DQ_MAX_OBJECTS` files
keyed `alice/sales/2026/part-NNNNN.csv` (31 characters), whose headers alternate between two
disjoint 100-column schemas of names padded to the stated length; the name and key lengths move the
figures, and a reproduction that leaves them out will not match. For the row counts, call
`report._row_counts_by_file([], files)` over `DQ_MAX_OBJECTS` keys made of `alice/`, then repeated
characters, then a nine-character `NNNNN.csv`, to the stated length — how the key is made up moves
the non-ASCII figure by tens of kilobytes. The per-column table uses short `colN` names; names at
the rule's 255-character ceiling add about 100 KB — each heads its column and again the samples'
table — taking the astral five to 2,533,561 B (81%), and about 50 KB once the samples are dropped.

**Rejected: naming the file each sampled row came from.** Grouping by every column erases it, and
recovering it means aggregating paths for every group or scanning a second time. The per-file row
counts the same spec surfaced are the "where" at the file level.

**One rule, stated once.** `sql.grouped_column_names` and `sql.has_nested_column` are exported and
read by both the statement and the report. A second copy of the grouping rule would head the samples
with the wrong list on a CSV whose header names a partition key — putting every value under its
neighbour's name, with no error at all, on a table that still renders perfectly.

## History

### 2026-09-20

- **Settled:** SPEC-240.
