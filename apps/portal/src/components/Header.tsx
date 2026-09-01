import {useCallback, useId, useState} from 'react';
import {useAuth} from '../features/auth';
import {NAV_PATH_FLAGS, useFeatureSet} from '../features/feature-flags';
import {HelpLink} from '../features/help';
import {NotificationsBell, useNotifications} from '../features/notifications';
import {useIsMobile} from '../lib/useBreakpoint';
import {AppNavDrawer} from './AppNavDrawer';
import {BrandMark} from './BrandMark';
import {Button} from './Button';
import {useNavRailContent} from './navRailContext';
import {PrimaryNav} from './PrimaryNav';
import {ThemeMenu} from './ThemeMenu';

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

  // The header is the one place that knows both the auth state and the flags, so it is where
  // the gating decision is made and handed down. `PrimaryNav` and
  // `AppNavDrawer` live in `components/` and may not import a feature, and both
  // get the SAME predicate — a tab hidden in the topbar and present in the mobile drawer is a
  // feature that is still one hamburger away.
  //
  // A destination with no entry in the registry (Notifications, Help) is ungated, and while
  // the flags are still loading every gated tab is absent: a tab that appears and then
  // vanishes under the pointer is worse than one that arrives a tick late.
  const {isEnabled} = useFeatureSet();
  const isPathEnabled = useCallback(
    (to: string) => {
      const flag = NAV_PATH_FLAGS.get(to);
      return !flag || isEnabled(flag);
    },
    [isEnabled]
  );

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
            <PrimaryNav isPathEnabled={isPathEnabled} />
          </div>
        )}

        <div className="flex-1" />

        <div className="flex items-center gap-3">
          {/* Present signed out too — the header is what a signed-out visitor sees on any
              route but the landing page, which carries its own copy. It is the one control
              here that steps aside below `tablet`: the authenticated header is over its width
              budget at 375px before anything is added, so the drawer takes it instead. There
              is no drawer when signed out, and that header carries only a brand mark and one
              button, so it keeps the control at every width. */}
          {!(authed && isMobile) && <ThemeMenu />}

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
          isPathEnabled={isPathEnabled}
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
