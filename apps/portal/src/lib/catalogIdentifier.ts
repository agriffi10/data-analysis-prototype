/**
 * Catalog-safe identifier rule — lowercase, leading letter, then [a-z0-9_],
 * 3–63 chars total. The same rule the pre-signup Lambda enforces for usernames
 * (= S3 prefix = Glue DB name); shared so view, table and shared-connection
 * name validation uses one source of truth, never a hand-duplicated regex.
 * Mirrors `cpcommon.config.CATALOG_IDENTIFIER_RE`, and a Python test holds the two equal.
 */
export const CATALOG_IDENTIFIER_RE = /^[a-z][a-z0-9_]{2,62}$/;

/**
 * Human-readable form of `CATALOG_IDENTIFIER_RE` — the validation-hint text shown
 * when a name fails the rule. Exported so every dialog (view / table / shared
 * connection) shows one wording, not a hand-duplicated copy.
 */
export const CATALOG_IDENTIFIER_RULE =
  'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.';

/**
 * Partition-key name rule — the catalog identifier alphabet and ceiling, from one
 * character. Hive-partitioned folders are routinely named `dt=`, `hr=` or `d=`,
 * and a key must match its folder; the three-character floor belongs to usernames,
 * not to anything Glue or Athena requires. A separate rule, so a two-character
 * table name is still refused. Mirrors `cpcommon.config.PARTITION_KEY_NAME_RE`.
 */
export const PARTITION_KEY_NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;

/** Human-readable form of `PARTITION_KEY_NAME_RE`, shown on a partition-key row. */
export const PARTITION_KEY_NAME_RULE =
  'Use 1–63 characters: lowercase letters, digits, or underscore, starting with a letter.';
