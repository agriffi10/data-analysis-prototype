import type {TrieNode, UsernameIndex, UsernameSearchResult} from './userDirectory.types';

/**
 * Above this many usernames the index is built from the first N and the overflow is warned
 * about. The cap exists so that the day this outgrows a client-side index it SAYS SO, instead
 * of quietly becoming slow — which is the failure mode a search box hides best.
 */
export const MAX_INDEXED_USERNAMES = 20_000;

/** Default result count. Eight fits a dropdown without scrolling on a phone. */
const DEFAULT_LIMIT = 8;

function emptyNode(): TrieNode {
  return {children: {}, terminal: false};
}

/**
 * Build the search index: a character trie for the prefix band, plus the flat ordered array
 * the substring band scans.
 *
 * Both structures come out of ONE walk of the input. The published document is a flat sorted
 * array precisely so the browser can choose its own shape here — shipping a
 * serialised trie would have made the artifact several times larger, unreadable to a human
 * debugging it, and coupled to this one consumer.
 *
 * @param usernames - Raw usernames. Duplicates are collapsed; order is not trusted.
 */
export function buildIndex(usernames: string[]): UsernameIndex {
  const truncated = usernames.length > MAX_INDEXED_USERNAMES;
  const source = truncated ? usernames.slice(0, MAX_INDEXED_USERNAMES) : usernames;

  const root = emptyNode();
  const unique = new Set<string>();
  for (const username of source) {
    if (unique.has(username)) continue;
    unique.add(username);
    let node = root;
    for (const character of username) {
      node = node.children[character] ?? (node.children[character] = emptyNode());
    }
    node.terminal = true;
  }

  return {
    root,
    // Sorted here so the substring band's linear scan emits ascending order for free, rather
    // than collecting and re-sorting on every keystroke.
    ordered: [...unique].sort(),
    size: unique.size,
    truncated
  };
}

/** Walk to the node ending `query`, counting nodes visited. `node` is null when absent. */
function descend(index: UsernameIndex, query: string): {node: TrieNode | null; visited: number} {
  let node: TrieNode | undefined = index.root;
  let visited = 1;
  for (const character of query) {
    node = node.children[character];
    if (!node) return {node: null, visited};
    visited += 1;
  }
  return {node, visited};
}

/**
 * Depth-first collection of every terminal under `node`, ascending alphabetically.
 *
 * Children are visited in sorted key order, so the traversal emits results already ordered and
 * can stop the moment `limit` is reached — which is what keeps a one-character query in a large
 * directory cheap rather than merely correct.
 */
function collect(
  node: TrieNode,
  prefix: string,
  limit: number,
  skip: string | null,
  out: string[],
  stats: {visited: number}
): void {
  if (out.length >= limit) return;
  if (node.terminal && prefix !== skip) out.push(prefix);
  for (const character of Object.keys(node.children).sort()) {
    if (out.length >= limit) return;
    stats.visited += 1;
    collect(node.children[character], prefix + character, limit, skip, out, stats);
  }
}

/** What {@link searchWithCost} reports alongside its results. */
export type SearchCost = {
  results: UsernameSearchResult[];
  /** Trie nodes touched by the prefix band. */
  nodesVisited: number;
  /** Entries the substring band read. 0 when the band was skipped entirely. */
  namesScanned: number;
};

/**
 * {@link search}, plus what it cost.
 *
 * Exported for the cost assertions in `usernameTrie.test.ts` and for nothing else. The two
 * bands have genuinely different complexity — one walks, one scans — and a claim about that is
 * worth pinning with a number rather than a comment. `search` is the API consumers use.
 */
export function searchWithCost(index: UsernameIndex, query: string, limit = DEFAULT_LIMIT): SearchCost {
  const normalized = query.trim().toLowerCase();
  // An empty query returns nothing rather than everything: the component must not open a menu
  // of the whole organisation on focus.
  if (!normalized || limit <= 0) return {results: [], nodesVisited: 0, namesScanned: 0};

  const results: UsernameSearchResult[] = [];
  const seen = new Set<string>();

  const {node, visited} = descend(index, normalized);
  let nodesVisited = visited;

  if (node) {
    // The exact match leads, and is then skipped by the prefix collection below so it cannot
    // appear twice.
    const isExact = node.terminal;
    if (isExact) {
      results.push({username: normalized, match: 'exact'});
      seen.add(normalized);
    }
    const prefixMatches: string[] = [];
    const stats = {visited: 0};
    collect(node, normalized, limit - results.length, isExact ? normalized : null, prefixMatches, stats);
    nodesVisited += stats.visited;
    for (const username of prefixMatches) {
      if (seen.has(username)) continue;
      seen.add(username);
      results.push({username, match: 'prefix'});
    }
  }

  // THE SUBSTRING BAND IS A LINEAR SCAN, and saying so is the honest thing: no structure built
  // in a single pass over the input answers arbitrary substring queries sub-linearly, and
  // pretending otherwise would set up a performance claim this code cannot keep. What bounds it
  // is that it short-circuits at `limit` and is SKIPPED ENTIRELY when the prefix band already
  // filled it — so the common case, someone typing a real prefix, never pays for it.
  let namesScanned = 0;
  if (results.length < limit) {
    for (const username of index.ordered) {
      namesScanned += 1;
      if (seen.has(username) || !username.includes(normalized)) continue;
      seen.add(username);
      results.push({username, match: 'substring'});
      if (results.length >= limit) break;
    }
  }

  return {results, nodesVisited, namesScanned};
}

/**
 * Search the index, best matches first.
 *
 * Ordering is deterministic and specified, because "the right person was third in the list" is
 * the complaint this feature generates: the exact match if there is one, then prefix matches
 * ascending alphabetically, then substring matches ascending alphabetically. A username appears
 * at most once, in its strongest band.
 *
 * A query containing a character no username can hold still searches — matching nothing —
 * rather than throwing. There is no minimum length: in a small directory one character is a
 * useful filter, and a minimum is a rule users have to discover.
 *
 * @param index - Built by {@link buildIndex}.
 * @param query - Raw user input; trimmed and lowercased here.
 * @param limit - Maximum results, default 8.
 *
 * @example
 * search(buildIndex(['bob', 'bob_smith', 'robert']), 'bob') // bob (exact), bob_smith (prefix)
 */
export function search(index: UsernameIndex, query: string, limit = DEFAULT_LIMIT): UsernameSearchResult[] {
  return searchWithCost(index, query, limit).results;
}
