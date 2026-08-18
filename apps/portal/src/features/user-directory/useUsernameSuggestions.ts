import {useMemo} from 'react';
import {useUserDirectory} from './useUserDirectory';
import type {SuggestionSource} from './userDirectory.types';

/**
 * The published username directory as a {@link SuggestionSource}.
 *
 * Thin on purpose. The combobox's data source is a prop so a second source could
 * exist; this hook is what keeps that lift behaviour-neutral for the two consumers that were
 * already suggesting usernames — they gained a prop, not a decision.
 *
 * `useUserDirectory` stays the public hook: it also reports `generatedAt`, which this shape has
 * no place for and a caller may still want.
 *
 * @returns The directory's `status` and `search`, with a stable object identity.
 *
 * @example
 * <UsernameCombobox {...useUsernameSuggestions()} label="Usernames" … />
 */
export function useUsernameSuggestions(): SuggestionSource {
  const {status, search} = useUserDirectory();
  return useMemo(() => ({status, search}), [status, search]);
}
