/** The document SPEC-146's daily builder publishes to `_directory/usernames.json`. */
export type UserDirectoryDocument = {
  version: number;
  generatedAt: string;
  count: number;
  usernames: string[];
};

/** What the service returns. */
export type UserDirectory = {
  usernames: string[];
  /** null when the directory is unavailable or empty. */
  generatedAt: string | null;
};

/**
 * What consumers branch on.
 *
 * `'unavailable'` deliberately collapses "the fetch errored" and "the document is empty":
 * from a consumer's point of view those are the same situation — there are no suggestions to
 * offer — and collapsing them here means no consumer has to remember to handle both.
 */
export type UserDirectoryStatus = 'loading' | 'ready' | 'unavailable';

/** Which band a result came from. Consumers use it to explain a match, never to filter one. */
export type UsernameSearchResult = {
  username: string;
  match: 'exact' | 'prefix' | 'substring';
};

type TrieNode = {children: Record<string, TrieNode>; terminal: boolean};

/**
 * Internal to `usernameTrie.ts`. Consumers never hold one — {@link useUserDirectory} hands out
 * a `search` callback instead, which is what makes the lazy build invisible.
 */
export type UsernameIndex = {
  root: TrieNode;
  /** The substring band's scan target. Sorted ascending, so its results come out ordered. */
  ordered: readonly string[];
  size: number;
  /** True when the input exceeded {@link MAX_INDEXED_USERNAMES} and was cut. */
  truncated: boolean;
};

export type {TrieNode};
