import {useAuth} from '../features/auth';
import {HelpLink} from '../features/help';
import {NotificationsBell, useNotifications} from '../features/notifications';
import {BrandMark} from './BrandMark';
import {Button} from './Button';
import {PrimaryNav} from './PrimaryNav';

/**
 * Persistent auth-aware top bar: brand mark, primary tabs (authenticated only),
 * notifications bell, and sign-in/out controls.
 *
 * @example
 * <Header />
 */
export function Header() {
  const {status, user, error, signIn, signOut} = useAuth();

  // Mounting the notifications hook in the always-present shell activates the
  // 60s background poll + prefetched read, so the bell's unread indicator is
  // correct on first paint and refreshes without a navigation. Disabled (no
  // read) when signed out.
  const {hasUnread, unreadCount} = useNotifications(status === 'authenticated' ? (user?.username ?? null) : null);

  return (
    <header className="h-14 bg-surface border-b border-border">
      <div className="flex h-full items-center gap-4 px-4">
        <BrandMark />

        {status === 'authenticated' && <PrimaryNav />}

        <div className="flex-1" />

        <div className="flex items-center gap-3">
          {status === 'loading' && (
            <span
              className="text-sm text-text-3"
              aria-hidden="true">
              &hellip;
            </span>
          )}

          {status === 'unauthenticated' && (
            <Button
              variant="primary"
              onClick={() => void signIn()}>
              Sign in
            </Button>
          )}

          {status === 'authenticated' && user && (
            <>
              <HelpLink />
              <NotificationsBell
                hasUnread={hasUnread}
                unreadCount={unreadCount}
              />
              <span className="text-sm text-text-2">{user.username}</span>
              <div
                className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white"
                aria-hidden="true">
                {user.username.slice(0, 2).toUpperCase()}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void signOut()}>
                Sign out
              </Button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="border-t border-danger-soft bg-danger-soft px-4 py-2 text-center text-sm text-danger">
          {error}
        </div>
      )}
    </header>
  );
}
