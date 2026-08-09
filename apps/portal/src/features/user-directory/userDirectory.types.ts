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

/**
 * What a suggestion field needs from whatever is suggesting: a status to branch on and a search
 * callback. Named for the ROLE rather than for the username directory, because SPEC-158 gave the
 * combobox a second source — the signed-in user's own shared spaces — and the two are
 * interchangeable from the field's point of view.
 *
 * `status` uses the same three-state vocabulary either way, deliberately: a consumer branching on
 * it has one rule to learn, and the reason `'unavailable'` collapses errored-and-empty holds for
 * both sources.
 */
export type SuggestionSource = {
  status: UserDirectoryStatus;
  /** Stable across renders; returns `[]` unless `status === 'ready'`. */
  search: (query: string, limit?: number) => UsernameSearchResult[];
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
