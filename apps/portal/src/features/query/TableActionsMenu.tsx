import {useEffect, useId, useRef, useState} from 'react';
import {cx} from '../../lib/cx';

export type TableMenuItem = {
  key: string;
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean; // a hairline above this item (e.g. before Drop)
};

type Props = {
  // Names the table for the accessible label (e.g. "Options for sales_2026").
  tableName: string;
  items: TableMenuItem[];
};

// SPEC-044 FR-001: a small, reusable kebab (⋮) + popover menu — the app's first
// menu primitive. Accessible: aria-haspopup/expanded, focus moves into the menu,
// Escape + outside-click close (returning focus to the trigger), arrow-key nav.
// Clicks stop propagation so opening the menu never toggles the table row.
export function TableActionsMenu({tableName, items}: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  const close = (returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  // Outside-click closes (no focus return — the click moves focus itself).
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  // On open, focus the first enabled item.
  useEffect(() => {
    if (!open) return;
    const first = itemRefs.current.find((el) => el && !el.disabled);
    first?.focus();
  }, [open]);

  const focusItem = (dir: 1 | -1) => {
    const els = itemRefs.current.filter((el): el is HTMLButtonElement => !!el);
    if (els.length === 0) return;
    const active = document.activeElement as HTMLElement | null;
    const idx = els.findIndex((el) => el === active);
    const next = (idx + dir + els.length) % els.length;
    els[next]?.focus();
  };

  return (
    <div
      ref={containerRef}
      className="relative flex-none">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Options for ${tableName}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className={cx(
          'grid h-6 w-6 place-items-center rounded-sm text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          open && 'bg-surface-2 text-text'
        )}>
        <svg
          viewBox="0 0 24 24"
          fill="currentColor"
          className="h-4 w-4"
          aria-hidden="true">
          <circle
            cx="12"
            cy="5"
            r="1.6"
          />
          <circle
            cx="12"
            cy="12"
            r="1.6"
          />
          <circle
            cx="12"
            cy="19"
            r="1.6"
          />
        </svg>
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={`${tableName} actions`}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              close();
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              focusItem(1);
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              focusItem(-1);
            }
          }}
          className="absolute right-0 top-full z-50 mt-1 min-w-[184px] rounded-md border border-border bg-surface p-1 shadow-md">
          {items.map((item, i) => (
            <div key={item.key}>
              {item.separatorBefore && (
                <div
                  className="my-1 h-px bg-border"
                  aria-hidden="true"
                />
              )}
              <button
                ref={(el) => {
                  itemRefs.current[i] = el;
                }}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  close(false);
                  item.onSelect();
                }}
                className={cx(
                  'flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-45',
                  item.danger ? 'text-danger hover:bg-danger-soft' : 'text-text hover:bg-surface-2'
                )}>
                {item.label}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
