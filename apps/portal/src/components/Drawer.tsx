import {useRef, type ReactNode} from 'react';
import {FocusTrap} from 'focus-trap-react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {useEscapeKey} from '../hooks/useEscapeKey';
import {EscapeLayer} from './EscapeLayer';

/** Below `tablet`, how the drawer presents: docked bottom sheet or full-height sheet. */
export type DrawerMobileVariant = 'bottom-sheet' | 'full-height';

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /**
   * Mobile (< tablet) presentation: `bottom-sheet` (full-width, docked to the
   * bottom, rounded top — content/detail drawers) or `full-height` (full-width,
   * full-height — member/roster drawers). Desktop is always the 440px right
   * slide-over. Default `bottom-sheet`.
   */
  mobileVariant?: DrawerMobileVariant;
  /** Extends the title's classes (e.g. `font-mono` for a name). */
  titleClassName?: string;
  /** Small muted line rendered under the title. */
  subtitle?: ReactNode;
  /** Defaults to `title`. */
  ariaLabel?: string;
  /** Close-button label; defaults to `Close {title}`. */
  closeLabel?: string;
  /** Escape closes the drawer; pass false while a nested dialog owns Escape. */
  /** Rendered after the title (e.g. a destination hint). */
  headerAccessory?: ReactNode;
  /** Body flex-gap override; defaults to `gap-3`. */
  bodyClassName?: string;
  children: ReactNode;
  /** Pinned below the scrollable body (e.g. a pager). */
  footer?: ReactNode;
};

/**
 * Slide-over drawer: scrim + panel + header with close button + scrollable body.
 * Traps focus while open and restores it to the trigger on close; Escape and
 * backdrop click both dismiss. A nested dialog takes Escape on its own — `useEscapeKey`
 * dispatches by tree depth, so there is no opt-out to remember. Desktop (≥ tablet) is a 440px right slide-over; below
 * tablet it becomes a full-width sheet — a docked bottom sheet or a full-height
 * sheet per `mobileVariant`.
 *
 * @example
 * <Drawer open={open} onClose={() => setOpen(false)} title="History" footer={<Pager {...pager} />}>
 *   <HistoryList items={items} />
 * </Drawer>
 */
export function Drawer({
  open,
  onClose,
  title,
  titleClassName,
  subtitle,
  ariaLabel,
  closeLabel,
  mobileVariant = 'bottom-sheet',
  headerAccessory,
  bodyClassName = 'gap-3',
  children,
  footer
}: DrawerProps) {
  useEscapeKey(onClose, open);
  const panelRef = useRef<HTMLElement>(null);

  if (!open) return null;

  return (
    // Escape is owned by useEscapeKey above and the scrim owns backdrop-dismiss,
    // so focus-trap's own escape/outside-click handling is disabled.
    <FocusTrap
      focusTrapOptions={{
        initialFocus: false,
        fallbackFocus: () => panelRef.current ?? document.body,
        escapeDeactivates: false,
        allowOutsideClick: true
      }}>
      <div
        className={cx(
          'fixed inset-0 z-40 flex bg-black/30 backdrop-blur-sm tablet:justify-end',
          // Below tablet a bottom sheet docks to the bottom edge; full-height
          // (and desktop) stretch. Reset to stretch at tablet for the slide-over.
          mobileVariant === 'bottom-sheet' ? 'items-end tablet:items-stretch' : ''
        )}
        onClick={onClose}>
        <aside
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={ariaLabel ?? title}
          tabIndex={-1}
          className={cx(
            'flex w-full flex-col bg-surface shadow-lg tablet:h-full tablet:max-h-none tablet:w-full tablet:max-w-[440px] tablet:rounded-none',
            mobileVariant === 'bottom-sheet' ? 'max-h-[85dvh] rounded-t-xl' : 'h-full'
          )}
          onClick={(e) => e.stopPropagation()}>
          <div className="flex min-h-14 shrink-0 items-center gap-2 border-b border-border px-5 py-2">
            <div className="min-w-0">
              <h2 className={cx('truncate text-md font-semibold text-text', titleClassName)}>{title}</h2>
              {subtitle && <div className="mt-0.5 text-xs text-text-3">{subtitle}</div>}
            </div>
            {headerAccessory}
            <div className="flex-1" />
            <IconButton
              label={closeLabel ?? `Close ${title.toLowerCase()}`}
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

          <div className={cx('flex min-h-0 flex-1 flex-col overflow-y-auto p-5', bodyClassName)}>
            {/* A dialog opened from inside this drawer is one layer deeper, so Escape
                closes it and leaves the drawer alone. */}
            <EscapeLayer>{children}</EscapeLayer>
          </div>

          {footer}
        </aside>
      </div>
    </FocusTrap>
  );
}
