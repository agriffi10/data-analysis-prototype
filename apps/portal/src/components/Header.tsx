import {useCallback, useId, useState} from 'react';
import {useNavigate} from 'react-router';
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
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
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
          {/* SIGNED OUT ONLY, now that the signed-in theme choice lives in the account menu.
              Not deleted: the header is what a signed-out visitor sees on every route but the
              landing page, there is no drawer to fall back to when signed out, and the account
              menu does not exist without an account — so removing this would leave a
              signed-out visitor no way to change the theme at all. */}
          {!authed && <ThemeMenu />}

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
              {/* Stays on the bar while its DESTINATION moves into the menu, because the two
                  are different things: this is per-page help, and a control whose meaning
                  changes with the route cannot live in a persistent account menu. On a route
                  with a help section it opens that section's panel; the menu's `Help & guides`
                  is the /help route, which is what it always was. */}
              <HelpLink />
              <NotificationsBell
                hasUnread={hasUnread}
                unreadCount={unreadCount}
              />
              {/* One trigger in place of five controls (theme, feedback, the username, the
                  avatar and Sign out). The header was over its width budget on a phone before
                  this, which is why theme and feedback were mount-gated away below `tablet`
                  and duplicated into the drawer; every option now exists at every width. */}
              <UserMenu
                username={user.username}
                onHelp={() => void navigate('/help')}
                onGiveFeedback={() => setFeedbackOpen(true)}
                onSignOut={() => void signOut()}
              />
            </>
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
