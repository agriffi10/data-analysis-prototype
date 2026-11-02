---
type: Decision
title: "No ASL state decodes an error Cause (PR #252, control-plane-wide)"
description: "**No ASL state may decode an error `Cause`.** `States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **uncatchable anywhere**. Carry raw `$.error`; decode with `cpcommon.errors.failure_reason`, the only decoder."
---

`States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **neither retriable nor catchable anywhere** — not even by a `Catch` on the same state. The `ParseError` `Pass` states that did this killed executions *before* the recorded-failure/notify states on 3 of 4 real error shapes (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — verified live with `TestState`, which injects the shape; a real `States.DataLimitExceeded` is never caught, so it never reached a `ParseError` state at all). Terminal states now carry the **raw `$.error` `{Error, Cause}`**; `cpcommon.errors.failure_reason` decodes it in Python. Enforced by `lambdas/control-plane-common/test_state_machines_cpcommon.py`. Related trap: a `Pass` state's JSONPath hard-fails on an **absent key** (a null *value* is fine), so anything a terminal `Pass` names must be seeded on every path — now **enforced by a test** (SPEC-114): every `Pass` reachable from a failure seed may read only keys that seed supplies. It has caught this arc twice (`$.location`, SPEC-112; `$.reportKey`, SPEC-114).

## History

### 2026-08-03

- **Settled:** entered the register.
