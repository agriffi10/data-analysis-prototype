import type { ReactNode } from 'react';
import { cx } from '../lib/cx';
import { IconButton } from './IconButton';
import { useEscapeKey } from '../hooks/useEscapeKey';

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
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
  ariaLabel,
  closeLabel,
  closeOnEscape = true,
  headerAccessory,
  bodyClassName = 'gap-3',
  children,
  footer,
}: DrawerProps) {
  useEscapeKey(onClose, open && closeOnEscape);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        className="flex h-full w-full max-w-[440px] flex-col bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-border px-5">
          <h2 className="text-md font-semibold text-text">{title}</h2>
          {headerAccessory}
          <div className="flex-1" />
          <IconButton
            label={closeLabel ?? `Close ${title.toLowerCase()}`}
            onClick={onClose}
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
            </svg>
          </IconButton>
        </div>

        <div
          className={cx(
            'flex flex-1 flex-col overflow-y-auto p-5',
            bodyClassName,
          )}
        >
          {children}
        </div>

        {footer}
      </aside>
    </div>
  );
}
