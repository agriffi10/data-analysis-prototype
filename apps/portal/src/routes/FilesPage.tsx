import { FileBrowser } from '../features/file-browser';

// Env-driven bucket/prefix wiring — unchanged from the pre-router App shell
// (FR-005). Still the SPEC-002 test bucket; per-user scoping is a future spec.
const bucket = import.meta.env.VITE_S3_BUCKET_NAME as string | undefined;
const rawPrefix = (import.meta.env.VITE_S3_ROOT_PREFIX as string | undefined) ?? '';
const rootPrefix =
  rawPrefix && !rawPrefix.endsWith('/') ? `${rawPrefix}/` : rawPrefix;

// The file browser page (`/files`). Chrome (Header) and the auth gate live in
// ProtectedLayout — this component only renders the browser content.
export default function FilesPage() {
  return (
    <main className="py-8">
      <div className="mx-auto max-w-4xl px-4">
        {bucket ? (
          <>
            <h1 className="mb-6 text-2xl font-semibold text-gray-900">Files</h1>
            <FileBrowser
              bucket={bucket}
              prefix={rootPrefix}
              rootPrefix={rootPrefix}
            />
          </>
        ) : (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700"
          >
            <p className="font-medium">Configuration error</p>
            <p className="mt-1 text-sm">
              VITE_S3_BUCKET_NAME is not set. Add it to your .env file.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
