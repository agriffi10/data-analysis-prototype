import {useEffect, useMemo} from 'react';
import {useSearchParams} from 'react-router';
import {
  FileBrowser,
  ensurePrefixMarker,
  useFileSpace,
  usableSpaceTargets,
  type FileSpaceTarget
} from '../features/file-browser';
import {useFeatureSet} from '../features/feature-flags';
import {Sidebar} from '../features/connections/Sidebar';
import {SpacesList} from '../features/connections/SpacesList';
import {useProvideNavRail} from '../components/navRailContext';
import {Banner} from '../components/Banner';
import {useAuth} from '../features/auth';
import {useConnections} from '../features/connections/useConnections';
import {useAcknowledgeMembership} from '../features/shared-spaces';
import {usePageTitle} from '../hooks/usePageTitle';
import {spaceBuckets} from '../lib/userSpace';
import {logBackgroundFailure, toUserMessage} from '../lib/errorMessages';
import {SECTION_CAPTION} from '../components/fieldStyles';

/** The file browser page (`/files`) — browses the active space (personal by default, or a shared space picked in the Sidebar / `?space=`). */
export default function FilesPage() {
  const {user} = useAuth();
  usePageTitle('Files');
  const {user: userSpaceBucket, shared: sharedSpaceBucket} = spaceBuckets();

  const {connections, isLoading: connectionsLoading} = useConnections(user?.username ?? null);
  // The spaces rail and the `?space=` parameter are shared-workspace
  // surfaces. With the flag off the page shows no rail and resolves to the personal space
  // with NO notice — the deep link is ignored, not refused.
  const {isEnabled, status: flagsStatus} = useFeatureSet();
  const sharedSpacesEnabled = isEnabled('sharedWorkspaces');
  const {space, activeSpaceId, selectSpace, fellBack, dismissFellBack} = useFileSpace({
    username: user?.username ?? null,
    connections,
    isLoading: connectionsLoading,
    userSpaceBucket,
    sharedSpaceBucket,
    // Gated on the RESOLVED answer, not on `sharedSpacesEnabled` — which reads false while the
    // flags are in flight. Ignoring the parameter during that window would resolve the
    // personal space first and then swap, costing an extra ListObjectsV2 and flashing the
    // wrong space on every cold load of a shared-space deep link, in the common case where
    // the feature is ON.
    ignoreSpaceParam: flagsStatus !== 'loading' && !sharedSpacesEnabled
  });
  // a member resolving a shared space they belong to acks their membership
  // (once per session), flipping them Pending → Active in the owner's projection.
  useAcknowledgeMembership(user?.username ?? null, connections, activeSpaceId);

  // Guarantee the user's personal prefix marker exists on load. Best-effort,
  // non-blocking, personal-space-only — a shared space's marker is provisioned
  // by the control plane, not the browser. A failure only logs; the service
  // guards against repeat HEADs within a session.
  useEffect(() => {
    if (!user || !userSpaceBucket) return;
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
  // `?requestId=` — the run whose conflicts to review. Minted by a notification row's own control
  // and never by this page, so it is read and passed on rather than validated here: the view it
  // opens resolves it against the user's OWN inbox, which is the only gate that means anything.
  const requestIdParam = searchParams.get('requestId') || undefined;

  // The file-browser target comes from the active space. A null space means the user-space (or
  // shared) bucket is missing from the runtime configuration.
  const sidebarConnections = connections;
  const sidebarActiveId = activeSpaceId;
  const onSelectSpace = selectSpace;

  const target: {
    bucket: string | undefined;
    rootPrefix: string;
    rootLabel: string | undefined;
    markerOwner: string | undefined;
    writable: boolean;
  } = {
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
  // Spaces move/copy can target: personal + active shared spaces.
  // The move/copy DESTINATION list is a shared-workspace surface too, and hiding only the rail
  // would leave the write path open: the picker renders a space selector whenever it has more
  // than one option, so a user could still browse into `marketing_data` and paste a file there
  // with the feature switched off. Filtered here, at the view — `useConnections` still resolves
  // every space, and the IAM grants are untouched.
  const destinations: FileSpaceTarget[] = usableSpaceTargets(
    connections,
    user?.username ?? null,
    userSpaceBucket,
    sharedSpaceBucket
  ).filter((target) => sharedSpacesEnabled || target.kind === 'personal');

  // Below `tablet` the on-page Spaces rail is hidden; feed the same list into the
  // mobile AppNavDrawer's contextual slot so it stays reachable — and take
  // the SAME gate there, because a rail hidden on desktop and present in the hamburger is
  // the feature still being one tap away.
  const spacesRail = useMemo(
    () => (
      <div className="p-3">
        <p className={`px-3 pb-1 pt-1 ${SECTION_CAPTION}`}>Spaces</p>
        <SpacesList
          connections={sidebarConnections}
          activeSpaceId={sidebarActiveId}
          onSelectSpace={onSelectSpace}
        />
      </div>
    ),
    [sidebarConnections, sidebarActiveId, onSelectSpace]
  );
  // The gate sits OUTSIDE the memo: a `useMemo` whose body is a conditional returning JSX is
  // one the React Compiler declines to preserve, and `npm run lint` fails on it.
  useProvideNavRail(sharedSpacesEnabled ? spacesRail : null);

  const initialPrefix = prefixParam && prefixParam.startsWith(target.rootPrefix) ? prefixParam : target.rootPrefix;
  const ready = !!target.bucket && !!user;
  // Resolved inside the component, not at module scope: `toUserMessage` logs the original
  // in a dev build, so a module-level call warns about an error that has not happened on
  // every page load and in every test that imports this route.
  const spaceUnavailable = toUserMessage({code: 'SpaceUnavailable'});

  return (
    <>
      {sharedSpacesEnabled && (
        <Sidebar
          connections={sidebarConnections}
          activeSpaceId={sidebarActiveId}
          onSelectSpace={onSelectSpace}
        />
      )}
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
            writable={target.writable}
            username={target.markerOwner}
            destinations={destinations}
            spaceKind={space?.kind}
            requestId={requestIdParam}
          />
        ) : (
          <div
            role="alert"
            className="rounded-lg border border-danger bg-danger-soft p-4 text-danger">
            <p className="font-medium">{spaceUnavailable.title}</p>
            <p className="mt-1 text-sm">{spaceUnavailable.message}</p>
          </div>
        )}
      </main>
    </>
  );
}
