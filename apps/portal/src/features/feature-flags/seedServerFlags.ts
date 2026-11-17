import type {QueryClient} from '@tanstack/react-query';
import {featureFlagKeys} from './featureFlagKeys';
import type {SeededFeatureFlags} from './featureFlags.types';

/**
 * Put the flag set the server sent with the page into the query cache, the one place that seed is
 * written.
 *
 * Written under the same key `useFeatureFlags` reads, and dated by when the API answered the server
 * rather than by now, so the hook's own `staleTime` decides whether the tab reads the document again:
 * a set the server held for most of an hour is re-read soon after sign-in, and a fresh one is not.
 *
 * @param client - The query client the frame was built with, before its first render.
 * @param environment - The runtime document's `environment`, which the key carries.
 * @param seeded - The set and the time the API answered it.
 */
export function seedServerFlags(
  client: QueryClient,
  environment: string | undefined,
  seeded: SeededFeatureFlags
): void {
  client.setQueryData(featureFlagKeys.resolved(environment), seeded.flags, {updatedAt: seeded.readAt});
}
