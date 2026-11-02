---
type: Decision
title: "Not every success notice links, and the table planes' do not on purpose"
description: "Table-build and table-share success notices carry no `link`, and the restore's started notice has none either, by decision; ask Andrew before adding one to make the producers uniform."
---

**Decided 2026-09-22 (Andrew).** The table-build plane's success notices (built, refreshed and
already up to date) and table-share's success notices carry no `link`. That was already the code's
choice (`tbcommon/notify.py`'s `emit_created` passes none, and the same module links only the
columns-removed refusal), and a live check had logged it as a failure against a "with a link"
clause the retired Arc B script carried. Andrew kept the notices link-free and dropped the clause.
`docs/testing/e2e.md` §4.12 records it so a live check does not log them again. The restore's
started notice is link-free for its own reason, since nothing has arrived yet. **Do not add a link
to these notices to make the producers uniform**; ask first, because the choice was made.

## History

### 2026-09-22

- **Settled:** entered the register.
