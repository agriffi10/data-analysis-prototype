# Test utilities (`apps/portal/src/test/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `expectNoA11yViolations(ui, axeOptions?)` + `ROUTE_AXE_OPTIONS` / `COMPONENT_AXE_OPTIONS` / `WCAG_TAGS` | `test/axe.ts` | Render a node and assert no `axe-core` violations; one centrally-defined WCAG A/AA config (`color-contrast` off — jsdom). Route preset enables landmark/heading/region rules; component preset disables `region`. Co-locate `*.a11y.test.tsx` checks; `npm run test:a11y` runs only those (SPEC-045). `expectContainerHasNoA11yViolations(container, axeOptions?)` checks an ALREADY-RENDERED container, for a state the user must drive into (a dialog opened from a button) — same config (SPEC-124). |

