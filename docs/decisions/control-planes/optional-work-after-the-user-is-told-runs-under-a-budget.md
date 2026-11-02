---
type: Decision
title: "Optional work after the user is told runs under a budget"
description: "**Optional work after the user is told runs under `cpcommon.budget`**, never on a bare default client inside a swallow: a stall raises nothing to swallow, so it holds the verb to its timeout, which fails a run whose outcome was already reported or, where the Catch goes to `Succeeded`, silences every notice after it. Each call is waited on for one cap, a loop through one budget starts no call past its deadline, and a guard holds deadline plus cap to half the timeout Terraform deploys the verb with. That covers the runs and archive indexes, the temp-table drops, the space-owner lookup and every notification send but two kinds — a loop of notices passes every send one `notify.send_budget()`. **Only a call whose late completion is harmless belongs under one**, since an abandoned call is not cancelled. The DLQ drain and every notify-failure wait for their sends instead: each reports an outcome already recorded, and at the drain and a timed-out door a stall held to the timeout is what earns the retry — the next sweep, Lambda's async retry. Reasoning: `lambdas/info/shared-layer.md`."
---

Some calls ride along after a verb's real work and are swallowed when they fail. A stall raises nothing to swallow, so on a bare default client it holds the verb to its timeout, which fails a run whose outcome was already reported or, where the Catch goes to `Succeeded`, silences every notice after it.

Such a call runs under `cpcommon.budget`: each is waited on for one cap, a loop through one budget starts no call past its deadline, and a guard holds deadline plus cap to half the timeout Terraform deploys the verb with. A loop of notices passes every send one `notify.send_budget()`. Only a call whose late completion is harmless belongs under one, since an abandoned call is not cancelled.

The DLQ drain and every notify-failure wait for their sends instead: each reports an outcome already recorded, and at the drain and a timed-out door a stall held to the timeout is what earns the retry, the next sweep or Lambda's async retry. Reasoning: `lambdas/info/shared-layer.md`.

## History

### 2026-11-02

- **Settled:** carried over from the area's Fences when the register was split.
