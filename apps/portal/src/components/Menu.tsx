import {useEffect, useId, useRef, useState, type ReactNode, type Ref} from 'react';
import {cx} from '../lib/cx';

export type MenuItem =
  | {
      kind: 'action';
      label: string;
      icon?: ReactNode;
      tone?: 'default' | 'danger';
      onSelect: () => void;
      disabled?: boolean;
    }
  | {kind: 'separator'};

export type MenuProps = {
  /**
   * Render the trigger button. Wire the supplied `ref` and `onClick={toggle}`
   * onto it, reflect `open` via `aria-expanded` (+ `aria-haspopup="menu"`), and
   * link the popover with `aria-controls={open ? menuId : undefined}`.
   */
  trigger: (p: {open: boolean; toggle: () => void; ref: Ref<HTMLButtonElement>; menuId: string}) => ReactNode;
  items: MenuItem[];
  /** Accessible name for the `role="menu"` popover. */
  ariaLabel: string;
  /** Popover horizontal alignment relative to the trigger. Default `right`. */
  align?: 'left' | 'right';
  /** Extra classes for the (relatively-positioned) wrapper around trigger + popover. */
  className?: string;
  /** Extra classes for the popover panel (e.g. a wider `min-w-*`). */
  menuClassName?: string;
};

/**
 * Accessible menu primitive: a caller-supplied trigger button + a `role="menu"`
 * popover with focus-into-menu on open, Arrow up/down roving, and Escape /
 * outside-click dismissal (Escape returns focus to the trigger). `items` drive
 * the body — action items (with an optional `icon` and a `danger` tone) and
 * separators. Extracted from the query schema-rail kebab (SPEC-095) so overflow
 * menus and kebabs across surfaces share one implementation.
 *
 * @example
 * <Menu
 *   ariaLabel="Row actions"
 *   trigger={({open, toggle, ref}) => (
 *     <button ref={ref} aria-haspopup="menu" aria-expanded={open} onClick={toggle}>⋯</button>
 *   )}
 *   items={[
 *     {kind: 'action', label: 'Rename', onSelect: rename},
 *     {kind: 'separator'},
 *     {kind: 'action', label: 'Delete', tone: 'danger', onSelect: remove},
 *   ]}
 * />
 */
export function Menu({trigger, items, ariaLabel, align = 'right', className, menuClassName}: MenuProps) {
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

  // Monotonic index over action items only (separators don't take focus).
  let actionIndex = 0;

  return (
    <div
      ref={containerRef}
      className={cx('relative', className)}>
      {trigger({open, toggle: () => setOpen((o) => !o), ref: triggerRef, menuId})}

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={ariaLabel}
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
          className={cx(
            'absolute top-full z-50 mt-1 min-w-[184px] rounded-md border border-border bg-surface p-1 shadow-md',
            align === 'right' ? 'right-0' : 'left-0',
            menuClassName
          )}>
          {items.map((item, i) => {
            if (item.kind === 'separator') {
              return (
                <div
                  key={`sep-${i}`}
                  className="my-1 h-px bg-border"
                  aria-hidden="true"
                />
              );
            }
            const refIndex = actionIndex++;
            return (
              <button
                key={`item-${i}`}
                ref={(el) => {
                  itemRefs.current[refIndex] = el;
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
                  item.tone === 'danger' ? 'text-danger hover:bg-danger-soft' : 'text-text hover:bg-surface-2'
                )}>
                {item.icon}
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
