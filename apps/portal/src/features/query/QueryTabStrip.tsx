import {useRef} from 'react';
import {cx} from '../../lib/cx';
import {DocumentIcon} from '../../components/icons';
import type {QueryTab} from './query.types';

type Props = {
  tabs: QueryTab[];
  activeTabId: string;
  dirtyTabIds: Set<string>; // Linked tabs whose SQL differs from the saved query
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
  onOpenSaved: () => void; // Global (all-tabs) workspace buttons
  onOpenHistory: () => void;
};

const barButton =
  'inline-flex h-7 flex-none items-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-3 text-sm font-medium text-text-2 hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent [&>svg]:h-[15px] [&>svg]:w-[15px]';

// The query-tab strip above the editor toolbar. "Card"
// tabs (design-system.md §6) — distinct from the topbar Files|Query underline and
// the sidebar fill. Active tab: an elevated card (surface fill + border + shadow +
// bold label) — never color-only, and no leading dot so it can't be confused with
// the dirty-state marker. The last remaining tab hides its close control; the `+`
// is never disabled (the cap is enforced by a dialog upstream).
export function QueryTabStrip({
  tabs,
  activeTabId,
  dirtyTabIds,
  onSelect,
  onClose,
  onNew,
  onOpenSaved,
  onOpenHistory
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
    <div className="flex h-10 flex-none items-center gap-1 border-b border-border bg-surface-2 px-3">
      {/* The `+` sits to the LEFT of the tabs and outside the scrollable region so
          it stays visible at any tab count (FR: only the tabs scroll). */}
      <button
        type="button"
        aria-label="New query tab"
        title="New query tab"
        onClick={onNew}
        className="grid h-7 w-7 flex-none place-items-center rounded-md border border-transparent text-text-2 hover:bg-surface hover:text-text">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-4 w-4"
          aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>

      {/* Only `role="tab"` elements may be tablist children (WCAG 4.1.2,
          aria-required-children) — the +/Saved/History controls sit outside it.
          This is the only scrollable region (min-w-0 + overflow-x-auto); the
          surrounding controls stay pinned. */}
      <div
        role="tablist"
        aria-label="Query tabs"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
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
                'inline-flex h-7 flex-none cursor-pointer items-center gap-2 whitespace-nowrap rounded-md border pl-3 text-sm',
                // The tight right padding assumes the ✕ box sits at the end; with no ✕ the
                // tab pads symmetrically instead of reserving a dead 24px slot.
                solo ? 'pr-3' : 'pr-1',
                active
                  ? 'border-border bg-surface font-semibold text-text shadow-sm'
                  : 'border-transparent font-medium text-text-2 hover:bg-surface hover:text-text'
              )}>
              {dirtyTabIds.has(tab.id) && (
                <span
                  role="img"
                  className="flex-none font-bold text-accent"
                  title="Unsaved changes"
                  aria-label="Unsaved changes">
                  •
                </span>
              )}
              <span className="truncate">{tab.label}</span>
              {/* The ✕ is a decorative, non-focusable pointer affordance — NOT a
                nested <button>, which would trip axe's nested-interactive rule
                inside the role="tab". Keyboard/AT users close via the Delete key
                on the focused tab (onTabKeyDown), so the same action stays fully
                operable without this control (WCAG 2.1.1).
                The last remaining tab renders no ✕ and no placeholder — the tab
                shrinks to its label rather than holding an empty 21px slot. */}
              {!solo && (
                <span
                  role="presentation"
                  title={`Close ${tab.label}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onClose(tab.id);
                  }}
                  className="grid h-6 w-6 flex-none cursor-pointer place-items-center rounded-sm text-text-3 hover:bg-danger-soft hover:text-danger">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className="h-3 w-3"
                    aria-hidden="true">
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* workspace-global buttons (act across all tabs). They
          sit outside the scrollable tablist so they stay visible at any tab count. */}
      <button
        type="button"
        className={barButton}
        onClick={onOpenSaved}>
        <DocumentIcon />
        Saved queries
      </button>
      <button
        type="button"
        className={barButton}
        onClick={onOpenHistory}>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
          <path d="M12 8v5l3 2" />
        </svg>
        History
      </button>
    </div>
  );
}
