// Types for the `.sql` store (SPEC-173, moved out of `features/query/` by SPEC-177). The
// space a query is written into is a `QuerySpace` from `features/catalog/`.

/**
 * One `.sql` object in a space's `saved_queries/` folder.
 *
 * The key IS the identity and the filename IS the name — there is no id and no record,
 * because a `.sql` file cannot carry one without a sidecar this feature deliberately
 * does not have.
 */
export type SavedQuery = {
  spaceId: string;
  bucket: string;
  /** `{rootPrefix}saved_queries/{name}.sql` */
  key: string;
  /** The filename without its `.sql` suffix. */
  name: string;
  /** S3 LastModified, ISO 8601. */
  updatedAt: string;
  /** Object size in bytes. */
  size: number;
};

/** One `ListObjectsV2` page of a space's saved queries, in S3's own (lexicographic) order. */
export type SavedQueryPage = {
  queries: SavedQuery[];
  isTruncated: boolean;
  nextContinuationToken?: string;
};

/** What a caller remembers about the saved query its buffer was opened from. */
export type SavedQueryLink = {
  spaceId: string;
  bucket: string;
  key: string;
  name: string;
};
