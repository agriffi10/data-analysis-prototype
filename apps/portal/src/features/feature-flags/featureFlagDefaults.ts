import type {FeatureFlagKey, FeatureFlags} from './featureFlags.types';

/**
 * Every flag key, in one iterable place.
 *
 * The resolver walks THIS list rather than the document's keys, which is what guarantees a
 * resolved set holds all four whatever the document said — including a document that names
 * none of them.
 */
export const FEATURE_FLAG_KEYS: readonly FeatureFlagKey[] = ['files', 'query', 'sharedWorkspaces', 'dataQuality'];

/**
 * What is in force when the document cannot be used: everything on.
 *
 * ALL-ON IS THE ONLY DEFENSIBLE FALLBACK, and it carries an accepted cost worth naming.
 * A flag is presentation, so an unreadable document must never take a feature away from a
 * user who has permission to use it — the app degrading into a smaller app because an S3
 * read failed would be a worse outcome than the flag not taking effect. The cost: during
 * an outage, a deliberate "off" does not apply. That is accepted rather than hidden, and
 * `'fallback'` plus the dev diagnostic is how it is made visible to the people who can act
 * on it.
 *
 * A test asserts this matches `config/feature-flags.json`'s `defaults` block, so the file
 * and the fallback cannot drift apart silently.
 */
export const FEATURE_FLAG_DEFAULTS: FeatureFlags = {
  files: true,
  query: true,
  sharedWorkspaces: true,
  dataQuality: true
};
