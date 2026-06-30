import {useRef, type ReactNode} from 'react';
import {FocusTrap} from 'focus-trap-react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {useEscapeKey} from '../hooks/useEscapeKey';

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  titleClassName?: string; // extends the title's classes (e.g. `font-mono` for a name)
  subtitle?: ReactNode; // small muted line rendered under the title
  ariaLabel?: string; // defaults to `title`
  closeLabel?: string; // close-button label; defaults to `Close {title}`
  // Escape closes the drawer; pass false while a nested dialog owns Escape.
  closeOnEscape?: boolean;
  headerAccessory?: ReactNode; // rendered after the title (e.g. a destination hint)
  bodyClassName?: string; // body flex-gap override; defaults to `gap-3`
  children: ReactNode;
  footer?: ReactNode; // pinned below the scrollable body (e.g. a pager)
};

// SPEC-036 right slide-over drawer (react-best-practices abstraction pass): scrim
// + 440px panel + header with close button + scrollable body, consolidated from
// QueryHistoryPanel and SavedQueriesPanel.
export function Drawer({
  open,
  onClose,
  title,
  titleClassName,
  subtitle,
  ariaLabel,
  closeLabel,
  closeOnEscape = true,
  headerAccessory,
  bodyClassName = 'gap-3',
  children,
  footer
}: DrawerProps) {
  useEscapeKey(onClose, open && closeOnEscape);
  const panelRef = useRef<HTMLElement>(null);

  if (!open) return null;

  return (
    // Trap focus within the drawer while open; restore it to the trigger on
    // close. Escape is owned by useEscapeKey above and the scrim owns
    // backdrop-dismiss, so focus-trap's own escape/outside-click are disabled.
    <FocusTrap
      focusTrapOptions={{
        initialFocus: false,
        fallbackFocus: () => panelRef.current ?? document.body,
        escapeDeactivates: false,
        allowOutsideClick: true
      }}>
      <div
        className="fixed inset-0 z-40 flex justify-end bg-black/30 backdrop-blur-sm"
        onClick={onClose}>
        <aside
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={ariaLabel ?? title}
          tabIndex={-1}
          className="flex h-full w-full max-w-[440px] flex-col bg-surface shadow-lg"
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

          <div className={cx('flex flex-1 flex-col overflow-y-auto p-5', bodyClassName)}>{children}</div>

          {footer}
        </aside>
      </div>
    </FocusTrap>
  );
}
