/**
 * Catalog-safe identifier rule — lowercase, leading letter, then [a-z0-9_],
 * 3–63 chars total. The same rule the pre-signup Lambda enforces for usernames
 * (= S3 prefix = Glue DB name); shared so view-name validation uses one source
 * of truth, never a hand-duplicated regex.
 */
export const CATALOG_IDENTIFIER_RE = /^[a-z][a-z0-9_]{2,62}$/;

/**
 * Human-readable form of `CATALOG_IDENTIFIER_RE` — the validation-hint text shown
 * when a name fails the rule. Exported so every dialog (view / table / shared
 * connection / partition key) shows one wording, not a hand-duplicated copy
 * (SPEC-106 FR-007).
 */
export const CATALOG_IDENTIFIER_RULE =
  'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.';
