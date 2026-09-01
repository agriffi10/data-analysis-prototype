import type {ReactElement} from 'react';
import type {RunOptions} from 'axe-core';
import {act, render} from '@testing-library/react';
import {configureAxe} from 'vitest-axe';
import {expect} from 'vitest';

// Centralised axe configuration: one place defines which rules run and which
// are disabled (with a written reason). Every a11y check renders through
// `expectNoA11yViolations` so the config lives here and nowhere else.
//
// THESE ASSERTIONS RUN IN THE LIGHT THEME, with one deliberate exception: `components/
// theme.test.tsx` renders the app shell in the dark theme once. The cap is stated rather than
// left to be inferred from what is absent — `color-contrast` is disabled below in either
// theme, so a second full pass would double an already long suite for a rule that cannot
// fire. Contrast, in BOTH themes, is measured from the token values by
// `lib/contrast.test.ts`.

/** WCAG A/AA rule tags the suite asserts against (machine-detectable subset). */
export const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] as const;

const runAxe = configureAxe({
  runOnly: {type: 'tag', values: [...WCAG_TAGS]},
  rules: {
    // jsdom has no layout engine or computed styles, so axe cannot evaluate
    // contrast — it would error, not pass. Disabled deliberately, never faked. What
    // covers it instead is `lib/contrast.test.ts`, which computes WCAG ratios from the
    // token values for every pairing the design uses, in both themes.
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
    // Disabled for the reason above, and covered by `lib/contrast.test.ts` instead. It is
    // repeated here because this object REPLACES the base `rules` for the specs that pass
    // it — a route spec would otherwise re-enable a rule that cannot run.
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
    expect(await runAxeSettled(container, axeOptions)).toHaveNoViolations();
  } finally {
    unmount();
  }
}

/**
 * Run axe with the whole traversal inside `act`.
 *
 * An axe pass takes real time, and a tree with an async boundary — a resolving query, a
 * focus trap claiming focus — commits its update DURING it. Outside `act` React logs
 * "An update to X inside a test was not wrapped in act(...)" for every one.
 *
 * This wrapper silences that, and NOTHING MORE — be precise about what it does not do,
 * because the obvious reading is wrong. `act` DEFERS the pending updates to the end of
 * its scope; it does not flush them before the run. And what axe inspects is unchanged
 * either way: axe-core snapshots the flattened tree when `run()` starts, so an update
 * landing mid-walk was never observable. Measured, not assumed — a component that swaps
 * in an `<img>` with no `alt` on a resolved microtask reports ZERO violations with and
 * without this wrapper, while the DOM afterwards holds the violating node.
 *
 * The standing consequence: these helpers check the tree as of the first paint. A state
 * a component reaches asynchronously has to be waited for by the CALLER — render, await
 * what you expect to appear, then hand the container to
 * {@link expectContainerHasNoA11yViolations}.
 */
async function runAxeSettled(container: Element, axeOptions?: RunOptions) {
  let results!: Awaited<ReturnType<typeof runAxe>>;
  await act(async () => {
    results = await runAxe(container, axeOptions);
  });
  return results;
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
  expect(await runAxeSettled(container, axeOptions)).toHaveNoViolations();
}
