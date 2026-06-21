import { useState } from 'react';
import { Banner } from '../../components/Banner';
import { Drawer } from '../../components/Drawer';
import { Pager } from '../../components/Pager';
import { useQueryHistory } from './useQueryHistory';
import { QueryHistoryRow } from './QueryHistoryRow';
import { QUERY_HISTORY_PAGE_SIZE } from './query.constants';
import type { QueryHistoryEntry } from './query.types';

type QueryHistoryPanelProps = {
  open: boolean;
  onClose: () => void;
  username: string;
  onReopen: (entry: QueryHistoryEntry) => void;
  onRerun: (entry: QueryHistoryEntry) => void;
  rerunDisabled: boolean;
};

// SPEC-036: per-user query history (newest-first), read-only — view / Open /
// Re-run, no delete. Renders in the shared Drawer; paginated 7/page (SPEC-042)
// via the shared Pager.
export function QueryHistoryPanel({
  open,
  onClose,
  username,
  onReopen,
  onRerun,
  rerunDisabled,
}: QueryHistoryPanelProps) {
  // Always subscribe to the live history key (not gated on `open`) so an entry
  // appended/updated while the panel is open shows immediately, and the panel and
  // the workspace's mutations share one cache entry. Drawer visibility is `open`.
  const { history, isLoading, error } = useQueryHistory(username || null);

  // SPEC-042: client-side Prev/Next pager over the in-memory newest-first list.
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(
    1,
    Math.ceil(history.length / QUERY_HISTORY_PAGE_SIZE),
  );
  // Clamp if the list shrank so the pager never lands on a blank page (FR-003).
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * QUERY_HISTORY_PAGE_SIZE;
  const pageEntries = history.slice(start, start + QUERY_HISTORY_PAGE_SIZE);
  const hasPrev = safeIndex > 0; // newer entries exist
  const hasNext = safeIndex < pageCount - 1; // older entries exist

  // Reset to page 1 (newest) on open, and when a new entry is appended in-session.
  // Render-phase "adjust state on change" pattern rather than Effects.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setPageIndex(0);
  }
  const [prevLen, setPrevLen] = useState(history.length);
  if (history.length !== prevLen) {
    setPrevLen(history.length);
    if (history.length > prevLen) setPageIndex(0);
  }

  const footer =
    !error && !isLoading && history.length > 0 ? (
      <Pager
        className="flex-shrink-0 border-t border-border px-5 py-4"
        hasPrev={hasPrev}
        hasNext={hasNext}
        onPrev={() => setPageIndex(Math.max(0, safeIndex - 1))}
        onNext={() => setPageIndex(Math.min(pageCount - 1, safeIndex + 1))}
        label={
          <>
            {start + 1}–{start + pageEntries.length} of {history.length}
            <span className="sr-only"> (page {safeIndex + 1})</span>
          </>
        }
      />
    ) : undefined;

  return (
    <Drawer open={open} onClose={onClose} title="Query history" footer={footer}>
      {error ? (
        <Banner variant="danger" title="Couldn’t load history.">
          {error}
        </Banner>
      ) : isLoading ? (
        <p className="text-sm text-text-3">Loading history&hellip;</p>
      ) : history.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-8 w-8 text-text-3"
            aria-hidden="true"
          >
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <path d="M3 3v5h5" />
            <path d="M12 8v5l3 2" />
          </svg>
          <p className="text-sm font-medium text-text">No queries yet</p>
          <p className="max-w-[260px] text-sm text-text-3">
            Run a query in the editor and it’ll appear here so you can re-open or
            re-run it.
          </p>
        </div>
      ) : (
        pageEntries.map((entry) => (
          <QueryHistoryRow
            key={`${entry.queryExecutionId}-${entry.submittedAt}`}
            entry={entry}
            onReopen={() => onReopen(entry)}
            onRerun={() => onRerun(entry)}
            rerunDisabled={rerunDisabled}
          />
        ))
      )}
    </Drawer>
  );
}
