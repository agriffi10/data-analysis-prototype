import {useEffect, useRef, type ReactNode} from 'react';
import {NavLink} from 'react-router';
import {FocusTrap} from 'focus-trap-react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {BellIcon, HelpCircleIcon} from './icons';
import {DestinationIcon} from './DestinationIcon';
import {BrandMark} from './BrandMark';
import {useEscapeKey} from '../hooks/useEscapeKey';

export type AppNavDrawerProps = {
  open: boolean;
  onClose: () => void;
  /** Applied to the panel so the hamburger's `aria-controls` can reference it. */
  id?: string;
  /** Page-supplied rail (Files → Spaces list, Query → schema rail). */
  contextualRail?: ReactNode;
  /**
   * Is this destination's feature on? Same predicate `PrimaryNav` takes, and required for the
   * same reason — the drawer IS the navigation below `tablet`, so a tab hidden only in the
   * topbar is a feature that is still one hamburger away on a phone.
   */
  isPathEnabled: (to: string) => boolean;
  /**
   * Chrome ACTIONS that live in the header at `tablet` and above and have nowhere to go below it.
   * Rendered under the destinations, after a divider.
   *
   * A slot rather than a prop per control, because this file may not import `features/` and every
   * such control is one — `Header` composes them and passes the node down. It is deliberately
   * generic: the mobile header is over budget at 375px before anything is added, so this is where
   * the next one goes too.
   *
   * The slot does NOT close the drawer. A launcher wants to, a toggle does not, and a wrapper
   * that decided for both would make the next control here quietly wrong — so each action closes
   * the drawer itself if that is what it means.
   *
   * CURRENTLY UNFILLED. Its one occupant was Give feedback, which moved to the account menu once
   * that menu made every chrome control reachable at every width. Kept rather than deleted
   * because the reason it exists has not gone away — the header is still width-constrained — but
   * nothing passes it today, so it is untested and the next filler owns proving it.
   */
  actions?: ReactNode;
};

type NavDest = {to: string; label: string; icon: ReactNode};

const DESTS: NavDest[] = [
  {
    to: '/files',
    label: 'Files',
    icon: (
      <DestinationIcon
        destination="files"
        className="h-[18px] w-[18px] flex-none"
      />
    )
  },
  {
    to: '/query',
    label: 'Query',
    icon: (
      <DestinationIcon
        destination="query"
        className="h-[18px] w-[18px] flex-none"
      />
    )
  },
  {
    to: '/explore',
    label: 'Data Explorer',
    icon: (
      <DestinationIcon
        destination="explore"
        className="h-[18px] w-[18px] flex-none"
      />
    )
  },
  {
    to: '/connections',
    label: 'Shared spaces',
    icon: (
      <DestinationIcon
        destination="connections"
        className="h-[18px] w-[18px] flex-none"
      />
    )
  },
  {
    to: '/data-quality',
    label: 'Data quality',
    icon: (
      <DestinationIcon
        destination="dataQuality"
        className="h-[18px] w-[18px] flex-none"
      />
    )
  },
  {to: '/notifications', label: 'Notifications', icon: <BellIcon className="h-[18px] w-[18px] flex-none" />},
  {to: '/help', label: 'Help', icon: <HelpCircleIcon className="h-[18px] w-[18px] flex-none" />}
];

/**
 * Mobile off-canvas navigation: a 300px left sheet over a scrim listing the primary
 * destinations (Files / Query / Data Explorer / Shared spaces / Data quality / Notifications / Help) with
 * active state, then any header actions that do not fit a phone's top bar, then a divider and a
 * page-supplied contextual rail. Reuses the
 * `Drawer` mechanics (focus trap + Escape/scrim dismiss) plus a background
 * scroll lock; activating a link navigates and closes. Header mounts this only
 * on mobile.
 *
 * @example
 * <AppNavDrawer open={navOpen} onClose={() => setNavOpen(false)} contextualRail={rail} />
 */
export function AppNavDrawer({open, onClose, id, contextualRail, isPathEnabled, actions}: AppNavDrawerProps) {
  useEscapeKey(onClose, open);
  const panelRef = useRef<HTMLElement>(null);

  // Lock background scroll while open (parity with the modal/drawer overlays).
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    // Escape is owned by useEscapeKey and the scrim owns backdrop-dismiss, so
    // focus-trap's own escape/outside-click handling is disabled; it still
    // returns focus to the hamburger on deactivate.
    <FocusTrap
      focusTrapOptions={{
        // Focus the first destination link (Files) on open; fall back to the
        // panel if the query misses so focus stays trapped inside.
        initialFocus: () =>
          panelRef.current?.querySelector<HTMLElement>('a[href]') ?? panelRef.current ?? document.body,
        fallbackFocus: () => panelRef.current ?? document.body,
        escapeDeactivates: false,
        allowOutsideClick: true
      }}>
      <div
        className="fixed inset-0 z-40 flex bg-black/30 backdrop-blur-sm"
        onClick={onClose}>
        <aside
          ref={panelRef}
          id={id}
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          tabIndex={-1}
          className="flex h-full w-[300px] max-w-[85vw] flex-col bg-surface shadow-lg"
          onClick={(e) => e.stopPropagation()}>
          <div className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-2">
            {/* The app's name, not the caption `Menu` that was here. Below `tablet` the header
                shows the brand SQUARE alone — there is no room for the words beside a
                hamburger, five nav tabs' worth of drawer and four controls — so without this
                the name appears nowhere on screen for a signed-in phone user. */}
            <BrandMark size="sm" />
            <IconButton
              label="Close navigation"
              onClick={onClose}>
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
                aria-hidden="true">
                <path
                  strokeLinecap="round"
                  d="M2 2l12 12M14 2L2 14"
                />
              </svg>
            </IconButton>
          </div>

          <nav
            aria-label="Primary"
            className="flex flex-col gap-0.5 p-3">
            {DESTS.filter((dest) => isPathEnabled(dest.to)).map((dest) => (
              <NavLink
                key={dest.to}
                to={dest.to}
                onClick={onClose}
                className={({isActive}) =>
                  cx(
                    'flex min-h-11 items-center gap-3 rounded-md px-3 py-2 text-base font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                    isActive ? 'bg-accent-soft text-accent-text' : 'text-text-2 hover:bg-surface-2 hover:text-text'
                  )
                }>
                {dest.icon}
                {dest.label}
              </NavLink>
            ))}
          </nav>

          {/* The theme choice used to be duplicated here, because the header dropped its
              control below `tablet` for want of width. The bar carries it at every width now
              — icon-only below `tablet`, where its label goes but the control does not — so a
              second copy would be two controls setting one value. */}

          {actions && <div className="flex flex-col gap-0.5 border-t border-border p-3">{actions}</div>}

          {contextualRail && (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto border-t border-border">{contextualRail}</div>
          )}
        </aside>
      </div>
    </FocusTrap>
  );
}
