---
type: Decision
title: "`ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)"
description: "**`ACCEPTED_` tripwires record what has NOT been verified**: pin today's behaviour, name the reasoning, and say *revisit the decision, don't delete the test*."
---

The repo invented this idiom in SPEC-110 (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`).
SPEC-153 makes it the standard way to record a **load-bearing premise that is corroborated but not
discharged**, and a **documented behaviour someone will later mistake for a bug**.

A tripwire test pins **today's behaviour**, names the reasoning in its docstring, and ends with the
same instruction every time: **if it starts failing, revisit the decision — do not delete the test.**
That is the whole point. A premise held only in prose degrades silently; a premise held in an
assertion tells you the day it stops being true.

Four now exist. Two pin premises:

- **Athena's column-name fold** (`test_apply_refresh.py`). AWS documents that Athena lowercases every
  column name it creates through DDL, which is why SPEC-149 hard-codes the fold — but 149's in-place
  `UpdateTable` bypasses Athena, so the fold is now **ours**. If the premise is wrong, the first
  refresh of a mixed-case table silently re-cases every column while `diff-schema`, which folds case
  to compare, reports them unchanged: a mutation no test and no notification would report. The
  tripwire pins that a live `Order_ID` becomes `order_id` and the carried comment survives. Still
  **corroborated, not discharged** — the `GetTable` read-back that would discharge it is an owed live
  check.
- **The projection round-trip** (`test_load_table_definition.py`). The existing round-trip builds its
  fixture from `ddl.projection_properties` and compares the reconstruction re-rendered through the
  same function: render → parse → render vs render. It proves the parser is a left inverse of the
  renderer **on the renderer's own image**, which is worth having and is not "reads tables this
  pipeline did not write". It was **kept and renamed to say so**, and a second fixture whose
  properties did not come from our renderer was added beside it, with a guard test that fails if the
  fixture ever becomes the renderer's output.

Two pin accepted behaviour:

- **A redelivered notification create writes a second inbox row** (`test_notifications_writer.py`).
  These pipelines are at-least-once and `apply_create` mints a fresh `uuid4` per invocation; FIFO's
  producer-side dedup window does not bound a visibility-timeout redelivery. **Accepted:** the blast
  radius is one duplicated line in a read-only, dismissible list, while the fix with teeth is a
  producer-supplied idempotency key — a contract change across four control planes and the browser
  producer. `dqcommon.index_store` handles the equivalent case by replacing the row, and the
  asymmetry is now stated rather than accidental.
- **The runs-index cap evicts by position, not by timestamp** (`test_index_store_dqcommon.py`). Once
  a replay has moved a row to the end, position order and timestamp order disagree and the next new
  run drops a row that is newer in time. **Accepted:** the code says at the cap that the dashboard
  sorts by timestamp itself, and every evicted run's report object is untouched.

A tripwire is **not** a licence to leave a defect. It is the difference between a project that knows
what it has not verified and one that has forgotten.

## History

### 2026-08-05

- **Settled:** SPEC-153.
