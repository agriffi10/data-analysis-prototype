/** How the current history entry was reached. */
export type NavigationType = 'PUSH' | 'REPLACE' | 'POP';

export type NavLocation = {
  pathname: string;
  /** The query string as the address carries it, never re-serialized. */
  search: string;
  hash: string;
  /** What the navigation that made this entry carried; never read back from history. */
  state: unknown;
  /** Fresh per push or replace; the same on a traversal back; 'default' for an entry with none. */
  key: string;
};

/** A navigation target: a path, optionally with a query and a hash, or its parts. */
export type To = string | {pathname?: string; search?: string; hash?: string};

export type NavigateOptions = {replace?: boolean; state?: unknown};
