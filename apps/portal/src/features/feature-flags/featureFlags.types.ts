/**
 * The features a flag can hide. Named for the features the portal ships, not
 * for the components that render them — a flag governs an AREA, and the gating has
 * to reach every entry point into that area, not one screen.
 *
 * Five of the eight are areas. The other three are deliberate exceptions: two kill switches and
 * one presentation flag.
 *
 * The kill switches exist because the only other way to stop a file-browser gesture is
 * `files: false`, which removes the entire file browser, and publishing a flag needs no app build.
 * `asyncFileOperations` is the first, over the file browser's copy/move/delete routing: off,
 * exactly one file keeps the browser's synchronous path and every other shape the routing rule
 * would send to the plane is refused at the control; on, anything that is not exactly one file is
 * handed to the control plane. `archive` is the second, over the one irreversible surface: off,
 * the Archive and Restore controls leave the file browser and the archive guide leaves Help. One
 * key covers both directions because they run on one state machine. Like every flag it is
 * presentation only — the archive and restore routes stay live and ungated.
 *
 * `resultsConversion` is neither an area nor a kill switch but a PRESENTATION flag over one
 * control: off, the Save-results dialog offers no format choice and saves the CSV it always did.
 * It takes nobody's access away — the enqueue route is live and ungated either way — so it hides
 * three options and changes what nobody may do.
 */
export type FeatureFlagKey =
  | 'files'
  | 'query'
  | 'sharedWorkspaces'
  | 'dataQuality'
  | 'dataExplorer'
  | 'asyncFileOperations'
  | 'resultsConversion'
  | 'archive';

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
