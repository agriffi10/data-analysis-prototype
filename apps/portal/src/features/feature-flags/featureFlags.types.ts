/**
 * The features a flag can hide. Named for the features the portal ships, not
 * for the components that render them — a flag governs an AREA, and the gating has
 * to reach every entry point into that area, not one screen.
 *
 * Five of the seven are areas, and the two exceptions are deliberate and different from each
 * other. `asyncFileOperations` is a kill switch over the file browser's copy/move/delete
 * routing, whose only other switch is `files: false` — which removes the entire file browser.
 * Off, every gesture keeps the browser's synchronous path; on, anything that is not exactly one
 * file is handed to the control plane. Publishing it needs no app build, which is what makes the
 * largest user-visible change in the product survivable.
 *
 * `resultsConversion` is neither an area nor a kill switch but a PRESENTATION flag over one
 * control: off, the Save-results dialog offers no format choice and saves the CSV it always did.
 * It takes nobody's access away — the enqueue route is live and ungated either way — so it hides
 * three options and changes what nobody may do.
 */
export type FeatureFlagKey =
  'files' | 'query' | 'sharedWorkspaces' | 'dataQuality' | 'dataExplorer' | 'asyncFileOperations' | 'resultsConversion';

/** Every flag, always. No consumer ever handles `undefined`. */
export type FeatureFlags = Record<FeatureFlagKey, boolean>;

/**
 * What consumers branch on.
 *
 * `'fallback'` = the compiled-in defaults are in force because the document was unusable.
 * It exists because the failure is otherwise INVISIBLE: every default is `true`, so a
 * permanently-blocked fetch renders exactly like a healthy all-on environment. Nothing
 * user-facing reads this — it feeds the dev-only diagnostic and the live check.
 */
export type FeatureFlagsStatus = 'loading' | 'ready' | 'fallback';

/** The document `.github/workflows/deploy-config.yml` publishes to `_config/feature-flags.json`. */
export type FeatureFlagDocument = {
  version: number;
  defaults: FeatureFlags;
  environments: Record<string, Partial<FeatureFlags>>;
};
