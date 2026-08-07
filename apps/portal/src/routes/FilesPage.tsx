import {useEffect, useMemo} from 'react';
import {useSearchParams} from 'react-router';
import {
  FileBrowser,
  ensurePrefixMarker,
  prefixMarkerKey,
  useFileSpace,
  usableSpaceTargets,
  type FileSpaceTarget
} from '../features/file-browser';
import {Sidebar} from '../features/connections/Sidebar';
import {SpacesList} from '../features/connections/SpacesList';
import {useProvideNavRail} from '../components/navRailContext';
import {Banner} from '../components/Banner';
import {useAuth} from '../features/auth';
import {useConnections} from '../features/connections/useConnections';
import {useAcknowledgeMembership} from '../features/shared-spaces';
import type {Connection} from '../features/connections/connection.types';
import {usePageTitle} from '../hooks/usePageTitle';
import {spaceBuckets} from '../lib/userSpace';
import {logBackgroundFailure} from '../lib/errorMessages';

// Dev-only fallback: browse a static/public test bucket without auth for local
// work without AWS. Honoured ONLY in a dev build (matches the service +
// ProtectedLayout guards), so production always uses the authenticated path.
const devUnauthenticated = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';
const devBucket = import.meta.env.VITE_S3_BUCKET_NAME as string | undefined;
const rawDevPrefix = (import.meta.env.VITE_S3_ROOT_PREFIX as string | undefined) ?? '';
const devPrefix = rawDevPrefix && !rawDevPrefix.endsWith('/') ? `${rawDevPrefix}/` : rawDevPrefix;

// A single synthetic space for the dev-unauth path — the spaces concept doesn't
// apply without auth, but the Sidebar still renders one entry for layout parity.
const devConnections: Connection[] = [{id: 'personal', label: 'Files', database: '', kind: 'personal'}];

// Stable no-op for the dev-unauth space selector, so the memoized mobile nav rail
// (useProvideNavRail) keeps a stable identity and doesn't churn the drawer content.
const noopSelect = () => {};

/** The file browser page (`/files`) — browses the active space (personal by default, or a shared space picked in the Sidebar / `?space=`). */
export default function FilesPage() {
  const {user} = useAuth();
  usePageTitle('Files');
  const {user: userSpaceBucket, shared: sharedSpaceBucket} = spaceBuckets();

  // Hooks run unconditionally; the dev-unauth path below overrides the targets.
  const {connections, isLoading: connectionsLoading} = useConnections(user?.username ?? null);
  const {space, activeSpaceId, selectSpace, fellBack, dismissFellBack} = useFileSpace({
    username: user?.username ?? null,
    connections,
    isLoading: connectionsLoading,
    userSpaceBucket,
    sharedSpaceBucket
  });
  // SPEC-073: a member resolving a shared space they belong to acks their membership
  // (once per session), flipping them Pending → Active in the owner's projection.
  useAcknowledgeMembership(user?.username ?? null, connections, activeSpaceId);

  // Guarantee the user's personal prefix marker exists on load. Best-effort,
  // non-blocking, personal-space-only — a shared space's marker is provisioned
  // by the control plane, not the browser. A failure only logs; the service
  // guards against repeat HEADs within a session.
  useEffect(() => {
    if (devUnauthenticated || !user || !userSpaceBucket) return;
    void (async () => {
      const result = await ensurePrefixMarker({bucket: userSpaceBucket, username: user.username});
      if (!result.success) {
        logBackgroundFailure('prefix-marker', result.error.message);
      }
    })();
  }, [user, userSpaceBucket]);

  // A `/files?space=…&prefix=…` deep-link seeds the browser. The prefix is
  // honoured only when it's within the resolved space's root (the navigation
  // floor), so the param can never point outside it.
  const [searchParams] = useSearchParams();
  const prefixParam = searchParams.get('prefix') || undefined;

  // Authenticated flow: the file-browser target comes from the active space. A
  // null space means the user-space (or shared) bucket env is missing.
  // Sidebar/rail values as `const` (not branch-reassigned `let`) so the memoized
  // mobile nav rail below keeps a stable identity the React Compiler can preserve.
  const sidebarConnections = devUnauthenticated ? devConnections : connections;
  const sidebarActiveId = devUnauthenticated ? 'personal' : activeSpaceId;
  const onSelectSpace = devUnauthenticated ? noopSelect : selectSpace;

  const target: {
    bucket: string | undefined;
    rootPrefix: string;
    rootLabel: string | undefined;
    markerOwner: string | undefined;
    writable: boolean;
  } = devUnauthenticated
    ? {bucket: devBucket, rootPrefix: devPrefix, rootLabel: undefined, markerOwner: undefined, writable: false}
    : {
        bucket: space?.bucket,
        rootPrefix: space?.rootPrefix ?? '',
        // The space name (incl. the username for the personal space) is the root
        // breadcrumb crumb.
        rootLabel: space?.label,
        // The marker owner = the space's root segment, so the delete/move/copy
        // marker guard protects `{root}/DO_NOT_DELETE.txt`.
        markerOwner: space?.label,
        writable: !!user
      };
  // Spaces move/copy can target: personal + active shared spaces. Undefined in
  // dev-unauth (read-only — the dialogs never open).
  const destinations: FileSpaceTarget[] | undefined = devUnauthenticated
    ? undefined
    : usableSpaceTargets(connections, user?.username ?? null, userSpaceBucket, sharedSpaceBucket);

  // Below `tablet` the on-page Spaces rail is hidden; feed the same list into the
  // mobile AppNavDrawer's contextual slot so it stays reachable (SPEC-099 FR-001).
  const navRail = useMemo(
    () => (
      <div className="p-3">
        <p className="px-3 pb-1 pt-1 text-xs font-semibold uppercase tracking-[.04em] text-text-3">Spaces</p>
        <SpacesList
          connections={sidebarConnections}
          activeSpaceId={sidebarActiveId}
          onSelectSpace={onSelectSpace}
        />
      </div>
    ),
    [sidebarConnections, sidebarActiveId, onSelectSpace]
  );
  useProvideNavRail(navRail);

  const markerKey = target.markerOwner ? prefixMarkerKey(target.markerOwner) : undefined;
  const initialPrefix = prefixParam && prefixParam.startsWith(target.rootPrefix) ? prefixParam : target.rootPrefix;
  const ready = !!target.bucket && (devUnauthenticated || !!user);

  return (
    <>
      <Sidebar
        connections={sidebarConnections}
        activeSpaceId={sidebarActiveId}
        onSelectSpace={onSelectSpace}
      />
      <main
        id="main"
        className="min-w-0 flex-1 px-4 py-6">
        <h1 className="sr-only">{target.rootLabel ?? 'Files'}</h1>

        {/* A `?space=` we can't resolve (gone/revoked/not-yet-active) falls back
            to the personal space — surfaced non-blockingly. */}
        {fellBack && (
          <Banner
            variant="info"
            role="status"
            title="Switched to your files"
            onDismiss={dismissFellBack}
            className="mb-4">
            That shared space is no longer available, so we switched back to your personal files.
          </Banner>
        )}

        {ready ? (
          <FileBrowser
            key={`${sidebarActiveId}:${initialPrefix}`}
            bucket={target.bucket as string}
            prefix={initialPrefix}
            rootPrefix={target.rootPrefix}
            rootLabel={target.rootLabel}
            markerKey={markerKey}
            writable={target.writable}
            username={devUnauthenticated ? undefined : target.markerOwner}
            destinations={destinations}
            spaceKind={devUnauthenticated ? undefined : space?.kind}
          />
        ) : (
          <div
            role="alert"
            className="rounded-lg border border-danger bg-danger-soft p-4 text-danger">
            <p className="font-medium">Configuration error</p>
            <p className="mt-1 text-sm">VITE_S3_USER_SPACE_BUCKET is not set. Add it to your .env file.</p>
          </div>
        )}
      </main>
    </>
  );
}
