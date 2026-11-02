---
type: Decision
title: "The contract is declared in Python and the TypeScript is generated (SPEC-197)"
description: "`lambdas/api/apicommon/contract.py` is the single wire declaration and the TypeScript is generated from it; CI refuses a diff on the generated file, and the closed type vocabulary raises rather than emitting `unknown` or `any`."
---

Two hand-edited copies rot. A contract test both sides hand-wrote against each other compares a copy
of the answer with itself, and it agrees most confidently exactly when both were written by the same
session on the same afternoon. So `lambdas/api/apicommon/contract.py` is the single declaration and
`scripts/generate_api_contract.py` emits the TypeScript.

Python is the source rather than TypeScript because the runtime request validator and the wire types
must read **one** declaration — a validator written against a separate schema is a third copy, and
the third copy is the one nobody regenerates. The generator and the validator consume the same
`walk` of the same annotation, asserted structurally: an AST check that the generator defines no
walker of its own.

**Two gates.** CI regenerates and refuses a diff on the generated file, which catches both
directions — a Python type edited without regenerating, and the generated TypeScript hand-edited.
`npm run build` is the second: a field removed or renamed regenerates into a changed type and fails
at every call site, which no test has to be written for.

**The type vocabulary is closed and the emitter never falls back.** `str`, `int`, `float`, `bool`,
`None`, `list[X]`, `X | None`, `Literal` over strings, references to declared `TypedDict`s, and
optional keys in both spellings. Anything else **raises**. This is the requirement that can silently
succeed: a fallback type agrees with every possible value, so the day the emitter meets a shape it
cannot express is the day the contract stops being checked and nothing goes red. It never emits
`unknown` and never emits `any`.

## History

### 2026-08-18

- **Settled:** SPEC-197.
