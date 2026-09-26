# Lambda best practices — index

The rulebooks for code under `lambdas/`. **Read only the section(s) your task needs** — each doc
carries its own internal index and is written to be loaded in parts.

| Doc | Load when you are… | Internal index |
|---|---|---|
| [Lambdas](lambdas/lambdas.md) | writing, refactoring, or decomposing any Lambda function or its Step Function orchestration / IAM | §1–§13 (Single responsibility → Language conventions) |
| [Python](python/python.md) | writing or refactoring any Python — style, naming, types, exceptions, docstrings | §1–§15 (Tooling → Modules & power features) |

**`lambdas.md` is about shape** (one task per function, what belongs in a Step Function, how IAM is
scoped); **`python.md` is about style** and layers over it. A new verb Lambda needs both.

**python.md §14** is the authority for the docstring standard `CLAUDE.md` states in summary:
`lambdas/` production code carries **no** inline comments beyond §14's lint-directive shape, and
every module, class, method and function, public or `_private`, gets a Google-style docstring — a
function's with `Args:` / `Returns:` / `Raises:` written out, using `None.` where a section is
empty. Test modules, `conftest.py` and `fakes.py` are outside it.

Sibling trees: [`../INDEX.md`](../INDEX.md) for the lambda index grouped by control plane;
[`docs/best-practices/INDEX.md`](../../../docs/best-practices/INDEX.md) for the React and
accessibility rulebooks.
