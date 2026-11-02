---
type: Spec
id: SPEC-184
title: "Presentation and Formatting"
description: "Adds Data Explorer presentation features that fetch nothing new: conditional row and cell colouring, colour by data type, group striping, and per-column value transformers including a safe URL template."
spec_status: Completed
depends_on: [SPEC-180, SPEC-181]
arc: data-explorer
arc_order: 9
---

## Overview

Everything in this spec changes how values *look* and nothing about what is *fetched*:
conditional row and cell colouring, colour-by-data-type, group row striping, and per-column
value transformers. It is the far side of the rule SPEC-178 built into the renderer's
signature — the SQL builder cannot reach presentation state, so nothing here can cost a query.

One requirement here is a security surface rather than a cosmetic one. The URL transformer takes
a user-authored template and renders a live anchor from cell data. A template is authored by the
user, but the value substituted into it comes from the table, which means a link's destination is
partly attacker-controlled whenever the data is. It gets a scheme allowlist and hardened anchor
attributes, and it is explicitly **not** `isSafeInAppPath`'s job — that rule governs in-app
notification paths (SPEC-061/167) and would be the wrong tool applied confidently.

## Scope

### In Scope

- Conditional row and cell colouring with operators, range/gradient mode and per-column scoping.
- Colorize by data type.
- Group row striping — alternating backgrounds across consecutive rows sharing values.
- Value transformers: URL, numeric and binary.
- Persistence of all of it per exploration tab.

### Out of Scope

- **Anything that renders SQL.** A test asserts this spec's state cannot reach the renderer.
- **The geometry half of presentation** — resize, reorder, pin, hide — which is SPEC-180's.
- **Geometry transformers** (DBeaver's spatial/SRID formatting). No GIS types here.
- **Cross-tab or cross-session persistence of colour rules.** They live with the tab, in
  `sessionStorage`, and are not a saved artifact.
- **Theming.** Colours come from the existing token palette; this spec adds no new design
  tokens and no light/dark handling of its own.

---

## Functional Requirements

### FR-001: Nothing here runs a query

#### Description:

The spec's defining property, asserted rather than assumed.

#### Acceptance Criteria:

- [ ] Applying, changing and removing every rule and transformer in this spec issues **zero**
      `StartQueryExecution` calls, asserted by count across a scripted sequence touching each.
- [ ] No module added by this spec is imported by `renderExplorationSql`, asserted by a static
      check on the renderer's import graph.
- [ ] Rules apply to the rows already on screen without a refetch.

### FR-002: Conditional colouring

#### Description:

Rules that colour a row or a cell when a condition holds.

#### Acceptance Criteria:

- [ ] Operators: `=`, `<>`, `>`, `>=`, `<`, `<=`, `LIKE`, `ILIKE` and `REGEX`.
- [ ] A rule sets foreground, background or both.
- [ ] A rule may be scoped to one column or applied across the row.
- [ ] Range/gradient mode interpolates a colour across a numeric range; non-numeric cells in a
      gradient rule are left unstyled rather than clamped to an end of the scale.
- [ ] Rules evaluate in order, and a later matching rule overrides an earlier one on the same
      property; the order is user-changeable.
- [ ] An invalid `REGEX` is refused at entry with a mapped message and never applied — a broken
      pattern must not silently match nothing.
- [ ] Comparison uses the **raw** cell value, not the transformed rendering (FR-005).
- [ ] Every colour pairing meets contrast requirements against the surface it lands on, and the
      axe pass over a coloured grid reports no violations.

### FR-003: Colorize by data type

#### Acceptance Criteria:

- [ ] A single toggle tints values by their Athena column type, using the existing token
      palette.
- [ ] It composes with conditional rules, which win where both apply.
- [ ] Colour is never the sole carrier of meaning — the type remains available in the column
      header and the Value panel.

### FR-004: Group row striping

#### Description:

Alternating backgrounds across consecutive rows that share values in one or more chosen columns
— a way to see block boundaries in sorted data.

#### Acceptance Criteria:

- [ ] One or more columns can be chosen; consecutive rows with equal values in all of them form
      one band, and adjacent bands alternate.
- [ ] Bands are computed over the **current page** and the surface says so — a band cannot be
      known to continue past the rows in hand.
- [ ] With no columns chosen, striping is off rather than defaulting to every-other-row.
- [ ] It composes with conditional colouring, which wins.

### FR-005: Transformers

#### Description:

Per-column rendering changes. Three of them.

#### Acceptance Criteria:

- [ ] **Numeric**: renders a string column as a number with a chosen precision; a lenient mode
      leaves unparseable values as-is rather than showing an error token.
- [ ] **Binary**: renders a value in a chosen encoding, with an explicit length cap and a clear
      truncation indicator.
- [ ] **URL**: renders an anchor from a user-authored template containing `${value}`.
- [ ] A transformer changes only the rendering. The raw value continues to drive filtering
      (SPEC-181 FR-002), colouring (FR-002), Calc (SPEC-182) and copy (SPEC-185) — asserted for
      each, because a transformed value leaking into any of them is a silent wrong answer.
- [ ] Transformers can be applied to several columns at once and removed individually.
- [ ] The Value panel shows the raw value alongside the transformed rendering.

### FR-006: The URL transformer is hardened

#### Description:

The one place in this spec where getting it wrong is a security bug rather than an ugly grid.

#### Acceptance Criteria:

- [ ] The resolved URL is parsed, and only `https:` is permitted — `javascript:`, `data:`,
      `vbscript:`, `file:` and every other scheme render as plain text with the reason
      available, not as a link.
- [ ] The check runs on the **resolved** URL after substitution, never on the template alone —
      a template of `${value}` with a cell value of `javascript:alert(1)` is the case that
      matters.
- [ ] The substituted value is percent-encoded for its position in the URL.
- [ ] Anchors carry `rel="noopener noreferrer"` and `target="_blank"`.
- [ ] `isSafeInAppPath` is **not** used, and a comment at the call site records why — it governs
      in-app paths, and reaching for it here would be a confident category error.
- [ ] A test drives each rejected scheme through a real cell value and asserts no anchor is
      rendered.

### FR-007: Persistence

#### Acceptance Criteria:

- [ ] Rules, the type-colour toggle, striping columns and transformers persist per exploration
      tab in `sessionStorage`, with the rest of the tab state.
- [ ] A malformed stored presentation block is discarded whole and replaced with defaults,
      never partially applied.
- [ ] A rule referencing a column that no longer exists after a grouping change is retained but
      inert, and is shown as inapplicable rather than silently dropped.

---

## Data Model

```ts
// dataExplorer.types.ts

export type ColourOperator = '=' | '<>' | '>' | '>=' | '<' | '<=' | 'like' | 'ilike' | 'regex';

export type ColourRule = {
  id: string;
  /** Undefined applies the rule across the row. */
  column?: string;
  operator: ColourOperator;
  value: string;
  foreground?: string;
  background?: string;
  /** Numeric gradient across [min, max] instead of a binary match. */
  gradient?: {min: number; max: number; from: string; to: string};
};

export type Transformer =
  | {kind: 'numeric'; precision: number; lenient: boolean}
  | {kind: 'binary'; encoding: 'hex' | 'base64'; maxLength: number}
  | {kind: 'url'; template: string};

export type FormattingState = {
  rules: ColourRule[];
  colourByType: boolean;
  stripeColumns: string[];
  transformers: Record<string, Transformer>;
};
```

`ExplorationPresentation` gains `formatting: FormattingState`.

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── RowColoursDialog.tsx
├── TransformersDialog.tsx
├── StripingControl.tsx
├── formatting.ts            # pure: rule evaluation, banding, transformer rendering
├── urlTransformer.ts        # the scheme allowlist and substitution
├── formatting.test.ts
├── urlTransformer.test.ts
└── formatting.a11y.test.tsx
```

---

## Implementation Phases

### Phase 1: Rule evaluation

- The pure evaluator: operators, ordering, gradient, the raw-value rule.
- The zero-execution and renderer-import assertions.

### Phase 2: Colour surfaces

- The rules dialog, colour-by-type, striping, and the contrast and axe passes.

### Phase 3: Transformers

- Numeric and binary; the raw-value-drives-everything assertions across filter, colour, Calc
  and copy.

### Phase 4: The URL transformer

- Substitution, percent-encoding, the resolved-URL scheme allowlist, hardened anchors, and the
  rejected-scheme tests.
