import './index.css';
import { FileBrowser } from './features/file-browser';
import { Header } from './components/Header';

const bucket = import.meta.env.VITE_S3_BUCKET_NAME as string | undefined;
const rawPrefix = (import.meta.env.VITE_S3_ROOT_PREFIX as string | undefined) ?? '';
const rootPrefix =
  rawPrefix && !rawPrefix.endsWith('/') ? `${rawPrefix}/` : rawPrefix;

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="py-8">
        <div className="mx-auto max-w-4xl px-4">
          {bucket ? (
            <>
              <h1 className="mb-6 text-2xl font-semibold text-gray-900">Files</h1>
              <FileBrowser bucket={bucket} prefix={rootPrefix} rootPrefix={rootPrefix} />
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
    </div>
  );
}
