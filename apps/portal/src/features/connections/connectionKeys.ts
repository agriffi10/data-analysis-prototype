/**
 * TanStack Query keys owned by the connections feature. Split out of `queryKeys`
 * (SPEC-176 FR-005): `useConnections` importing a key from `features/query/` was a
 * shared feature reaching into a leaf one — the SPEC-155 inversion in miniature.
 */
export const connectionKeys = {
  all: ['connections'] as const,
  /** Merged personal + shared connection list; refresh-connections invalidates this key. */
  list: (username: string) => [...connectionKeys.all, 'list', username] as const
};
