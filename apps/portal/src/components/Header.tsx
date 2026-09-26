import {useCallback, useId, useState} from 'react';
import {useAuth} from '../features/auth';
import {FeedbackDialog} from '../features/feedback';
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
import {UserMenu} from './UserMenu';

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
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const isMobile = useIsMobile();
  // The drawer exists below `tablet` only. Kept open across a width change it would reappear,
  // open and unasked, when the width came back — rotating an iPad twice — so a change closes it.
  const [wasMobile, setWasMobile] = useState(isMobile);
  if (isMobile !== wasMobile) {
    setWasMobile(isMobile);
    setNavOpen(false);
  }
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

        {/* The words wait for `desktop`: at `tablet` the tab strip and the three control labels
            switch on together, so the band just above it is the tightest in the layout, not the
            loosest. The username and the tab icons wait with them, for the same reason. The
            square still identifies the app, and the nav drawer names it below `tablet`. Signed
            out there is no tab strip and no user zone, so the words stay at every width. */}
        <BrandMark wordmarkClassName={authed ? 'hidden desktop:inline' : undefined} />

        {authed && (
          <div className="hidden h-full tablet:flex">
            <PrimaryNav isPathEnabled={isPathEnabled} />
          </div>
        )}

        <div className="flex-1" />

        {/* Help, notifications and the theme are three NAMED controls in a row, then the
            account trigger. Each of the three carries a word beside its icon at `tablet` and
            up; below that the words go and the icons stay, because the bar's fixed-width
            chrome is most of a 375px phone before any of them is drawn. */}
        <div className="flex items-center gap-1 tablet:gap-2">
          {authed && (
            <>
              <HelpLink />
              <NotificationsBell
                hasUnread={hasUnread}
                unreadCount={unreadCount}
              />
            </>
          )}

          {/* ONE instance, for both auth states — signed out it is the whole right-hand side
              beside `Sign in`, signed in it sits next to notifications. The header is what a
              signed-out visitor sees on every route but the landing page and there is no
              drawer to fall back to, so a control gated on `authed` would leave them no way to
              change the theme at all. */}
          <ThemeMenu />

          {status === 'loading' && (
            <span
              className="ml-2 text-sm text-text-3"
              aria-hidden="true">
              &hellip;
            </span>
          )}

          {status === 'unauthenticated' && (
            <Button
              variant="primary"
              className="ml-2"
              onClick={() => void signIn()}>
              Sign in
            </Button>
          )}

          {authed && (
            <UserMenu
              username={user.username}
              onGiveFeedback={() => setFeedbackOpen(true)}
              onSignOut={() => void signOut()}
            />
          )}
        </div>
      </div>

      {/* No `actions` slot any more: it existed to give a phone the Give-feedback control the
          header had no room for, and the account menu now carries it at every width. Two ways
          to reach one dialog is one more than the user needs and one more to keep in step. */}
      {authed && isMobile && (
        <AppNavDrawer
          id={navDrawerId}
          open={navOpen}
          onClose={() => setNavOpen(false)}
          contextualRail={contextualRail}
          isPathEnabled={isPathEnabled}
        />
      )}

      {feedbackOpen && <FeedbackDialog onClose={() => setFeedbackOpen(false)} />}

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
