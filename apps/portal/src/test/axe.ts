import type {ReactElement} from 'react';
import type {RunOptions} from 'axe-core';
import {render} from '@testing-library/react';
import {configureAxe} from 'vitest-axe';
import {expect} from 'vitest';

// Centralised axe configuration: one place defines which rules run and which
// are disabled (with a written reason). Every a11y check renders through
// `expectNoA11yViolations` so the config lives here and nowhere else.

/** WCAG A/AA rule tags the suite asserts against (machine-detectable subset). */
export const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] as const;

const runAxe = configureAxe({
  runOnly: {type: 'tag', values: [...WCAG_TAGS]},
  rules: {
    // jsdom has no layout engine or computed styles, so axe cannot evaluate
    // contrast — it would error, not pass. Contrast is governed by the design
    // tokens and stays a manual/visual concern. Disabled deliberately, never faked.
    'color-contrast': {enabled: false}
  }
});

/**
 * Route-level override: page renders own their document structure, so opt in to
 * the best-practice landmark / heading-order / region rules that only have
 * meaning for a full page. Pass this as the second arg for route specs.
 */
export const ROUTE_AXE_OPTIONS: RunOptions = {
  runOnly: {type: 'tag', values: [...WCAG_TAGS, 'best-practice']},
  rules: {
    'color-contrast': {enabled: false},
    region: {enabled: true}
  }
};

/**
 * Component-level override: a primitive rendered in isolation legitimately is
 * not inside a landmark, so the `region` rule is disabled for these checks —
 * the landmark guarantee is enforced by the route-level specs instead.
 */
export const COMPONENT_AXE_OPTIONS: RunOptions = {
  rules: {
    region: {enabled: false}
  }
};

/**
 * Render `ui` with the app's standard test setup and assert it has no
 * machine-detectable axe violations. `axeOptions` deep-merges over the project
 * default config (e.g. {@link ROUTE_AXE_OPTIONS} / {@link COMPONENT_AXE_OPTIONS}).
 *
 * Callers compose any providers/router the node needs (mirroring the rest of the
 * suite), then hand the wrapped element here.
 */
export async function expectNoA11yViolations(ui: ReactElement, axeOptions?: RunOptions): Promise<void> {
  const {container, unmount} = render(ui);
  try {
    const results = await runAxe(container, axeOptions);
    expect(results).toHaveNoViolations();
  } finally {
    unmount();
  }
}

/**
 * Assert an ALREADY-RENDERED container has no axe violations.
 *
 * {@link expectNoA11yViolations} renders and checks in one step, which is right for a tree
 * that is correct on first paint. It cannot reach a state the user has to drive into — a
 * dialog opened from a button, a panel expanded — because there is no point between its
 * render and its assertion at which to click. Render, interact, then hand the container
 * here; the axe configuration is still the one defined above and nowhere else.
 */
export async function expectContainerHasNoA11yViolations(container: Element, axeOptions?: RunOptions): Promise<void> {
  const results = await runAxe(container, axeOptions);
  expect(results).toHaveNoViolations();
}
