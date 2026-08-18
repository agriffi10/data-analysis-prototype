/**
 * The five primary features a flag can hide. Named for the features the portal ships, not
 * for the components that render them — a flag governs an AREA, and the gating has
 * to reach every entry point into that area, not one screen.
 */
export type FeatureFlagKey = 'files' | 'query' | 'sharedWorkspaces' | 'dataQuality' | 'dataExplorer';

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
