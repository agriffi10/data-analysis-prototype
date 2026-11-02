---
type: Decision
title: "The log-foundry pin, and what a library upgrade owes the code written around it (SPEC-224)"
description: "The fleet pins `log-foundry==1.0.0` exactly and core-only, and a bump owes a check of everything built around the old version: a workaround the library makes redundant is retired, and a claim anchored to a version is re-checked."
---

The fleet runs **`log-foundry==1.0.0`**, pinned exactly and core-only, for the reasons the pin's own comment gives. What this entry records is not the bump but its **shape**, because two of the three changes that reached this repo were things the codebase had built *around* the old version, and both were invisible to a green suite.

**A capability the library gains retires the workaround, and the workaround does not retire itself.** `configure(sink=…)` now drains, closes and re-points delivery; before, it leaked to the sink it replaced, which is why two harnesses retired the worker by hand. That reach could not merely be left alone: the private name behind it no longer exists, so it had degraded to a **silent no-op behind a `getattr` default** — reading as load-bearing while doing nothing. A second reach was worse than redundant: the library now holds a live sink beside the stored config, so `conftest.py`'s `_config` restore left it **reporting one sink while delivering to another**, on the span path only (the orphan path agrees even when it is broken, so an orphan-path probe passes vacuously).

**A prohibited-name list must be READ by the thing that prohibits.** `_emit` refuses `echo` and `fields`, and they are refused for **different reasons**: an un-dropped `echo` collides with the keyword `_emit` always passes and raises `TypeError` into business logic, while an un-dropped `fields` is the library's own parameter and raises **nothing** — the mapping is unpacked over the event and the author's field silently vanishes. The first version of this change defined `PROHIBITED_FIELDS` and hard-coded both names beside it, so emptying it changed nothing and extending it dropped nothing. The constant is now read, and a test plants a third name.

**Three standing rules this settled.** No module outside `cpcommon/observability.py` and the two named test harnesses reaches an underscore-prefixed `log_foundry` name — held by a guard that resolves **import aliases**, because `import log_foundry as lf; lf._lifecycle` is the spelling this repo actually uses and renders with neither the package name nor a recognisable prefix in it. No `@traced`/`@step` function may be a **generator**: the library refuses one at decoration, which for this fleet is a cold start that never completes. And the "no way to turn stack capture off" claim three register entries lean on is **asserted by a test against the installed version**, so a release that adds an opt-out reddens rather than silently outliving the decision — the claim itself is unchanged and still true.

**A version-anchored claim rots differently from a wrong one, and the two need different repairs.** Of five claims corrected here, **two** were true of the previous pin and false of this one, **one was never true** (the one-door absolute above), and **two are still true and were merely dated to a superseded version** — including the stack-capture claim, which is unchanged and now asserted by a test. Only the first kind is a falsification; and the two dispositions that predate this pin are now stated **version-free**, since naming their release would leave a superseded version in the one block a sweep exists to clear. Full reasoning and the measurements: `spec-delivery/SPEC-224`.

## History

### 2026-09-08

- **Settled:** SPEC-224.
