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
  Break work into phases that match your review cadence. Each phase should
  be completable in one Claude Code session. End every phase with a
  Checkpoint — a human-verifiable test you run before saying "continue."
-->

### Phase 1: [Name — e.g. "Data layer and types"]

- Task 1
- Task 2
- Task 3

#### Checkpoint

[What you will verify before approving Phase 2. Be specific —
name the test file, the command to run, or the thing you'll click in the UI.]


### Phase 2: [Name — e.g. "Hook and state management"]

- Task 1
- Task 2

#### Checkpoint

[What you will verify before approving Phase 2. Be specific —
name the test file, the command to run, or the thing you'll click in the UI.]

## Open Questions

<!--
  Decisions that need an answer before or during implementation.
  Check these off as they're resolved. Unresolved questions in later phases
  are fine — flag them so Claude Code knows to stop and ask rather than assume.
-->

- [ ] [Question that needs an answer before Phase 1]
- [ ] [Question that can wait until Phase 2]