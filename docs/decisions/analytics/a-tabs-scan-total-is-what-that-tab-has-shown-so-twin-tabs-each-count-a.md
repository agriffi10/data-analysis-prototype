---
type: Decision
title: "A tab's scan total is what that tab has shown, so twin tabs each count a shared execution (2026-09-26)"
description: "A tab's scan total means what that tab has shown, not what it caused, so twin tabs sharing one execution each count its bytes and the sum may exceed Athena's bill; do not file a shared execution at zero."
---

Two Explorer tabs showing one description share one execution — the cache is keyed by source and
SQL, not by tab — but each tab keeps its own cost ledger (`useExplorationTabs`' `scannedByExecution`),
so the second tab to reach it records its bytes too, and its line reads *"This query scanned X"*.
Summed across tabs, the figures exceed what Athena billed.

**Accepted, not pending (Andrew, 2026-09-26): a tab's total means "what this tab has shown", not
"what this tab caused".** The cost line answers a question about the tab in front of the user, and
*"Loaded from an earlier run in this tab"* is the one cache hit it names; a hit on another tab's
run is reported as the scan it is.

**The trap, from an attempt that was built and reverted (UI audit, #887's review):** recording a
twin's execution at zero, and calling it a hit from another tab, bills whichever tab is SHOWING when
the run finishes. Start in tab A, switch to its twin B before the run ends, and B records the full
scan while A records nothing and then claims to have loaded B's run. Getting attribution right needs
the tab that STARTED each execution, which is new state kept beside the cache for a figure whose
meaning this entry settles the other way.

**Rejected.** Filing a shared execution at zero on whichever tab reaches it second; a session-wide
seen-executions set; tracking the starting tab.

## History

### 2026-09-26

- **Settled:** entered the register.
