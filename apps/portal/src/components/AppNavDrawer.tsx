import {useEffect, useRef, type ReactNode} from 'react';
import {NavLink} from 'react-router';
import {FocusTrap} from 'focus-trap-react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {BellIcon, HelpCircleIcon} from './icons';
import {useEscapeKey} from '../hooks/useEscapeKey';
import {SECTION_CAPTION} from './fieldStyles';

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
};

type NavDest = {to: string; label: string; icon: ReactNode};

// Stroke-icon glyphs mirror PrimaryNav (Files/Query/Connections) so the two nav
// surfaces read the same; Notifications/Help reuse the shared icon components.
function GlyphSvg({children}: {children: ReactNode}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[18px] w-[18px] flex-none"
      aria-hidden="true">
      {children}
    </svg>
  );
}

const DESTS: NavDest[] = [
  {
    to: '/files',
    label: 'Files',
    icon: (
      <GlyphSvg>
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      </GlyphSvg>
    )
  },
  {
    to: '/query',
    label: 'Query',
    icon: (
      <GlyphSvg>
        <ellipse
          cx="12"
          cy="6"
          rx="8"
          ry="3"
        />
        <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
        <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
      </GlyphSvg>
    )
  },
  {
    to: '/explore',
    label: 'Data Explorer',
    icon: (
      <GlyphSvg>
        <rect
          x="3"
          y="4"
          width="18"
          height="16"
          rx="2"
        />
        <path d="M3 9h18M9 9v11" />
      </GlyphSvg>
    )
  },
  {
    to: '/connections',
    label: 'Connections',
    icon: (
      <GlyphSvg>
        <circle
          cx="7"
          cy="7"
          r="3"
        />
        <circle
          cx="17"
          cy="17"
          r="3"
        />
        <path d="M10 7h4a3 3 0 0 1 3 3v4M7 10v4a3 3 0 0 0 3 3h4" />
      </GlyphSvg>
    )
  },
  {
    to: '/data-quality',
    label: 'Data quality',
    icon: (
      <GlyphSvg>
        <path d="M9 12l2 2 4-4" />
        <path d="M21 12a9 9 0 1 1-3.5-7.1" />
      </GlyphSvg>
    )
  },
  {to: '/notifications', label: 'Notifications', icon: <BellIcon className="h-[18px] w-[18px] flex-none" />},
  {to: '/help', label: 'Help', icon: <HelpCircleIcon className="h-[18px] w-[18px] flex-none" />}
];

/**
 * Mobile off-canvas navigation: a 300px left sheet over a scrim listing the primary
 * destinations (Files / Query / Data Explorer / Connections / Data quality / Notifications / Help) with
 * active state, then a divider and a page-supplied contextual rail. Reuses the
 * `Drawer` mechanics (focus trap + Escape/scrim dismiss) plus a background
 * scroll lock; activating a link navigates and closes. Header mounts this only
 * on mobile.
 *
 * @example
 * <AppNavDrawer open={navOpen} onClose={() => setNavOpen(false)} contextualRail={rail} />
 */
export function AppNavDrawer({open, onClose, id, contextualRail, isPathEnabled}: AppNavDrawerProps) {
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
            <span className={SECTION_CAPTION}>Menu</span>
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

          {contextualRail && (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto border-t border-border">{contextualRail}</div>
          )}
        </aside>
      </div>
    </FocusTrap>
  );
}
