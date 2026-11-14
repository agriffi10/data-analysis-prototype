import 'server-only';

/** One session item. The key is a digest of the cookie, so the table never holds a usable cookie. */
export type SessionItem = {
  /** `session#` + the SHA-256 hex digest of the cookie's session id. */
  pk: string;
  idToken: string;
  refreshToken: string;
  /** Epoch seconds: the stored ID token's `exp`. */
  tokenExpiresAt: number;
  /** Epoch seconds: sign-in time plus the session's ceiling. The boundary, checked on every read. */
  sessionExpiresAt: number;
  /** Epoch seconds: the TTL attribute, equal to `sessionExpiresAt`. Hygiene, never the boundary. */
  expiresAt: number;
  /** Incremented by every token write; the compare-and-set's subject. */
  version: number;
};

/** What the sign-in cookie carries between `/auth/login` and `/auth/callback`. */
export type SignInTransaction = {
  state: string;
  codeVerifier: string;
  nonce: string;
};

/** The browser's existing user shape, which `GET /auth/session` answers. */
export type SessionUser = {username: string; email?: string};

/** The tokens a sign-in or a refresh produced, with the ID token's expiry. */
export type IssuedTokens = {idToken: string; tokenExpiresAt: number; refreshToken?: string};

/** The store the session logic runs on. The DynamoDB adapter and the test double both implement it. */
export type SessionStore = {
  /** Strongly consistent. Null for an absent item; expiry is the caller's check. */
  get(pk: string): Promise<SessionItem | null>;
  put(item: SessionItem): Promise<void>;
  /** Writes under `attribute_exists(pk) AND version = :expectedVersion`; false when that failed. */
  replaceTokens(
    pk: string,
    expectedVersion: number,
    next: Pick<SessionItem, 'idToken' | 'tokenExpiresAt'>
  ): Promise<boolean>;
  delete(pk: string): Promise<void>;
};

/** A session load's outcome. `unavailable` is a fault, never a sign-out. */
export type LoadedSession =
  {status: 'active'; pk: string; idToken: string; user: SessionUser} | {status: 'absent'} | {status: 'unavailable'};
