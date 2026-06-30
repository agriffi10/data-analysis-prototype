import {useEffect} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  FileBrowser,
  ensurePrefixMarker,
  prefixMarkerKey,
  useFileSpace,
  usableSpaceTargets,
  type FileSpaceTarget
} from '../features/file-browser';
import {Sidebar} from '../components/Sidebar';
import {Banner} from '../components/Banner';
import {useAuth} from '../features/auth';
import {useConnections} from '../features/query/useConnections';
import type {Connection} from '../features/query/query.types';
import {usePageTitle} from '../hooks/usePageTitle';

// Dev-only fallback (SPEC-013): browse a static/public test bucket without auth
// for local work without AWS. Honoured ONLY in a dev build (matches the service
// + ProtectedLayout guards), so production always uses the authenticated path.
const devUnauthenticated = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';
const devBucket = import.meta.env.VITE_S3_BUCKET_NAME as string | undefined;
const rawDevPrefix = (import.meta.env.VITE_S3_ROOT_PREFIX as string | undefined) ?? '';
const devPrefix = rawDevPrefix && !rawDevPrefix.endsWith('/') ? `${rawDevPrefix}/` : rawDevPrefix;

const userSpaceBucket = import.meta.env.VITE_S3_USER_SPACE_BUCKET as string | undefined;
const sharedSpaceBucket = import.meta.env.VITE_S3_SHARED_SPACE_BUCKET as string | undefined;

// A single synthetic space for the dev-unauth path — the spaces concept doesn't
// apply without auth, but the Sidebar still renders one entry for layout parity.
const devConnections: Connection[] = [{id: 'personal', label: 'Files', database: '', kind: 'personal'}];

// The file browser page (`/files`). Chrome (Header) and the auth gate live in
// ProtectedLayout — this component only renders the browser content. SPEC-057: the
// Sidebar lists the user's spaces (personal + active shared connections); selecting
// one points the browser at that space's bucket + root prefix. The personal space
// is the default (SPEC-013, unchanged): the user-space bucket rooted at
// `{username}/`. Shared spaces browse `dat-prod-shared-space/{name}/` under the
// SPEC-056 membership-slot IAM.
export default function FilesPage() {
  const {user} = useAuth();
  usePageTitle('Files');

  // SPEC-052 source of spaces; SPEC-057 active-space + `?space=` routing. Hooks run
  // unconditionally; the dev-unauth path below overrides the targets directly.
  const {connections, isLoading: connectionsLoading} = useConnections(user?.username ?? null);
  const {space, activeSpaceId, selectSpace, fellBack, dismissFellBack} = useFileSpace({
    username: user?.username ?? null,
    connections,
    isLoading: connectionsLoading,
    userSpaceBucket,
    sharedSpaceBucket
  });

  // SPEC-014 FR-001: guarantee the user's personal prefix marker exists on load.
  // Best-effort, non-blocking, personal-space-only — a shared space's marker is
  // provisioned by the pipeline (SPEC-050/056), not the browser. A failure only
  // logs; the service guards against repeat HEADs within a session.
  useEffect(() => {
    if (devUnauthenticated || !user || !userSpaceBucket) return;
    void (async () => {
      const result = await ensurePrefixMarker({bucket: userSpaceBucket, username: user.username});
      if (!result.success) {
        console.warn(`[prefix-marker] could not ensure marker: ${result.error.message}`);
      }
    })();
  }, [user]);

  // SPEC-044/057 FR-004: a `/files?space=…&prefix=…` deep-link seeds the browser.
  // The prefix is honoured only when it's within the resolved space's root (the
  // navigation floor), so the param can never point outside it.
  const [searchParams] = useSearchParams();
  const prefixParam = searchParams.get('prefix') || undefined;

  // Authenticated flow: the file-browser target comes from the active space. A
  // null space means the user-space (or shared) bucket env is missing.
  let target: {
    bucket: string | undefined;
    rootPrefix: string;
    rootLabel: string | undefined;
    markerOwner: string | undefined;
    writable: boolean;
  };
  let sidebarConnections: Connection[];
  let sidebarActiveId: string;
  let onSelectSpace: (id: string) => void;
  // Connections move/copy can target (feedback 2026-06-30): personal + active
  // shared spaces. Undefined in dev-unauth (read-only — the dialogs never open).
  let destinations: FileSpaceTarget[] | undefined;

  if (devUnauthenticated) {
    target = {bucket: devBucket, rootPrefix: devPrefix, rootLabel: undefined, markerOwner: undefined, writable: false};
    sidebarConnections = devConnections;
    sidebarActiveId = 'personal';
    onSelectSpace = () => {};
    destinations = undefined;
  } else {
    target = {
      bucket: space?.bucket,
      rootPrefix: space?.rootPrefix ?? '',
      // The user chose to surface the space name (incl. the username for the
      // personal space) as the root breadcrumb crumb.
      rootLabel: space?.label,
      // The marker owner = the space's root segment: the username for the personal
      // space, the shared-space name for a shared space — so the delete/move/copy
      // marker guard protects `{root}/DO_NOT_DELETE.txt` (SPEC-014/056).
      markerOwner: space?.label,
      writable: !!user
    };
    sidebarConnections = connections;
    sidebarActiveId = activeSpaceId;
    onSelectSpace = selectSpace;
    destinations = usableSpaceTargets(connections, user?.username ?? null, userSpaceBucket, sharedSpaceBucket);
  }

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

        {/* SPEC-057 FR-004/FR-005: a `?space=` we can't resolve (gone/revoked/not-
            yet-active) falls back to the personal space — surfaced non-blockingly. */}
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
