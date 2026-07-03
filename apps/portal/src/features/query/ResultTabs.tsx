import {useRef} from 'react';
import {cx} from '../../lib/cx';
import type {ResultTab} from './query.types';

type Props = {
  /** One entry per result-producing statement, execution order (SPEC-078 FR-007). */
  tabs: ResultTab[];
  activeIndex: number;
  onSelect: (index: number) => void;
};

/**
 * SPEC-078 FR-007: the result-tab strip shown for a "Run Script (tab per
 * statement)" run — one tab per result-producing statement, labeled by its
 * 1-based statement position and a short statement hint. Same WAI-ARIA tabs
 * keyboard model as QueryTabStrip (roving tabindex; Left/Right/Home/End move
 * focus + selection); the active tab is never indicated by color alone.
 */
export function ResultTabs({tabs, activeIndex, onSelect}: Props) {
  const tabRefs = useRef(new Map<number, HTMLButtonElement>());

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    onSelect(next);
    tabRefs.current.get(next)?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Result tabs"
      className="mb-3 flex flex-none items-center gap-1 overflow-x-auto">
      {tabs.map((tab, index) => {
        const active = index === activeIndex;
        return (
          <button
            key={tab.executionId}
            ref={(el) => {
              if (el) tabRefs.current.set(index, el);
              else tabRefs.current.delete(index);
            }}
            type="button"
            id={`result-tab-${index}`}
            role="tab"
            aria-selected={active}
            aria-controls="result-tabpanel"
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(index)}
            onKeyDown={(e) => onTabKeyDown(e, index)}
            title={tab.label}
            className={cx(
              'inline-flex h-7 flex-none cursor-pointer items-center gap-2 whitespace-nowrap rounded-md border px-3 font-mono text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active
                ? 'border-border bg-surface text-text shadow-sm'
                : 'border-transparent text-text-2 hover:bg-surface hover:text-text'
            )}>
            <span
              className={cx('h-1.5 w-1.5 flex-none rounded-full bg-accent', active ? 'opacity-100' : 'opacity-0')}
              aria-hidden="true"
            />
            <span className="max-w-56 truncate">{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}
