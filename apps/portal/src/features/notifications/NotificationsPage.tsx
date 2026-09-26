import {useState} from 'react';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {PageLayout} from '../../components/PageLayout';
import {Pager} from '../../components/Pager';
import {RefreshIconButton} from '../../components/RefreshIconButton';
import {SegmentedFilter} from '../../components/SegmentedFilter';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useClientPager} from '../../hooks/useClientPager';
import {useAuth} from '../auth';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {useNotifications} from './useNotifications';
import {NotificationRow} from './NotificationRow';

const PAGE_SIZE = 10;

type Filter = 'all' | 'unread';

const FILTERS = [
  {value: 'all', label: 'All'},
  {value: 'unread', label: 'Unread'}
] as const satisfies readonly {value: Filter; label: string}[];

/**
 * Routed notifications page: newest-first list with 10/page Prev/Next, per-row
 * Mark-read, Mark-all-read, Refresh, and empty/loading/error states. Actions are
 * optimistic via `useNotifications`; a failed enqueue rolls back and raises a
 * danger Toast. There is no delete anywhere on the page.
 */
export function NotificationsPage() {
  const {user} = useAuth();
  const username = user?.username ?? null;

  const toast = useToast();
  const {notifications, unreadCount, isLoading, isError, refresh, markRead, markAllRead} = useNotifications(username, {
    onMutationError: (error) => toast.push({variant: 'danger', message: toUserText(error)}),
    // Stop the 60s background poll while the user is on this page so it can't re-pull
    // the inbox and fight in-page mark-read actions (the writer is the async source of
    // truth); the header bell keeps polling for new arrivals.
    pausePoll: true
  });

  usePageTitle(unreadCount > 0 ? `Notifications (${unreadCount})` : 'Notifications');

  // The list and pager operate on the filtered subset; switching filters resets to page 1.
  const [filter, setFilter] = useState<Filter>('all');
  const visible = filter === 'unread' ? notifications.filter((n) => !n.read) : notifications;

  // Clamped client-side pager: a shrunk list never strands the user on a blank page.
  const {pageItems, pagerProps, resetToFirst} = useClientPager(visible, PAGE_SIZE);

  // Snap to the newest page when new notifications arrive.
  const [prevLen, setPrevLen] = useState(notifications.length);
  if (notifications.length !== prevLen) {
    setPrevLen(notifications.length);
    if (notifications.length > prevLen) resetToFirst();
  }

  const applyFilter = (next: Filter) => {
    setFilter(next);
    resetToFirst();
  };

  const [refreshing, setRefreshing] = useState(false);
  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
    resetToFirst();
  };

  return (
    <PageLayout
      title="Notifications"
      contentClassName="max-w-[760px] gap-2"
      stackActionsOnMobile
      actions={
        <>
          <SegmentedFilter
            label="Filter notifications"
            options={FILTERS}
            value={filter}
            onChange={applyFilter}
          />
          <RefreshIconButton
            label="Refresh notifications"
            busy={refreshing}
            onClick={() => void handleRefresh()}
          />
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
            failed Refresh is non-destructive. */}
      {isError && (
        <Banner
          variant="danger"
          title="Couldn’t load notifications."
          retry={() => void handleRefresh()}
          className="mb-2"
        />
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
              {filter === 'unread' ? 'No unread notifications.' : 'New notifications will appear here.'}
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
            {...pagerProps}
          />
        </>
      )}
    </PageLayout>
  );
}
