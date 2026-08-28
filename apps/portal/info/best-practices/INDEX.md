# App best practices — index

The rulebooks for code under `apps/portal/src/`. **Read only the section(s) your task needs** — each
doc carries its own internal index and is written to be loaded in parts.

| Doc | Load when you are… | Internal index |
|---|---|---|
| [React](react/react.md) | writing or refactoring any React component, hook, state, or effect | §1–§21 (Purity → Testing) |
| [Accessibility (WCAG 2.2)](accessibility/accessibility.md) | building or auditing any user-facing UI — markup, forms, keyboard/focus, color, ARIA | Task Index → §1–§4 (Perceivable / Operable / Understandable / Robust) |

**UI work usually touches both.** Pull the relevant sections from each rather than the whole files.

Two sections are cited from `CLAUDE.md` and are the authority for rules stated there only in
summary: **react.md §19** (JSDoc is the primary source of context; keep inline comments sparse) and
**react.md §21** (the testing rulebook — integration-style tests, mock only the AWS service
boundary).

Sibling trees: [`../component-inventory/INDEX.md`](../component-inventory/INDEX.md) for what already
exists to reuse; [`docs/best-practices/INDEX.md`](../../../../docs/best-practices/INDEX.md) for the
Python and Lambda rulebooks.
