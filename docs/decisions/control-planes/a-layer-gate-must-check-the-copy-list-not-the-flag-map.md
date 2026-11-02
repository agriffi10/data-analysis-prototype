---
type: Decision
title: "A layer gate must check the copy list, not the flag map (SPEC-153)"
description: "No per-file copy list exists any more: the image assembler ships what each `lambdas/*-common/` directory holds, a test compares its output with an independent walk, and a directory it cannot classify is refused."
---

The packaging harness existed because SPEC-137 shipped instrumented code whose layer attachment was
missing and every gate was blind. It joined each function's **imports** against the matrix **flags**.
That answers "which functions attach the layer" and says nothing about **what the layer contains** —
so adding a module to `lambdas/shared-space-common/`, importing it from a function whose row already
reads `layer: true`, passed every check, deployed green, and raised `ModuleNotFoundError` at cold
start. SPEC-137 again, straight through the gate built to stop it.

**The rule: for any shared code packaged by an explicit per-file list, assert SET EQUALITY between that
list and the directory.** ~~`shared-space-common` was the only such layer.~~ **Superseded by SPEC-214:
there is no per-file list anywhere any more** — the container image's assembler ships what a shared
directory contains, so the rule has no subject left in this repository. It is kept because the *reason*
outlives it: a declaration maintained beside the thing it declares drifts, and the drift is invisible
until a cold start. The set equality survives in a different shape — the assembler's output against an
independent walk of the same directories. Both directions — a module in the directory and not the list never ships; a
module in the list and not the directory fails the `cp` at deploy time. Completing the flag map does
**not** substitute: all nine shared-space modules ship in one layer behind one flag, so a module that
never reaches the zip is invisible to the flag map no matter how complete it is. `LAYER_PACKAGES` was
corrected to all nine anyway, with a comment saying exactly that.

`shared-space-common` was the **only** such layer — every other copied a whole package directory or
pip-installed, so a new module shipped by existing, and those were exempt for that named reason.
~~`test_no_unchecked_explicit_copy_list_was_added` fails if a second one appears, so the exemption cannot
quietly widen.~~ **Retired with the list by SPEC-214**, and nothing replaced it because nothing can: the
exemption it policed does not exist once every shared directory ships what it holds. Its structural
successor is a different guard for a different hazard —
`test_every_directory_under_lambdas_is_a_function_shared_code_or_named_exempt`, which refuses a directory
the assembler cannot classify, so a new one has to be declared rather than defaulting into shared code.
The guard-the-guard habit carried over: every comparison there asserts its inputs are non-trivial first,
because two empty sets are equal.

SPEC-152 shipped the shared-space half of this in
`test_notify_failure_import_safety.py`; SPEC-153 moved it to the packaging harness and generalised it,
rather than leaving two copies of one set-equality to drift apart.

## History

### 2026-08-05

- **Settled:** SPEC-153.
