import {useCallback, useState} from 'react';
import {readSavedQuerySpaceId, writeSavedQuerySpaceId} from './savedQuerySpace';
import type {QuerySpace} from '../catalog/catalog.types';

export type UseSavedQuerySpaceResult = {
  /** The resolved space — never null while at least one space exists. */
  space: QuerySpace | null;
  spaces: QuerySpace[];
  selectSpace: (spaceId: string) => void;
};

/**
 * Which space the saved-queries surfaces read from.
 *
 * The selection is the DRAWER's state, not the workspace's: it does not change which
 * database a query runs against and it does not touch the schema rail.
 *
 * The spaces are handed in rather than read from `useQuerySpaces` so the caller can
 * apply the `sharedWorkspaces` gate at the view without this hook — or the
 * service beneath it — learning about feature flags. A remembered space the user no
 * longer belongs to, or that a flag has since hidden, resolves through the same
 * fallback: it is not in the list, so the personal space wins.
 *
 * @param username - The signed-in user, for the per-user sessionStorage key.
 * @param spaces - The offerable spaces, personal first.
 * @returns The resolved space, the list to render, and the setter that remembers.
 */
export function useSavedQuerySpace(username: string | null, spaces: QuerySpace[]): UseSavedQuerySpaceResult {
  const [chosenId, setChosenId] = useState<string | null>(() => readSavedQuerySpaceId(username));

  // Resolve every render rather than storing a space object: `spaces` changes identity
  // when a connection resolves, and a stored object would go stale behind it. An id that
  // names nothing in the current list falls back to the first space (personal).
  const space = spaces.find((s) => s.id === chosenId) ?? spaces[0] ?? null;

  const selectSpace = useCallback(
    (spaceId: string) => {
      setChosenId(spaceId);
      writeSavedQuerySpaceId(username, spaceId);
    },
    [username]
  );

  return {space, spaces, selectSpace};
}
