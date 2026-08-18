/** A share-request target: an existing user or an active shared space. */
export type ShareRecipient = {
  kind: 'user' | 'space';
  name: string;
};

/**
 * The enqueueTableShare input. The service attaches the caller's ID token as the
 * envelope's `actor` field (the server derives the actor from the verified claim —
 * a body username is never trusted).
 */
export type TableShareRequest = {
  /** The table being shared, fully qualified. */
  source: {database: string; table: string};
  /** Catalog-safe result table name, applied to every recipient. */
  tableName: string;
  recipients: ShareRecipient[];
};
