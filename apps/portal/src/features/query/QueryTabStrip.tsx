import { useRef } from 'react';
import { cx } from '../../lib/cx';
import { DocumentIcon } from '../../components/icons';
import type { QueryTab } from './query.types';

type Props = {
  tabs: QueryTab[];
  activeTabId: string;
  dirtyTabIds: Set<string>; // SPEC-043: linked tabs whose SQL differs from the saved query
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
  onOpenSaved: () => void; // SPEC-043 FR-010: global (all-tabs) workspace buttons
  onOpenHistory: () => void;
};

const barButton =
  'inline-flex h-7 flex-none items-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-3 text-sm font-medium text-text-2 hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent [&>svg]:h-[15px] [&>svg]:w-[15px]';

// SPEC-041 FR-001/002/005: the query-tab strip above the editor toolbar. "Card"
// tabs (design-system.md §6) — distinct from the topbar Files|Query underline and
// the sidebar fill. Active tab: surface + border + leading accent dot (never
// color-only). The last remaining tab hides its close control; the `+` is never
// disabled (the cap is enforced by a dialog upstream — FR-008).
export function QueryTabStrip({
  tabs,
  activeTabId,
  dirtyTabIds,
  onSelect,
  onClose,
  onNew,
  onOpenSaved,
  onOpenHistory,
}: Props) {
  const solo = tabs.length === 1;
  const tabRefs = useRef(new Map<string, HTMLDivElement>());

  // WAI-ARIA tabs keyboard model (WCAG 2.1.1): with a roving tabindex only the
  // active tab is in the Tab sequence, so Left/Right/Home/End must move focus
  // (and selection) to reach the other tabs.
  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(tabs[index].id);
      return;
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && !solo) {
      // Keyboard close (WAI-ARIA tabs-with-close pattern): the visible ✕ button is
      // a sibling of the tab — not a focusable descendant (nested-interactive) — so
      // Delete is how keyboard users close the focused tab.
      e.preventDefault();
      onClose(tabs[index].id);
      return;
    }
    if (next === null) return;
    e.preventDefault();
    const nextTab = tabs[next];
    onSelect(nextTab.id);
    tabRefs.current.get(nextTab.id)?.focus();
  };

  return (
    <div className="flex h-10 flex-none items-center gap-1 overflow-x-auto border-b border-border bg-surface-2 px-3">
      {/* Only `role="tab"` elements may be tablist children (WCAG 4.1.2,
          aria-required-children) — the +/Saved/History controls sit outside it. */}
      <div
        role="tablist"
        aria-label="Query tabs"
        className="flex flex-none items-center gap-1"
      >
      {tabs.map((tab, index) => {
        const active = tab.id === activeTabId;
        return (
          <div
            key={tab.id}
            ref={(el) => {
              if (el) tabRefs.current.set(tab.id, el);
              else tabRefs.current.delete(tab.id);
            }}
            id={`query-tab-${tab.id}`}
            role="tab"
            aria-selected={active}
            aria-controls="query-tabpanel"
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(e) => onTabKeyDown(e, index)}
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
            {dirtyTabIds.has(tab.id) && (
              <span
                role="img"
                className="flex-none font-bold text-accent"
                title="Unsaved changes"
                aria-label="Unsaved changes"
              >
                •
              </span>
            )}
            <span className="truncate">{tab.label}</span>
            {/* Keyboard/AT users can also close via the Delete key on the focused
                tab (onTabKeyDown). This nested close button trips axe's
                nested-interactive rule — a known closable-tab remediation tracked
                separately; see QueryTabStrip.a11y.test.tsx. */}
            {!solo && (
              <button
                type="button"
                aria-label={`Close ${tab.label}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className="grid h-6 w-6 flex-none place-items-center rounded-sm text-text-3 hover:bg-danger-soft hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
      </div>

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

      {/* SPEC-043 FR-010: workspace-global buttons (act across all tabs). */}
      <div className="flex-1" />
      <button type="button" className={barButton} onClick={onOpenSaved}>
        <DocumentIcon />
        Saved queries
      </button>
      <button type="button" className={barButton} onClick={onOpenHistory}>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
          <path d="M12 8v5l3 2" />
        </svg>
        History
      </button>
    </div>
  );
}
