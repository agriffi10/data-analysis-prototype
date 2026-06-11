import { Navigate } from 'react-router-dom';
import { useAuth } from '../features/auth';
import { takeReturnPath } from '../lib/returnPath';

// Public landing page (`/`). Renders no S3 data and makes no S3 calls — it only
// explains the portal and offers sign-in via the SPEC-007 auth context.
export default function LandingPage() {
  const { status, signIn, signUp } = useAuth();

  // An authenticated visitor never sees the landing page — send them to the
  // route they originally requested (FR-004), or to /files by default (FR-002).
  if (status === 'authenticated') {
    return <Navigate to={takeReturnPath() ?? '/files'} replace />;
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4">
      <div className="w-full max-w-md text-center">
        <h1 className="text-3xl font-semibold text-gray-900">S3 File Portal</h1>
        <p className="mt-3 text-gray-600">
          Securely upload and download files in your personal S3 space.
        </p>
        <div className="mt-8 flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={() => void signIn()}
            className="w-48 rounded-md bg-gray-900 px-5 py-2.5 font-medium text-white hover:bg-gray-700"
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => signUp()}
            className="w-48 rounded-md border border-gray-300 bg-white px-5 py-2.5 font-medium text-gray-700 hover:bg-gray-50"
          >
            Create account
          </button>
        </div>
        {/* Username guidance — mirrors the SPEC-012 pre-signup rule exactly,
            since the username becomes the user's S3 prefix and audit identity. */}
        <p className="mt-4 text-xs text-gray-500">
          Your username becomes your private file space: 3&ndash;64 characters,
          letters and numbers plus <code>. _ @ -</code> only.
        </p>
      </div>
    </div>
  );
}
