import {useMemo, useState, type ReactNode} from 'react';
import {Badge} from '../../components/Badge';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {PageLayout} from '../../components/PageLayout';
import {StatusPill} from '../../components/StatusPill';
import {cx} from '../../lib/cx';
import {formatAbsoluteDate} from '../../lib/format';
import {useAuth} from '../auth';
import {useConnections} from '../connections/useConnections';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {CreateSharedConnectionDialog} from './CreateSharedConnectionDialog';
import {useCreateSharedConnection} from './useCreateSharedConnection';
import {useManageMembers} from './useManageMembers';
import {useLeaveOrDeleteSharedSpace} from './useLeaveOrDeleteSharedSpace';
import {ManageMembersDrawer} from './ManageMembersDrawer';
import {MemberRosterDrawer} from './MemberRosterDrawer';
import {LeaveSharedSpaceDialog} from './LeaveSharedSpaceDialog';
import {DeleteSharedSpaceDialog} from './DeleteSharedSpaceDialog';
import {RefreshConnectionsButton} from './RefreshConnectionsButton';
import {connectionStatusLabel} from '../connections/connectionStatus';
import type {FailedAction, Member, SharedConnectionRole, SharedConnectionStatus} from './sharedSpaces.types';

// One renderable shared-connection row, normalized from the cache (via
// useConnections) and the local optimistic pending list.
type ConnectionRow = {
  name: string;
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string;
  /** Member roster with per-member join status. On owner rows (Manage) and, since
   * Member rows too (read-only View members). Absent on legacy entries. */
  members?: Member[];
  /** ISO; drives the "created <date>" meta line. */
  createdAt?: string;
  /** Owner username (member rows); drives the "owner: <name>" meta line. */
  owner?: string;
  /** Which verb failed, so Retry enqueues that one and Dismiss is offered only where it acts. */
  failedAction?: FailedAction;
};

/**
 * Management surface for shared connections: lists the user's spaces (name + role +
 * status) with Refresh and Create. The list comes from the one `useConnections` hook
 * (the same source the Query schema rail and Files list read), merged with local
 * optimistic pending entries so a just-created connection shows provisioning before
 * the pipeline writes the cache.
 */
export function ConnectionsPage() {
  const {user} = useAuth();
  const username = user?.username ?? null;

  const {connections, isLoading, error, refresh, isRefreshing, reconcile} = useConnections(username);
  const {create, busy, pending} = useCreateSharedConnection(username);
  const {addMembers, removeMembers, busy: membersBusy} = useManageMembers(username);
  const {leave, remove, forget, busy: lifecycleBusy} = useLeaveOrDeleteSharedSpace(username);

  const [dialogOpen, setDialogOpen] = useState(false);
  // Track the managed space by NAME (not a row snapshot) so the drawer re-derives
  // from the live `rows` — a Refresh that flips a member Pending → Active is then
  // reflected in the open drawer without reopening it.
  const [managingName, setManagingName] = useState<string | null>(null);
  // Same NAME-tracked pattern as `managingName`, for a member's read-only roster view
  // so a Refresh keeps the open drawer in sync.
  const [viewingName, setViewingName] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<ConnectionRow | null>(null);
  const [deleting, setDeleting] = useState<ConnectionRow | null>(null);
  const toast = useToast();
  // Connections the user has just left/deleted, shown optimistically as
  // leaving/deleting until a Refresh reconciles them away (mirrors `retrying`).
  const [transitioning, setTransitioning] = useState<Map<string, 'leaving' | 'deleting'>>(new Map());
  // Failed entries the user has dismissed, and ones being retried (shown
  // optimistically as provisioning). Both are local-only; a Refresh reconciles
  // against the authoritative cache.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Keyed by the verb being retried, not a bare set: the optimistic override forces a status,
  // which makes `row.status === 'failed'` false on the next render — so without the kind carried
  // here, failedAction-based logic flips a retried delete back to looking like a create.
  const [retrying, setRetrying] = useState<Map<string, FailedAction>>(new Map());

  const rows = useMemo<ConnectionRow[]>(() => {
    const fromCache: ConnectionRow[] = connections
      .filter((c) => c.kind === 'shared')
      .map((c) => ({
        name: c.database,
        role: c.role ?? 'member',
        status: c.status ?? 'active',
        reason: c.reason,
        failedAction: c.failedAction,
        members: c.members,
        createdAt: c.createdAt,
        owner: c.owner
      }));
    const cacheNames = new Set(fromCache.map((r) => r.name));
    // Local pending entries not yet reflected in the cache (cache wins on dupes).
    const fromPending: ConnectionRow[] = pending
      .filter((p) => !cacheNames.has(p.name))
      .map((p) => ({name: p.name, role: p.role, status: p.status}));
    return (
      [...fromCache, ...fromPending]
        .filter((r) => !dismissed.has(r.name))
        // A retried entry shows the status its own verb is heading for, until the cache
        // reconciles (then the override is inert, so the auto-poll resolves it without a
        // Refresh). A retried DELETE showing 'provisioning' would be a row that lies for the
        // length of the run.
        .map((r) => {
          const kind = retrying.get(r.name);
          if (!kind || r.status === 'active') return r;
          return {...r, status: kind === 'delete' ? ('deleting' as const) : ('provisioning' as const)};
        })
        .map((r) => {
          const t = transitioning.get(r.name);
          return t ? {...r, status: t} : r;
        })
        .sort((a, b) => a.name.localeCompare(b.name))
    );
  }, [connections, pending, dismissed, retrying, transitioning]);

  // The live row for the open Manage drawer, re-derived from `rows` each render so a
  // Refresh (or auto-poll) surfaces member/status changes without reopening.
  const managing = useMemo(
    () => (managingName ? (rows.find((r) => r.name === managingName) ?? null) : null),
    [managingName, rows]
  );

  // Same for the member roster drawer.
  const viewing = useMemo(
    () => (viewingName ? (rows.find((r) => r.name === viewingName) ?? null) : null),
    [viewingName, rows]
  );

  const handleRefresh = () => {
    // The cache is authoritative after a refresh — drop local-only overrides so
    // a still-failed entry reappears and a now-active retry/leave/delete reflects
    // reality (a successful leave/delete is simply gone from the cache).
    setDismissed(new Set());
    setRetrying(new Map());
    setTransitioning(new Map());
    void refresh();
  };

  const handleCreate = async (name: string) => {
    setDialogOpen(false);
    const result = await create(name);
    if (result.success) {
      toast.push({variant: 'success', message: `Creating “${name}”…`});
      void reconcile(); // auto-poll until the pipeline writes the cache
    } else {
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleAddMembers = async (space: string, toAdd: string[]) => {
    const result = await addMembers(space, toAdd);
    if (result.success) {
      const n = toAdd.length;
      toast.push({
        variant: 'success',
        message: `Adding ${n} member${n === 1 ? '' : 's'} to “${space}”…`
      });
      void reconcile();
    } else {
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleRemoveMembers = async (space: string, toRemove: string[]) => {
    const result = await removeMembers(space, toRemove);
    if (result.success) {
      toast.push({
        variant: 'success',
        message: `Removing ${toRemove.join(', ')} from “${space}”…`
      });
      void reconcile();
    } else {
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleLeave = async (space: string) => {
    const result = await leave(space);
    setLeaving(null);
    if (result.success) {
      setTransitioning((prev) => new Map(prev).set(space, 'leaving'));
      toast.push({variant: 'success', message: `Leaving “${space}”…`});
      void reconcile();
    } else {
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleDelete = async (space: string) => {
    const result = await remove(space);
    setDeleting(null);
    if (result.success) {
      setTransitioning((prev) => new Map(prev).set(space, 'deleting'));
      toast.push({variant: 'success', message: `Deleting “${space}”…`});
      void reconcile();
    } else {
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleDismiss = async (name: string) => {
    // Durably clear the entry: `forget` removes it from the cache the pipeline writes
    // (a plain local hide reappears on reload). Optimistically hide + reconcile; on a
    // failed enqueue, un-hide and surface the error.
    setDismissed((prev) => new Set(prev).add(name));
    const result = await forget(name);
    if (result.success) {
      void reconcile();
    } else {
      setDismissed((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  const handleRetry = async (row: ConnectionRow) => {
    // A `deleting` row IS a delete, whatever its cache entry carries — the entry the validator
    // writes has no `failedAction` at all, so a nullish default would send `create` here and
    // retry the one verb that cannot work. Create is refused on a name that was ever used, and
    // the refusal overwrites the row's own discriminator, so nothing can enqueue a delete after
    // that: the workspace is stranded with no affordance that does anything.
    const kind: FailedAction = row.status === 'deleting' ? 'delete' : (row.failedAction ?? 'create');
    setRetrying((prev) => new Map(prev).set(row.name, kind));
    const result = kind === 'delete' ? await remove(row.name) : await create(row.name);
    if (result.success) {
      toast.push({variant: 'success', message: `Retrying “${row.name}”…`});
      void reconcile();
    } else {
      setRetrying((prev) => {
        const next = new Map(prev);
        next.delete(row.name);
        return next;
      });
      toast.push({variant: 'danger', message: toUserText(result.error)});
    }
  };

  return (
    <>
      {/* Content is left-aligned (no mx-auto) and capped at 920px so the cards
          don't stretch across very wide viewports. */}
      <PageLayout
        title="Shared connections"
        subtitle={
          <>
            Spaces you own or belong to.
            {/* Full sentence at desktop; trimmed below. One
                span (display:none removes it from the a11y tree), so the subtitle
                is never read doubled. */}
            <span className="hidden desktop:inline"> Files, tables, and the database are shared by all members.</span>
          </>
        }
        contentClassName="max-w-[920px] gap-3"
        stackActionsOnMobile
        actions={
          <>
            <RefreshConnectionsButton
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
            />
            <Button
              variant="primary"
              aria-label="New shared connection"
              className="w-full tablet:w-auto"
              onClick={() => setDialogOpen(true)}>
              {/* "New" below desktop, full label at desktop; aria-label carries
                  the full intent at every width. */}
              <span className="desktop:hidden">New</span>
              <span className="hidden desktop:inline">New shared connection</span>
            </Button>
          </>
        }>
        {!!error && (
          <Banner variant="danger">
            Couldn&apos;t load your shared connections. Try Refresh, or contact the Administrator.
          </Banner>
        )}

        {isLoading ? (
          <p
            role="status"
            className="px-1 py-10 text-center text-sm text-text-3">
            Loading your connections…
          </p>
        ) : rows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-surface-2 px-5 py-10 text-center text-sm text-text-2">
            No shared connections yet — create one or ask an owner to add you.
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {rows.map((row) => (
              <ConnectionRowItem
                key={row.name}
                row={row}
                onManage={() => setManagingName(row.name)}
                onView={() => setViewingName(row.name)}
                onDelete={() => setDeleting(row)}
                onLeave={() => setLeaving(row)}
                onDismiss={() => void handleDismiss(row.name)}
                onRetry={() => void handleRetry(row)}
                submitting={transitioning.has(row.name) || retrying.has(row.name)}
              />
            ))}
          </ul>
        )}
      </PageLayout>

      {dialogOpen && (
        <CreateSharedConnectionDialog
          busy={busy}
          onCreate={handleCreate}
          onCancel={() => setDialogOpen(false)}
        />
      )}
      {managing && username && (
        <ManageMembersDrawer
          open
          onClose={() => setManagingName(null)}
          space={managing.name}
          owner={username}
          members={managing.members ?? [{username, status: 'active'}]}
          unavailable={managing.members === undefined}
          busy={membersBusy}
          onRefresh={handleRefresh}
          refreshing={isRefreshing}
          onAddMembers={(toAdd) => void handleAddMembers(managing.name, toAdd)}
          onRemoveMembers={(toRemove) => void handleRemoveMembers(managing.name, toRemove)}
        />
      )}
      {viewing && username && (
        <MemberRosterDrawer
          open
          onClose={() => setViewingName(null)}
          space={viewing.name}
          owner={viewing.owner ?? ''}
          members={viewing.members ?? []}
          unavailable={viewing.members === undefined}
          viewer={username}
          onRefresh={handleRefresh}
          refreshing={isRefreshing}
        />
      )}
      {leaving && (
        <LeaveSharedSpaceDialog
          space={leaving.name}
          busy={lifecycleBusy}
          onConfirm={() => void handleLeave(leaving.name)}
          onCancel={() => setLeaving(null)}
        />
      )}
      {deleting && (
        <DeleteSharedSpaceDialog
          space={deleting.name}
          busy={lifecycleBusy}
          onConfirm={() => void handleDelete(deleting.name)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </>
  );
}

// Secondary meta line under a card's name. Owner cards show member count + created
// date; member cards show the owner; transient states explain that the change
// applies on the next refresh. Null when there's nothing to show.
function metaLine(row: ConnectionRow, submitting: boolean): string | null {
  if (row.status === 'active') {
    if (row.role === 'owner') {
      const parts: string[] = [];
      if (row.members) {
        const n = row.members.length;
        parts.push(`${n} member${n === 1 ? '' : 's'}`);
        const pending = row.members.filter((m) => m.status === 'pending').length;
        if (pending > 0) parts.push(`${pending} pending`);
      }
      const created = formatCreated(row.createdAt);
      if (created) parts.push(`created ${created}`);
      return parts.length > 0 ? parts.join(' · ') : null;
    }
    return row.owner ? `owner: ${row.owner}` : null;
  }
  if (row.status === 'provisioning') return 'Creating prefix, database, and your access — applies on next refresh';
  if (row.status === 'leaving') return 'Leaving — applies on next refresh';
  // A row the validator left in `deleting` never reconciles on its own, so the reassuring
  // sentence is false there; it is true only while the user's own delete is in flight.
  // A Refresh drops the local override, so after one there is no way to tell a delete in
  // flight from one that stopped — the cache says `deleting` for both. The sentence has to be
  // true of both, and Retry is safe either way because deleting again is idempotent.
  if (row.status === 'deleting') {
    return submitting ? 'Deleting — applies on next refresh' : 'Deleting — if this doesn’t clear, Retry';
  }
  return null; // failed: the reason is shown in its own line
}

function formatCreated(iso?: string): string | null {
  if (!iso) return null;
  return formatAbsoluteDate(iso) || null;
}

function ConnectionRowItem({
  row,
  submitting,
  onManage,
  onView,
  onDelete,
  onLeave,
  onDismiss,
  onRetry
}: {
  row: ConnectionRow;
  /** True while this row's own status is a local optimistic override rather than the cache's. */
  submitting: boolean;
  onManage: () => void;
  onView: () => void;
  onDelete: () => void;
  onLeave: () => void;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  const isOwner = row.role === 'owner';
  const meta = metaLine(row, submitting);

  // The applicable actions per state, each full-width on mobile / auto at ≥ tablet.
  const dangerGhost = 'w-full text-danger hover:bg-danger-soft hover:text-danger tablet:w-auto';
  const actions: ReactNode[] = [];
  // A row stuck in `deleting` — the validator writes that status and a run that dies never
  // clears it — needs an exit that is not an operator. It gets the same Retry. A row that is
  // `deleting` only because the user just confirmed one is indistinguishable in `rows`, so the
  // optimistic flag is what tells them apart; offering Retry there would put the button beside
  // a delete submitted two seconds ago.
  const stuckDeleting = row.status === 'deleting' && !submitting;
  if (row.status === 'failed' || stuckDeleting) {
    // Dismiss is suppressed on anything delete-shaped. `forget` is a server-side no-op for a
    // space that was ever usable, so the button would present an action that does nothing —
    // and the row it would clear is the only affordance left for retrying the delete.
    if (row.status === 'failed' && (row.failedAction ?? 'create') === 'create') {
      actions.push(
        <Button
          key="dismiss"
          variant="ghost"
          size="sm"
          className="w-full tablet:w-auto"
          onClick={onDismiss}>
          Dismiss
        </Button>
      );
    }
    actions.push(
      <Button
        key="retry"
        size="sm"
        className="w-full tablet:w-auto"
        onClick={onRetry}>
        Retry
      </Button>
    );
  } else if (isOwner) {
    actions.push(
      <Button
        key="manage"
        size="sm"
        className="w-full tablet:w-auto"
        onClick={onManage}
        disabled={row.status !== 'active'}>
        Manage
      </Button>
    );
    if (row.status === 'active') {
      actions.push(
        <Button
          key="delete"
          variant="ghost"
          size="sm"
          className={dangerGhost}
          onClick={onDelete}>
          Delete
        </Button>
      );
    }
  } else if (row.status === 'active') {
    actions.push(
      <Button
        key="view"
        variant="ghost"
        size="sm"
        className="w-full tablet:w-auto"
        onClick={onView}>
        View members
      </Button>,
      <Button
        key="leave"
        variant="ghost"
        size="sm"
        className={dangerGhost}
        onClick={onLeave}>
        Leave
      </Button>
    );
  }

  return (
    // Stacked on mobile (name / pills / meta then a full-width action row); a
    // single horizontal row with right-aligned actions at ≥ tablet.
    <li className="flex flex-col gap-3 rounded-lg border border-border bg-surface px-5 py-4 tablet:flex-row tablet:items-center">
      <div className="min-w-0 flex-1">
        {/* Name on line 1, pills wrap under it on mobile; all inline (wrapping
            only on collision) at ≥ tablet via `tablet:contents`. */}
        <div className="flex flex-col gap-1 tablet:flex-row tablet:flex-wrap tablet:items-center tablet:gap-2">
          <span className="truncate font-mono text-base font-semibold text-text">{row.name}</span>
          <div className="flex flex-wrap items-center gap-2 tablet:contents">
            <RolePill role={row.role} />
            <StatusBadge status={row.status} />
          </div>
        </div>
        {meta && <div className="mt-1 text-xs text-text-3">{meta}</div>}
        {row.status === 'failed' && (
          <div className="mt-1 text-xs text-danger">
            {row.reason ?? (row.failedAction === 'delete' ? 'Removing this workspace failed.' : 'Provisioning failed.')}
          </div>
        )}
      </div>
      {actions.length > 0 && (
        <div
          className={cx(
            'grid w-full gap-2 tablet:flex tablet:w-auto tablet:flex-none tablet:items-center',
            actions.length === 1 ? 'grid-cols-1' : 'grid-cols-2'
          )}>
          {actions}
        </div>
      )}
    </li>
  );
}

function RolePill({role}: {role: SharedConnectionRole}) {
  return <Badge className="flex-none capitalize">{role}</Badge>;
}

// Status as a colored dot + text label; the label always carries the meaning, so
// the color/dot is never the only signal. The dot pulses for transient states.
function StatusBadge({status}: {status: SharedConnectionStatus}) {
  const transient = status === 'provisioning' || status === 'leaving' || status === 'deleting';
  const tone = status === 'active' ? 'success' : status === 'failed' ? 'danger' : 'warning';
  return (
    <StatusPill
      tone={tone}
      pulse={transient}>
      {connectionStatusLabel(status)}
    </StatusPill>
  );
}
