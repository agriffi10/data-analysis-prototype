# Test utilities (`apps/portal/src/test/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `expectNoA11yViolations(ui, axeOptions?)` + `ROUTE_AXE_OPTIONS` / `COMPONENT_AXE_OPTIONS` / `WCAG_TAGS` | `test/axe.ts` | Render a node and assert no `axe-core` violations; one centrally-defined WCAG A/AA config (`color-contrast` off — jsdom). Route preset enables landmark/heading/region rules; component preset disables `region`. Co-locate `*.a11y.test.tsx` checks; `npm run test:a11y` runs only those (SPEC-045). `expectContainerHasNoA11yViolations(container, axeOptions?)` checks an ALREADY-RENDERED container, for a state the user must drive into (a dialog opened from a button) — same config (SPEC-124). |
| `mockApi(apiRequest)` → `{answer, fail, calls, routes, bodyFor, queryFor, paramsFor, countOf, fn}` | `test/apiMock.ts` | Programs a mocked `apiRequest` **by route id**, never by call order, and records what each call sent. `paramsFor` reads the PATH parameters: a templated route puts its identifier in the path, so a test reading only the body and the query passes whichever execution id or database the service chose, including the wrong one. |
| `seedRuntimeConfig(partial?)` / `clearRuntimeConfig()` | `test/seedRuntimeConfig.ts` | Puts a spec on the runtime-document path instead of the dev fallback. Most tests need neither — under Vitest `DEV` is true and no load has happened, so `vi.stubEnv`'d `VITE_*` values answer. Seed only when the document itself is the subject, or when a spec stubs `DEV` false (SPEC-192). |
