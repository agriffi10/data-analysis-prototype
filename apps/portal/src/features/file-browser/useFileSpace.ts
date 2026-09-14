import {useCallback, useMemo} from 'react';
import {useSearchParams} from 'react-router';
import {isConnectionUsable} from '../connections/connection.types';
import type {Connection} from '../connections/connection.types';

// the file browser's active "space" — derived from a
// `Connection`. Selecting a space points the browser at that
// space's bucket + root prefix; personal → the user-space bucket at `{username}/`,
// shared → `dat-prod-shared-space/{name}/`. `label` is the root breadcrumb crumb
// AND the marker-owner segment (the personal marker lives at `{username}/…`, a
// shared one at `{name}/…`), so the delete/move/copy marker guard keys off it.
export type FileSpaceKind = 'personal' | 'shared';

export type FileSpaceTarget = {
  id: string; // connection id: 'personal' | the shared-space name
  bucket: string;
  rootPrefix: string; // '{username}/' | '{name}/'
  kind: FileSpaceKind;
  label: string; // username | shared name
};

export type UseFileSpaceParams = {
  username: string | null;
  connections: Connection[];
  // True while the connections cache is still loading — suppresses the
  // vanished-space notice so a valid shared deep-link doesn't flash a fallback
  // before the cache resolves.
  isLoading: boolean;
  userSpaceBucket: string | undefined;
  sharedSpaceBucket: string | undefined;
  /**
   * Resolve to the personal space and ignore `?space=` entirely.
   *
   * Set while the `sharedWorkspaces` flag is off. Deliberately NOT the same thing as a
   * space that cannot be resolved: this reports `fellBack: false`, so no banner claims the
   * space is unavailable — it is available, this build just does not offer shared spaces.
   * `useConnections` still resolves normally, because a flag may not touch a service.
   */
  ignoreSpaceParam?: boolean;
};

export type UseFileSpaceResult = {
  // null only when the bucket env / username needed to target the space is
  // missing — the page surfaces its existing configuration-error UI.
  space: FileSpaceTarget | null;
  activeSpaceId: string;
  selectSpace: (id: string) => void;
  // True when the URL named a space the user can't browse (gone/revoked/not-yet-
  // active) and we fell back to the personal space — drives a non-blocking notice
  // Dismissing clears the stale `?space=` param.
  fellBack: boolean;
  dismissFellBack: () => void;
};

// Derive the browser target for a connection. Returns null when the bucket it
// needs isn't configured (personal → user-space bucket; shared → shared bucket).
function connectionToSpaceTarget(
  conn: Connection,
  username: string,
  userSpaceBucket: string | undefined,
  sharedSpaceBucket: string | undefined
): FileSpaceTarget | null {
  if (conn.kind === 'personal') {
    if (!userSpaceBucket) return null;
    return {
      id: 'personal',
      bucket: userSpaceBucket,
      rootPrefix: `${username}/`,
      kind: 'personal',
      label: username
    };
  }
  if (!sharedSpaceBucket) return null;
  // `database` (→ rootPrefix) and `label` (→ root crumb + marker owner) must name
  // the same space; `useConnections` sets both to the shared name, so they stay in
  // sync — keep it that way or the prefix and marker key would silently diverge.
  return {
    id: conn.id,
    bucket: sharedSpaceBucket,
    rootPrefix: `${conn.database}/`,
    kind: 'shared',
    label: conn.label
  };
}

/**
 * All usable connections as browser targets (feedback 2026-06-30) — the personal
 * space plus every active shared space. Used to populate the move/copy destination
 * picker so files can be relocated across connections. Unusable shared spaces
 * (provisioning/failed/leaving) are excluded, matching the sidebar.
 */
export function usableSpaceTargets(
  connections: Connection[],
  username: string | null,
  userSpaceBucket: string | undefined,
  sharedSpaceBucket: string | undefined
): FileSpaceTarget[] {
  if (!username) return [];
  return connections
    .filter(isConnectionUsable)
    .map((c) => connectionToSpaceTarget(c, username, userSpaceBucket, sharedSpaceBucket))
    .filter((t): t is FileSpaceTarget => t !== null);
}

/**
 * the file browser's active-space state, derived
 * from `useConnections` and synced to the `?space=` route param.
 * Selection flows through the URL so a deep-link (`/files?space=…&prefix=…`) and a
 * sidebar click are one mechanism, and a vanished/unusable space reconciles to the
 * personal space purely during render.
 *
 * @example
 * const {space, destinations} = useFileSpace({username, connections, isLoading, userSpaceBucket, sharedSpaceBucket});
 */
export function useFileSpace({
  username,
  connections,
  isLoading,
  userSpaceBucket,
  sharedSpaceBucket,
  ignoreSpaceParam = false
}: UseFileSpaceParams): UseFileSpaceResult {
  const [searchParams, setSearchParams] = useSearchParams();
  // With shared workspaces off the parameter is not resolved-and-refused,
  // it is NOT READ. That distinction is the whole requirement — routing it through the
  // `fellBack` path below would raise "That shared space is no longer available", which is a
  // false statement about a space that is perfectly fine and that the user will see again
  // the moment the flag flips back.
  const spaceParam = ignoreSpaceParam ? null : searchParams.get('space');

  const {space, fellBack} = useMemo(() => {
    if (!username) return {space: null, fellBack: false};
    const personalConn = connections.find((c) => c.kind === 'personal') ?? null;

    // Resolve the requested shared space; fall back to personal when it's absent
    // or not yet usable (provisioning/failed/leaving). Suppress the fallback
    // notice while the cache is still loading so a valid deep-link doesn't flash.
    let targetConn: Connection | null = personalConn;
    let didFallBack = false;
    if (spaceParam) {
      const match = connections.find((c) => c.id === spaceParam) ?? null;
      if (match && isConnectionUsable(match)) {
        targetConn = match;
      } else if (!isLoading) {
        didFallBack = true;
      }
    }

    const target = targetConn
      ? connectionToSpaceTarget(targetConn, username, userSpaceBucket, sharedSpaceBucket)
      : null;
    return {space: target, fellBack: didFallBack};
  }, [username, connections, spaceParam, isLoading, userSpaceBucket, sharedSpaceBucket]);

  const selectSpace = useCallback(
    (id: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          // A space switch resets navigation to the space's root.
          next.delete('prefix');
          if (id === 'personal') next.delete('space');
          else next.set('space', id);
          return next;
        },
        {replace: false}
      );
    },
    [setSearchParams]
  );

  const dismissFellBack = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        // Drop both the stale space AND any prefix that was scoped to it, so no
        // orphaned `?prefix=` lingers once we're back in the personal space.
        next.delete('space');
        next.delete('prefix');
        return next;
      },
      {replace: true}
    );
  }, [setSearchParams]);

  return {
    space,
    activeSpaceId: space?.id ?? 'personal',
    selectSpace,
    fellBack,
    dismissFellBack
  };
}
