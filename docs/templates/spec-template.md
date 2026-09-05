# Spec: [Feature Name]

**ID:** SPEC-XXX  
**Status:** Draft | In Progress | Completed  
**Last Updated:** YYYY-MM-DD  
**Depends On:** SPEC-XXX, SPEC-XXX (or "None")

## Overview

One paragraph. What this feature does and why it exists. Focus on user/business intent —
no implementation detail here. Someone unfamiliar with the codebase should understand
the purpose after reading this section alone.

## Scope

### In Scope

- Bullet list of what will be built in this spec

### Out of Scope

- Explicit exclusions — things that are related but intentionally deferred
- Call out anything Claude might reasonably assume is included but isn't

---

## Functional Requirements

<!--
  One FR per discrete behavior. Keep them granular enough that each one
  maps to a single unit of testable work. Use sequential IDs so you can
  reference them in prompts: "implement FR-001 through FR-003 only."

  Size: aim for 3-6 FRs. Past 8, split into a second spec and record the
  pair as an arc in docs/specs/ARCS.md - don't grow this one. The second
  spec restarts at FR-001; IDs are spec-local.

  validate_docs.py ratchets the NUMBER of specs above 8, so a new one
  fails CI. A genuinely indivisible spec may still sit above the line, but
  say so in one line under Scope > In Scope and let the reviewer accept or
  reject it - "it is all one feature" is what every over-scoped spec
  claims.
-->

### FR-001: [Requirement Name]

#### Description:

What the system must do.  

#### Acceptance Criteria:

- [ ] Testable condition written from the user/caller's perspective
- [ ] Each criterion is a binary pass/fail — no ambiguous language
- [ ] Cover the happy path, error path, and any edge cases

### FR-002: [Requirement Name]

#### Description:

What the system must do.  

#### Acceptance Criteria:

- [ ] Testable condition written from the user/caller's perspective
- [ ] Each criterion is a binary pass/fail — no ambiguous language
- [ ] Cover the happy path, error path, and any edge cases

<!-- Add more FRs as needed -->

---

## Data Model

<!--
  Use TypeScript interfaces or pseudocode — not prose.
  Claude Code produces much better-typed output when shapes are explicit here.
  Place final types in src/types/ and note that path.
-->

```ts
// src/types/[feature].types.ts

export type ExampleItem = {
  id: string;
  // ...
};
```

---

## API / Interface Contract

<!--
  For service functions, hooks, or component props — show the signature and
  a concrete usage example. Skip this section if FR acceptance criteria
  already cover it fully.
-->

```ts
// Function signature
functionName(param: Type, optionalParam?: Type): Promise<ServiceResult<ReturnType>>;

// Example call
const result = await functionName('value');
if (result.success) {
  console.log(result.data);
} else {
  console.error(result.error.message);
}
```

## Environment Variables

<!--
  List any new env vars this spec introduces. Delete section if none.
-->

Add to `.env.example`:
```
VITE_SOME_NEW_VAR=description-of-expected-value
```

## File & Folder Structure

<!--
  Show the exact paths that should exist after this spec is complete.
  Claude Code uses this to know where to put things without guessing.
-->

```
src/
├── features/
│   └── [feature-name]/
│       ├── FeatureName.tsx
│       ├── FeatureName.test.tsx
│       ├── useFeatureName.ts
│       ├── useFeatureName.test.ts
│       ├── featureName.service.ts
│       └── featureName.service.test.ts
├── types/
│   └── [feature].types.ts
```

## Implementation Phases

<!--
  Break work into phases that map to discrete, reviewable units. Each phase
  should be completable in one session. Do NOT write per-phase checkpoints
  here — when this spec is picked up for build, the implementing session
  generates an implementation plan, validates it against this spec and sends it
  to a fresh-context reviewer before writing code (see `docs/process/session-rhythm.md`, *The
  reviewer contract*). The phases below are the input to that plan.
-->

### Phase 1: [Name — e.g. "Data layer and types"]

- Task 1
- Task 2
- Task 3

### Phase 2: [Name — e.g. "Hook and state management"]

- Task 1
- Task 2