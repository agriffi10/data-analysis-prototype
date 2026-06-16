import { Navigate } from 'react-router-dom';
import { useAuth } from '../features/auth';
import { takeReturnPath } from '../lib/returnPath';
import { BrandMark } from '../components/BrandMark';
import { Button } from '../components/Button';

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
        {/* Brand mark (shared with the Header) — SPEC-028. */}
        <div className="mb-8 flex justify-center">
          <BrandMark size="md" />
        </div>

        <p className="text-sm text-text-2">
          Securely upload and download files in your personal S3 space.
        </p>

        <div className="mt-8 flex flex-col items-center gap-3">
          <Button
            variant="primary"
            onClick={() => void signIn()}
            className="w-full max-w-[200px]"
          >
            Sign in
          </Button>
          <Button
            variant="default"
            onClick={() => signUp()}
            className="w-full max-w-[200px]"
          >
            Create account
          </Button>
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
