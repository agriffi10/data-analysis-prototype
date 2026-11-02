---
type: Decision
title: "A partition key is named after its folder, so its name may be one character (2026-09-16)"
description: "A declared partition key answers to `PARTITION_KEY_NAME_RE`, one to sixty-three lowercase characters from a leading letter, while usernames, databases, views and tables keep `CATALOG_IDENTIFIER_RE`'s floor of three; the browser mirrors each rule."
---

**The ruling (Andrew's).** A table over `dt=2025-01-01/` partitions could not be created, because
the key `dt` is two characters and every declared key was held to `CATALOG_IDENTIFIER_RE`, three
to sixty-three — twice: the Create table dialog kept Create disabled under its "Use 3–63
characters" hint, and a request that reached the plane was refused `invalid_partition_keys`,
which is how it was measured live. A declared key must match its folder, and `dt=`,
`ds=`, `hr=` and `d=` are ordinary Hive folder names, so the only repair was renaming every folder.
The same layout under `day=` built. Partition-key names now answer to their own rule,
`PARTITION_KEY_NAME_RE`: the same lowercase alphabet, leading letter and sixty-three-character
ceiling, from one character. Usernames, databases, views and tables keep three to sixty-three.

**Why the floor was never a catalog limit.** Three characters is this project's rule for a
username, which is also an S3 prefix and a Glue database name, and the one rule was reused for
every name the portal creates. Glue and Athena accept a one-character column, and the DDL that
declares a key quotes it — table-builder's create and table-share's copy alike — so a two-letter
reserved word such as `in` is the same case as the three-letter ones the old rule already admitted.

**A separate rule, not the shared one loosened.** Loosening `CATALOG_IDENTIFIER_RE` would admit a
two-character username and database. Each rule is spelled in `cpcommon.config` and in the
browser's `lib/catalogIdentifier.ts`, and `test_catalog_identifier_browser_mirror.py` holds each
pair equal, flags included; the username rule's third copy, in pre-signup, is pinned by nothing yet. The API's bound on `partitionKeys[].name` is unchanged,
because the ceiling is. Data-quality detects its keys from folder names and never applied the
identifier rule; it judges them by the column-name rule, which already accepted `dt`.

**What short names make ordinary.** Keys `d` and `dt` together: execute-ddl's confirmation and a
refresh's reconstruction each gather a key's properties by the prefix `projection.<name>.`, and
only the trailing dot keeps `d` from claiming `dt`'s. The overlap was possible before (`day` beside
`day_of_week`), and both handler suites now pin it.

## History

### 2026-09-16

- **Settled:** entered the register.
