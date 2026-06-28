import {useAuth} from '../features/auth';
import {NotificationsBell, useNotifications} from '../features/notifications';
import {BrandMark} from './BrandMark';
import {Button} from './Button';
import {PrimaryNav} from './PrimaryNav';

export function Header() {
  const {status, user, error, signIn, signOut} = useAuth();

  // SPEC-060 FR-001: the bell's unread indicator reads the SPEC-059 hook. Mounted
  // here in the always-present authenticated shell, this also activates the 60s
  // background poll + prefetched read so the indicator is correct on first paint
  // and refreshes without a navigation. Disabled (no read) when signed out.
  const {hasUnread, unreadCount} = useNotifications(status === 'authenticated' ? (user?.username ?? null) : null);

  return (
    <header className="h-14 bg-surface border-b border-border">
      <div className="flex h-full items-center gap-4 px-4">
        <BrandMark />

        {/* Primary tabs (Files | Query) — authenticated shell only (FR-001). */}
        {status === 'authenticated' && <PrimaryNav />}

        <div className="flex-1" />

        {/* User zone */}
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
