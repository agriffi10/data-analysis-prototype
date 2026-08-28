# Best Practices — cross-domain router

Domain coding rulebooks for agents. **Read this index first**, then open only the one doc — and only
the section(s) — your task needs. Each doc is a token-efficient, self-contained agent reference with
its **own internal index**; never load a whole doc you don't need, and don't load a second domain
unless the task genuinely spans both. This index is a **router, not content** — keep it to one screen.

**The rulebooks live beside the code they govern**, one `info/` tree per domain, so the doc is found
by whoever is standing in the tree rather than by remembering a central path. This file stays here
because it is the one entry point that spans all three.

| Domain | Tree | Rulebooks |
|---|---|---|
| App (React SPA) | [`apps/portal/info/best-practices/`](../../apps/portal/info/best-practices/INDEX.md) | React, accessibility |
| Lambdas (Python) | [`lambdas/info/best-practices/`](../../lambdas/info/best-practices/INDEX.md) | Lambda shape, Python style |
| Infrastructure (OpenTofu) | [`infra/info/`](../../infra/info/INDEX.md) | No rulebook yet — the module index is the entry point |

## The individual docs

| Doc | Load when you are… | Internal index |
|---|---|---|
| [React](../../apps/portal/info/best-practices/react/react.md) | writing or refactoring any React component, hook, state, or effect | §1–§21 (Purity → Testing; §19 JSDoc component docs is the primary source of context, keep inline comments sparse; §21 Testing is the rulebook CLAUDE.md's test rules point to) |
| [Accessibility (WCAG 2.2)](../../apps/portal/info/best-practices/accessibility/accessibility.md) | building or auditing any user-facing UI — markup, forms, keyboard/focus, color, ARIA | Task Index → §1–§4 (Perceivable / Operable / Understandable / Robust) |
| [Lambdas](../../lambdas/info/best-practices/lambdas/lambdas.md) | writing, refactoring, or decomposing any Lambda function or its Step Function orchestration / IAM | §1–§13 (Single responsibility → Language conventions) |
| [Python](../../lambdas/info/best-practices/python/python.md) | writing or refactoring any Python — style, naming, types, exceptions, docstrings (layer over `lambdas.md` for Lambda *shape*) | §1–§15 (Tooling → Modules & power features; §14 docstrings are the primary source of context, keep inline comments sparse) |

## How to use

1. Match your task to a **Domain** row above and open that tree's index.
2. Use the doc's **own index** (the React Index, the a11y Task Index) to pick the section IDs you
   need — read only those.
3. If a rule conflicts with existing code, follow the rule and **flag the conflict** (unless the user
   says otherwise).

UI work usually touches **both** React and accessibility — pull the relevant sections from each, not
the whole files.

## Adding a new domain

- Put the doc in the tree it governs: `<domain-root>/info/best-practices/<domain>/<domain>.md`,
  written as a token-efficient agent reference — a short "how to use", an internal index, and
  imperative ✅/🔴 rules (match the existing four).
- Add **one row** to that tree's own index, and **one row** here. Nothing more in either — the detail
  lives in the doc, not the router.
