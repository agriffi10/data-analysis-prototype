import { useAuth } from '../features/auth';

export function Header() {
  const { status, user, error, signIn, signOut } = useAuth();

  return (
    <header className="h-14 bg-surface border-b border-border">
      <div className="flex h-full items-center gap-4 px-4">
        {/* Brand — rounded accent square + upload-arrow mark + wordmark.
            Extracted into a shared BrandMark in SPEC-028. */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-accent">
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

        <div className="flex-1" />

        {/* User zone */}
        <div className="flex items-center gap-3">
          {status === 'loading' && (
            <span className="text-sm text-text-3" aria-hidden="true">
              &hellip;
            </span>
          )}

          {status === 'unauthenticated' && (
            <button
              type="button"
              onClick={() => void signIn()}
              className="h-9 rounded-md bg-accent px-4 text-base font-medium text-white hover:bg-accent-hover"
            >
              Sign in
            </button>
          )}

          {status === 'authenticated' && user && (
            <>
              <span className="text-sm text-text-2">{user.username}</span>
              <div
                className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white"
                aria-hidden="true"
              >
                {user.username.slice(0, 2).toUpperCase()}
              </div>
              <button
                type="button"
                onClick={() => void signOut()}
                className="h-8 rounded-md px-3 text-sm font-medium text-text-2 hover:bg-surface-2 hover:text-text"
              >
                Sign out
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="border-t border-danger-soft bg-danger-soft px-4 py-2 text-center text-sm text-danger"
        >
          {error}
        </div>
      )}
    </header>
  );
}
