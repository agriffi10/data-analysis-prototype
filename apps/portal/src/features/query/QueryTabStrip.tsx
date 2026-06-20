import { cx } from '../../lib/cx';
import type { QueryTab } from './query.types';

type Props = {
  tabs: QueryTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
};

// SPEC-041 FR-001/002/005: the query-tab strip above the editor toolbar. "Card"
// tabs (design-system.md §6) — distinct from the topbar Files|Query underline and
// the sidebar fill. Active tab: surface + border + leading accent dot (never
// color-only). The last remaining tab hides its close control; the `+` is never
// disabled (the cap is enforced by a dialog upstream — FR-008).
export function QueryTabStrip({
  tabs,
  activeTabId,
  onSelect,
  onClose,
  onNew,
}: Props) {
  const solo = tabs.length === 1;

  return (
    <div
      role="tablist"
      aria-label="Query tabs"
      className="flex h-10 flex-none items-center gap-1 overflow-x-auto border-b border-border bg-surface-2 px-3"
    >
      {tabs.map((tab) => {
        const active = tab.id === activeTabId;
        return (
          <div
            key={tab.id}
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(tab.id);
              }
            }}
            className={cx(
              'inline-flex h-7 flex-none cursor-pointer items-center gap-2 whitespace-nowrap rounded-md border pl-3 pr-1 text-sm font-medium',
              active
                ? 'border-border bg-surface text-text shadow-sm'
                : 'border-transparent text-text-2 hover:bg-surface hover:text-text',
            )}
          >
            <span
              className={cx(
                'h-1.5 w-1.5 flex-none rounded-full bg-accent',
                active ? 'opacity-100' : 'opacity-0',
              )}
              aria-hidden="true"
            />
            <span className="truncate">{tab.label}</span>
            {!solo && (
              <button
                type="button"
                aria-label={`Close ${tab.label}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className="grid h-[18px] w-[18px] place-items-center rounded-sm text-text-3 hover:bg-danger-soft hover:text-danger"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3 w-3"
                  aria-hidden="true"
                >
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            )}
          </div>
        );
      })}

      <button
        type="button"
        aria-label="New query tab"
        title="New query tab"
        onClick={onNew}
        className="grid h-7 w-7 flex-none place-items-center rounded-md border border-transparent text-text-2 hover:bg-surface hover:text-text"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-4 w-4"
          aria-hidden="true"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
    </div>
  );
}
