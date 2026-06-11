import { useAuth } from '../features/auth';

export function Header() {
  const { status, user, error, signIn, signOut } = useAuth();

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
        <span className="font-semibold text-gray-900">S3 File Portal</span>

        <div className="flex items-center gap-3 text-sm">
          {status === 'loading' && (
            <span className="text-gray-400" aria-hidden="true">
              &hellip;
            </span>
          )}

          {status === 'unauthenticated' && (
            <button
              type="button"
              onClick={() => void signIn()}
              className="rounded-md bg-gray-900 px-3 py-1.5 font-medium text-white hover:bg-gray-700"
            >
              Sign in
            </button>
          )}

          {status === 'authenticated' && user && (
            <>
              <span className="text-gray-700">{user.username}</span>
              <button
                type="button"
                onClick={() => void signOut()}
                className="rounded-md border border-gray-300 px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
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
          className="border-t border-red-200 bg-red-50 px-4 py-2 text-center text-sm text-red-700"
        >
          {error}
        </div>
      )}
    </header>
  );
}
