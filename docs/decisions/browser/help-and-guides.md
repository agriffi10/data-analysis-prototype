---
type: Decision
title: "Help & guides (SPEC-074)"
description: "**Help & guides document only what is shipped and wired end to end.**"
---

> **Superseded in part by SPEC-207:** the header icon opens a **panel over the current route** on
> the six routes that have one, and stays a link to `/help` everywhere else. The page, its section
> sidebar and its hash addressing are unchanged. Full entry: [*Help is read where the work is*](help-is-read-where-the-work-is-and-a-gated-pages-help-is-gated-by.md).

In-app how-to surface — a header help icon → `/help` page (Files/Query left-rail shell: section sidebar + accordion guide cards, active section in the URL hash). **Presentation + authored content only** (no data layer/network/AWS/IAM/infra/env/deps). Content is a **static, code-grounded** module (`features/help/helpContent.ts`) documenting only shipped, wired-end-to-end behavior (FR-005) — **keep it in sync via the completion-ritual step 9** whenever a user-facing feature lands/changes.

## History

### 2026-07-03

- **Settled:** SPEC-074.
