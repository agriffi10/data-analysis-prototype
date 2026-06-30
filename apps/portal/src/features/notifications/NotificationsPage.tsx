import {useState} from 'react';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {IconButton} from '../../components/IconButton';
import {PageLayout} from '../../components/PageLayout';
import {Pager} from '../../components/Pager';
import {cx} from '../../lib/cx';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useAuth} from '../auth';
import {Toast, type ToastState} from '../query/Toast';
import {useNotifications} from './useNotifications';
import {NotificationRow} from './NotificationRow';

const PAGE_SIZE = 10; // FR-004 (mirrors the history pager constant, sized to 10)

type Filter = 'all' | 'unread';

// SPEC-060 FR-002/004/005/006: the routed notifications page. Owns the SPEC-059
// `useNotifications` hook and renders the newest-first list with 10/page Prev/Next,
// per-row Mark-read + a Mark-all-read bulk control, a Refresh, and the
// empty/loading/error states. Actions are optimistic (the hook updates the cache +
// header indicator instantly); a failed enqueue rolls back and raises a danger
// Toast. There is no delete anywhere on the page.
export function NotificationsPage() {
  const {user} = useAuth();
  const username = user?.username ?? null;

  const [toast, setToast] = useState<ToastState | null>(null);
  const {notifications, unreadCount, isLoading, isError, refresh, markRead, markAllRead} = useNotifications(username, {
    onMutationError: (message) => setToast({variant: 'danger', message}),
    // Stop the 60s background poll while the user is on this page so it can't re-pull
    // the inbox and fight in-page mark-read actions (the writer is the async source of
    // truth); the header bell keeps polling for new arrivals.
    pausePoll: true
  });

  usePageTitle(unreadCount > 0 ? `Notifications (${unreadCount})` : 'Notifications');

  // All / Unread segmented filter. The list (and pager) operate on the visible
  // subset; switching the filter resets to the first page.
  const [filter, setFilter] = useState<Filter>('all');
  const visible = filter === 'unread' ? notifications.filter((n) => !n.read) : notifications;

  // Client-side Prev/Next pager over the in-memory newest-first list (SPEC-042
  // pattern). Clamp so a shrunk/condensed list never strands on a blank page, and
  // snap to the newest page when new notifications arrive (the list grows).
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * PAGE_SIZE;
  const pageItems = visible.slice(start, start + PAGE_SIZE);

  const [prevLen, setPrevLen] = useState(notifications.length);
  if (notifications.length !== prevLen) {
    setPrevLen(notifications.length);
    if (notifications.length > prevLen) setPageIndex(0);
  }

  const applyFilter = (next: Filter) => {
    setFilter(next);
    setPageIndex(0);
  };

  const [refreshing, setRefreshing] = useState(false);
  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
    setPageIndex(0);
  };

  return (
    <>
      <PageLayout
        title="Notifications"
        contentClassName="max-w-[760px] gap-2"
        actions={
          <>
            <FilterTabs
              filter={filter}
              onChange={applyFilter}
            />
            <IconButton
              label="Refresh notifications"
              size="sm"
              disabled={refreshing}
              onClick={() => void handleRefresh()}>
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className={cx('h-4 w-4', refreshing && 'animate-spin')}
                aria-hidden="true">
                <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
                <path d="M21 3v5h-5" />
                <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
                <path d="M3 21v-5h5" />
              </svg>
            </IconButton>
            <Button
              variant="default"
              size="sm"
              disabled={unreadCount === 0}
              onClick={() => markAllRead()}>
              Mark all read
            </Button>
          </>
        }>
        {/* A read/refresh error is shown above the list and never clears it, so a
            failed Refresh is non-destructive (FR-006). */}
        {isError && (
          <Banner
            variant="danger"
            title="Couldn’t load notifications."
            className="mb-2">
            <button
              type="button"
              onClick={() => void handleRefresh()}
              className="font-semibold underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              Try again
            </button>
          </Banner>
        )}

        {isLoading ? (
          <p
            role="status"
            className="px-1 py-10 text-center text-sm text-text-3">
            Loading notifications…
          </p>
        ) : visible.length === 0 ? (
          isError ? null : (
            <div className="rounded-lg border border-dashed border-border bg-surface-2 px-5 py-12 text-center">
              <p className="text-sm font-medium text-text">You’re all caught up</p>
              <p className="mt-1 text-sm text-text-3">
                {filter === 'unread'
                  ? 'No unread notifications.'
                  : 'New notifications about your shared spaces will appear here.'}
              </p>
            </div>
          )
        ) : (
          <>
            <ul className="flex flex-col gap-2">
              {pageItems.map((notification) => (
                <NotificationRow
                  key={notification.id}
                  notification={notification}
                  onMarkRead={markRead}
                />
              ))}
            </ul>
            <Pager
              className="mt-2"
              hasPrev={safeIndex > 0}
              hasNext={safeIndex < pageCount - 1}
              onPrev={() => setPageIndex(Math.max(0, safeIndex - 1))}
              onNext={() => setPageIndex(Math.min(pageCount - 1, safeIndex + 1))}
              label={
                <>
                  {start + 1}–{start + pageItems.length} of {visible.length}
                  <span className="sr-only"> (page {safeIndex + 1})</span>
                </>
              }
            />
          </>
        )}
      </PageLayout>

      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          onDismiss={() => setToast(null)}
        />
      )}
    </>
  );
}

// All / Unread segmented control (design `.seg`). Two mutually-exclusive toggle
// buttons in a labeled group; the active one carries `aria-pressed` so the choice
// is exposed to assistive tech (it's never conveyed by styling alone).
function FilterTabs({filter, onChange}: {filter: Filter; onChange: (next: Filter) => void}) {
  return (
    <div
      role="group"
      aria-label="Filter notifications"
      className="inline-flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
      {(['all', 'unread'] as const).map((value) => {
        const active = filter === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(value)}
            className={cx(
              'h-7 rounded-sm px-3 text-sm font-medium capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active
                ? 'bg-surface font-semibold text-accent-text shadow-sm'
                : 'text-text-2 hover:text-text'
            )}>
            {value}
          </button>
        );
      })}
    </div>
  );
}
