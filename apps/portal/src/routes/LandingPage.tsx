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
    <div className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm text-center">
        {/* Brand mark — rounded accent square + wordmark. Mirrors the Header
            mark (SPEC-023); extracted into a shared BrandMark in SPEC-028. */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4 text-white"
              aria-hidden="true"
            >
              <path d="M12 16V4M7 9l5-5 5 5" />
              <path d="M5 20h14" />
            </svg>
          </div>
          <span className="text-md font-semibold text-text">S3 File Portal</span>
        </div>

        <p className="text-sm text-text-2">
          Securely upload and download files in your personal S3 space.
        </p>

        <div className="mt-8 flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={() => void signIn()}
            className="h-9 w-full max-w-[200px] rounded-md bg-accent px-4 text-base font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45"
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => signUp()}
            className="h-9 w-full max-w-[200px] rounded-md border border-border bg-surface px-4 text-base font-medium text-text hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45"
          >
            Create account
          </button>
        </div>
        {/* Username guidance — mirrors the SPEC-012 pre-signup rule exactly,
            since the username becomes the user's S3 prefix and audit identity. */}
        <p className="mt-4 text-xs leading-relaxed text-text-3">
          Your username becomes your private file space: 3&ndash;64 characters,
          letters and numbers plus{' '}
          <code className="rounded-sm border border-border bg-surface-2 px-1 font-mono text-xs">
            . _ @ -
          </code>{' '}
          only.
        </p>
      </div>
    </div>
  );
}
