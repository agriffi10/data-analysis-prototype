---
type: Decision
title: "The artifacts are ordered most durable to least, and the receipt's failure is terminal"
description: "Artifacts land in the order manifest, source deletion, receipt, so a receipt exists only for a completed archive; a receipt failure fails the run and names the request id, and nothing may depend on the manifest."
---

`_manifest.json` into the vault → the source deletion → the receipt into the user's own space,
matching the data-quality plane's report → notification → index. A receipt therefore only ever
exists for an archive that completed, and a run interrupted between any two states leaves something
an operator can read.

**The receipt failing fails the RUN**, even though the data is safely archived and the source is
already gone: a user with no receipt has no id and therefore no route to a restore. The message
says the data IS archived and names the request id, so the run is recoverable by hand.

**The manifest is a report, not a record.** Nothing may come to depend on it — SPEC-170 rebuilds
every restore destination from the archived keys themselves, because an archived key encodes its
own origin. An AST sweep over the plane enforces that for the specs that have not been written yet,
exempting docstrings by node identity (SPEC-165's recorded trap) and qualifying the import test,
because `cpcommon.transfer.manifest` is a different module with the same name.

Both timestamps come from `$$.Execution.StartTime`, stamped onto the state by the same `Pass` that
stamps the execution name. Two `now()` calls would disagree by however long the deletion took, and
a re-run would disagree with itself.

## History

### 2026-08-12

- **Settled:** entered the register.
