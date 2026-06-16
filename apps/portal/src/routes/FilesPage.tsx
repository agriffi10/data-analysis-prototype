import { useEffect } from 'react';
import {
  FileBrowser,
  ensurePrefixMarker,
  prefixMarkerKey,
} from '../features/file-browser';
import { useAuth } from '../features/auth';

// Dev-only fallback (SPEC-013): browse a static/public test bucket without auth
// for local work without AWS. Honoured ONLY in a dev build (matches the service
// + ProtectedLayout guards), so production always uses the authenticated path.
const devUnauthenticated =
  import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';
const devBucket = import.meta.env.VITE_S3_BUCKET_NAME as string | undefined;
const rawDevPrefix =
  (import.meta.env.VITE_S3_ROOT_PREFIX as string | undefined) ?? '';
const devPrefix =
  rawDevPrefix && !rawDevPrefix.endsWith('/') ? `${rawDevPrefix}/` : rawDevPrefix;

const userSpaceBucket = import.meta.env.VITE_S3_USER_SPACE_BUCKET as
  | string
  | undefined;

// The file browser page (`/files`). Chrome (Header) and the auth gate live in
// ProtectedLayout — this component only renders the browser content. In the
// authenticated flow (SPEC-013) it shows the user's own space in the user-space
// bucket, rooted at `{username}/`, with the username hidden from the UI.
export default function FilesPage() {
  const { user } = useAuth();

  // Authenticated flow: scope to the user's own prefix in the user-space bucket.
  // The username is the navigation floor but never shown — the root crumb reads
  // "My Files" and the user only ever sees paths below their own prefix.
  let bucket = userSpaceBucket;
  let rootPrefix = user ? `${user.username}/` : '';
  let rootLabel: string | undefined = 'My Files';
  // The prefix marker is hidden from the listing (SPEC-014 FR-002). Only set in
  // the authenticated flow — there is no per-user prefix in the dev fallback.
  let markerKey: string | undefined = user
    ? prefixMarkerKey(user.username)
    : undefined;

  if (devUnauthenticated) {
    bucket = devBucket;
    rootPrefix = devPrefix;
    rootLabel = undefined; // dev: standard Home-rooted breadcrumb
    markerKey = undefined;
  }

  // SPEC-014 FR-001: guarantee the user's prefix marker exists on authenticated
  // load. Best-effort and non-blocking — a failure only logs a warning; the
  // browser still renders and the marker is retried next session. The service
  // guards against repeat HEADs within a session.
  useEffect(() => {
    if (devUnauthenticated || !user || !userSpaceBucket) return;
    void (async () => {
      const result = await ensurePrefixMarker({
        bucket: userSpaceBucket,
        username: user.username,
      });
      if (!result.success) {
        console.warn(
          `[prefix-marker] could not ensure marker: ${result.error.message}`,
        );
      }
    })();
  }, [user]);

  return (
    <main className="px-4 py-6">
      {bucket && (devUnauthenticated || user) ? (
        <FileBrowser
          bucket={bucket}
          prefix={rootPrefix}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          markerKey={markerKey}
          writable={!devUnauthenticated && !!user}
          username={devUnauthenticated ? undefined : user?.username}
        />
      ) : (
        <div
          role="alert"
          className="rounded-lg border border-danger bg-danger-soft p-4 text-danger"
        >
          <p className="font-medium">Configuration error</p>
          <p className="mt-1 text-sm">
            VITE_S3_USER_SPACE_BUCKET is not set. Add it to your .env file.
          </p>
        </div>
      )}
    </main>
  );
}
