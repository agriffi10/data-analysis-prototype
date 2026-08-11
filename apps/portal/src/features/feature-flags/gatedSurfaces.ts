import type {FeatureFlagKey} from './featureFlags.types';

/**
 * One surface a flag controls.
 *
 * `name` is the ACCESSIBLE NAME the registry test queries by — not a test id and not a CSS
 * class. That is the point of it: a control removed from the DOM and a control still present
 * under a changed label are different bugs, and only an accessible-name query tells them
 * apart. It is also the name a user would say out loud, which is what makes a registry row
 * reviewable by someone who has not read the component.
 */
export type GatedSurface = {
  /** Accessible name of the control or nav item, as the registry test queries it. */
  name: string;
  kind: 'nav' | 'route' | 'control' | 'guide';
  /** Route path for `kind: 'route'`; the owning route otherwise. */
  path: string;
  /**
   * For `kind: 'guide'`, the `helpContent.ts` section or guide id this row hides.
   *
   * The registry is the ONLY home of the guide→flag mapping (FR-006 AC3) — `helpContent.ts`
   * knows nothing about flags, so a guide cannot end up gated in the Help list and ungated in
   * the search index, or vice versa.
   */
  helpId?: string;
};

/**
 * Every surface every flag hides, in one place.
 *
 * **THE REGISTRY EXISTS BECAUSE THE TABS ARE THE EASY PART.** "Create table from this folder"
 * lives in the file browser and is a Query feature; "Share table" lives in the Query rail and
 * pushes into Shared Workspaces; "Check data quality" is a button on a file-browser selection.
 * A per-component pass finds three of those and ships the fourth visible — the failure
 * `process.md` records from log-forge's SPEC-033, which is why this is a registry with a
 * walking test rather than a checklist.
 *
 * Adding a fifth entry point is therefore a registry edit, not a discovery exercise, and
 * `gatedSurfaces.test.tsx` fails for a row whose surface it cannot make disappear.
 *
 * **A flag is presentation, never authorization.** Nothing here revokes a grant; every row
 * removes a way of ASKING for something the user may still do by other means.
 */
export const GATED_SURFACES: Record<FeatureFlagKey, readonly GatedSurface[]> = {
  files: [
    {name: 'Files', kind: 'nav', path: '/files'},
    {name: '/files', kind: 'route', path: '/files'},
    // Signed-in visitors only — the signed-out page gates nothing (FR-007).
    {name: 'Go to Dashboard', kind: 'control', path: '/'},
    {name: 'Files help section', kind: 'guide', path: '/help', helpId: 'files'}
  ],
  query: [
    {name: 'Query', kind: 'nav', path: '/query'},
    {name: '/query', kind: 'route', path: '/query'},
    // In the FILE BROWSER, not the Query workspace. The one everyone forgets.
    {name: 'Create table', kind: 'control', path: '/files'},
    // Belt to the route's braces: a later spec surfacing these elsewhere inherits the row.
    {name: 'Refresh table', kind: 'control', path: '/query'},
    {name: 'Share table', kind: 'control', path: '/query'},
    {name: 'Create view', kind: 'control', path: '/query'},
    {name: 'Query help section', kind: 'guide', path: '/help', helpId: 'query'},
    // Building a table from a folder is a Query capability wearing a file-browser button, so
    // its guides follow the `query` flag rather than `files`.
    {name: 'Tables help section', kind: 'guide', path: '/help', helpId: 'tables'}
  ],
  sharedWorkspaces: [
    {name: 'Connections', kind: 'nav', path: '/connections'},
    {name: '/connections', kind: 'route', path: '/connections'},
    {name: 'Your spaces navigation', kind: 'control', path: '/files'},
    {name: 'Add members', kind: 'control', path: '/connections'},
    // The recipient-KIND choice, not the dialog: it drops the toggle rather than rendering a
    // one-option control (FR-005).
    {name: 'Shared spaces', kind: 'control', path: '/query'},
    // The last two are beyond the spec's contract table — see the delivery doc. Hiding the
    // rail alone left both the schema rail and the move/copy WRITE path open.
    {name: 'Shared databases in the schema rail', kind: 'control', path: '/query'},
    {name: 'Shared spaces as a move destination', kind: 'control', path: '/files'},
    {name: 'Shared connections help section', kind: 'guide', path: '/help', helpId: 'shared-connections'}
  ],
  dataQuality: [
    {name: 'Data quality', kind: 'nav', path: '/data-quality'},
    {name: '/data-quality', kind: 'route', path: '/data-quality'},
    // Its own row: a report deep link must render unavailable and issue NO S3 request, or the
    // page becomes an existence oracle for someone else's report (SPEC-113's rule).
    {name: '/data-quality/:space/:requestId', kind: 'route', path: '/data-quality/:space/:requestId'},
    {name: 'Check data quality of the selected item', kind: 'control', path: '/files'},
    // Named by the contract table and gated by nothing until review said so.
    {name: 'Data quality link on a notification', kind: 'control', path: '/notifications'},
    // Inside the FILES section — which is why guides are gated individually, not by section.
    {name: 'Check data quality guide', kind: 'guide', path: '/help', helpId: 'check-data-quality'},
    {name: 'Past data quality checks guide', kind: 'guide', path: '/help', helpId: 'past-data-quality-checks'}
  ]
};

/**
 * Every help section or guide id hidden while `flags` says its feature is off.
 *
 * Derived from the registry rather than declared beside it, so the Help page and the walking
 * test cannot disagree about which guide belongs to which flag.
 *
 * @param isEnabled - Answers whether one flag is on (normally `useFeature`).
 * @returns The ids to drop, as a Set for a cheap lookup per section and per guide.
 *
 * @example
 * const hidden = hiddenHelpIds((key) => flags[key]);
 * HELP_SECTIONS.filter((s) => !hidden.has(s.id));
 */
export function hiddenHelpIds(isEnabled: (key: FeatureFlagKey) => boolean): Set<string> {
  const hidden = new Set<string>();
  for (const [key, surfaces] of Object.entries(GATED_SURFACES) as [FeatureFlagKey, readonly GatedSurface[]][]) {
    if (isEnabled(key)) continue;
    for (const surface of surfaces) if (surface.helpId) hidden.add(surface.helpId);
  }
  return hidden;
}

/**
 * The nav destinations a flag governs, as `path → flag`.
 *
 * `PrimaryNav` and `AppNavDrawer` live in `components/`, which may not import a feature
 * (SPEC-155), so they take a predicate instead of reaching for the hook. This is what the
 * predicate is built from — and it is derived from the registry, so a nav row cannot be gated
 * on a different flag from the route it points at.
 */
/**
 * A flag's own nav destination — its label and where it points.
 *
 * Read from the registry's `nav` row rather than declared separately, so the name the
 * unavailable page says out loud is the same string the missing tab used to carry.
 *
 * @param key - The flag.
 * @returns The destination, or `undefined` for a flag with no nav row.
 */
export function navDestination(key: FeatureFlagKey): {to: string; label: string} | undefined {
  const nav = GATED_SURFACES[key].find((surface) => surface.kind === 'nav');
  return nav ? {to: nav.path, label: nav.name} : undefined;
}

export const NAV_PATH_FLAGS: ReadonlyMap<string, FeatureFlagKey> = new Map(
  (Object.entries(GATED_SURFACES) as [FeatureFlagKey, readonly GatedSurface[]][]).flatMap(([key, surfaces]) =>
    surfaces.filter((s) => s.kind === 'nav').map((s) => [s.path, key] as const)
  )
);
