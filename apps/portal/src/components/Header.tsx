import {useId, useState} from 'react';
import {useAuth} from '../features/auth';
import {HelpLink} from '../features/help';
import {NotificationsBell, useNotifications} from '../features/notifications';
import {useIsMobile} from '../lib/useBreakpoint';
import {AppNavDrawer} from './AppNavDrawer';
import {BrandMark} from './BrandMark';
import {Button} from './Button';
import {useNavRailContent} from './navRailContext';
import {PrimaryNav} from './PrimaryNav';

/**
 * Persistent auth-aware top bar: brand mark, primary tabs (authenticated only;
 * a hamburger opening `AppNavDrawer` below `tablet`), notifications bell, and
 * sign-in/out controls.
 *
 * @example
 * <Header />
 */
export function Header() {
  const {status, user, error, signIn, signOut} = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  const isMobile = useIsMobile();
  const navDrawerId = useId();
  const contextualRail = useNavRailContent();

  // Mounting the notifications hook in the always-present shell activates the
  // 60s background poll + prefetched read, so the bell's unread indicator is
  // correct on first paint and refreshes without a navigation. Disabled (no
  // read) when signed out.
  const {hasUnread, unreadCount} = useNotifications(status === 'authenticated' ? (user?.username ?? null) : null);

  const authed = status === 'authenticated' && !!user;

  return (
    <header className="h-14 bg-surface border-b border-border">
      <div className="flex h-full items-center gap-4 px-4">
        {authed && (
          <button
            type="button"
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls={navOpen ? navDrawerId : undefined}
            onClick={() => setNavOpen(true)}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent tablet:hidden">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-5 w-5"
              aria-hidden="true">
              <path
                strokeLinecap="round"
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
        )}

        <BrandMark />

        {authed && (
          <div className="hidden h-full tablet:flex">
            <PrimaryNav />
          </div>
        )}

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

          {authed && (
            <>
              <HelpLink />
              <NotificationsBell
                hasUnread={hasUnread}
                unreadCount={unreadCount}
              />
              <span className="hidden text-sm text-text-2 tablet:inline">{user.username}</span>
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

      {authed && isMobile && (
        <AppNavDrawer
          id={navDrawerId}
          open={navOpen}
          onClose={() => setNavOpen(false)}
          contextualRail={contextualRail}
        />
      )}

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
