import {useMemo, useState} from 'react';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {PageLayout} from '../../components/PageLayout';
import {useAuth} from '../auth';
import {useConnections} from '../query/useConnections';
import {Toast, type ToastState} from '../query/Toast';
import {CreateSharedConnectionDialog} from './CreateSharedConnectionDialog';
import {useCreateSharedConnection} from './useCreateSharedConnection';
import {useManageMembers} from './useManageMembers';
import {useLeaveOrDeleteSharedSpace} from './useLeaveOrDeleteSharedSpace';
import {ManageMembersDrawer} from './ManageMembersDrawer';
import {LeaveSharedSpaceDialog} from './LeaveSharedSpaceDialog';
import {DeleteSharedSpaceDialog} from './DeleteSharedSpaceDialog';
import {RefreshConnectionsButton} from './RefreshConnectionsButton';
import {connectionStatusLabel} from './connectionStatus';
import type {SharedConnectionRole, SharedConnectionStatus} from './sharedSpaces.types';

// One renderable shared-connection row, normalized from the cache (via
// useConnections) and the local optimistic pending list.
type ConnectionRow = {
  name: string;
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string;
  /** Owner-readable projection (owner rows only). */
  members?: string[];
  /** ISO; drives the "created <date>" meta line. */
  createdAt?: string;
  /** Owner username (member rows); drives the "owner: <name>" meta line. */
  owner?: string;
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
  const [managing, setManaging] = useState<ConnectionRow | null>(null);
  const [leaving, setLeaving] = useState<ConnectionRow | null>(null);
  const [deleting, setDeleting] = useState<ConnectionRow | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  // Connections the user has just left/deleted, shown optimistically as
  // leaving/deleting until a Refresh reconciles them away (mirrors `retrying`).
  const [transitioning, setTransitioning] = useState<Map<string, 'leaving' | 'deleting'>>(new Map());
  // Failed entries the user has dismissed, and ones being retried (shown
  // optimistically as provisioning). Both are local-only; a Refresh reconciles
  // against the authoritative cache.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [retrying, setRetrying] = useState<Set<string>>(new Set());

  const rows = useMemo<ConnectionRow[]>(() => {
    const fromCache: ConnectionRow[] = connections
      .filter((c) => c.kind === 'shared')
      .map((c) => ({
        name: c.database,
        role: c.role ?? 'member',
        status: c.status ?? 'active',
        reason: c.reason,
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
        // A retried entry shows provisioning until the cache reconciles it to active
        // (then the override is inert, so the auto-poll resolves it without a Refresh).
        .map((r) => (retrying.has(r.name) && r.status !== 'active' ? {...r, status: 'provisioning' as const} : r))
        .map((r) => {
          const t = transitioning.get(r.name);
          return t ? {...r, status: t} : r;
        })
        .sort((a, b) => a.name.localeCompare(b.name))
    );
  }, [connections, pending, dismissed, retrying, transitioning]);

  const handleRefresh = () => {
    // The cache is authoritative after a refresh — drop local-only overrides so
    // a still-failed entry reappears and a now-active retry/leave/delete reflects
    // reality (a successful leave/delete is simply gone from the cache).
    setDismissed(new Set());
    setRetrying(new Set());
    setTransitioning(new Map());
    void refresh();
  };

  const handleCreate = async (name: string) => {
    setDialogOpen(false);
    const result = await create(name);
    if (result.success) {
      setToast({variant: 'success', message: `Creating “${name}”…`});
      void reconcile(); // auto-poll until the pipeline writes the cache
    } else {
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  const handleAddMembers = async (space: string, toAdd: string[]) => {
    const result = await addMembers(space, toAdd);
    if (result.success) {
      const n = toAdd.length;
      setToast({
        variant: 'success',
        message: `Adding ${n} member${n === 1 ? '' : 's'} to “${space}”…`
      });
      void reconcile();
    } else {
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  const handleRemoveMembers = async (space: string, toRemove: string[]) => {
    const result = await removeMembers(space, toRemove);
    if (result.success) {
      setToast({
        variant: 'success',
        message: `Removing ${toRemove.join(', ')} from “${space}”…`
      });
      void reconcile();
    } else {
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  const handleLeave = async (space: string) => {
    const result = await leave(space);
    setLeaving(null);
    if (result.success) {
      setTransitioning((prev) => new Map(prev).set(space, 'leaving'));
      setToast({variant: 'success', message: `Leaving “${space}”…`});
      void reconcile();
    } else {
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  const handleDelete = async (space: string) => {
    const result = await remove(space);
    setDeleting(null);
    if (result.success) {
      setTransitioning((prev) => new Map(prev).set(space, 'deleting'));
      setToast({variant: 'success', message: `Deleting “${space}”…`});
      void reconcile();
    } else {
      setToast({variant: 'danger', message: result.error.message});
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
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  const handleRetry = async (name: string) => {
    setRetrying((prev) => new Set(prev).add(name));
    const result = await create(name);
    if (result.success) {
      setToast({variant: 'success', message: `Retrying “${name}”…`});
      void reconcile();
    } else {
      setRetrying((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
      setToast({variant: 'danger', message: result.error.message});
    }
  };

  return (
    <>
      {/* Content is left-aligned (no mx-auto) and capped at 920px so the cards
          don't stretch across very wide viewports. */}
      <PageLayout
        title="Shared connections"
        subtitle="Spaces you own or belong to. Files, tables, and the database are shared by all members."
        contentClassName="max-w-[920px] gap-3"
        actions={
          <>
            <RefreshConnectionsButton
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
            />
            <Button
              variant="primary"
              onClick={() => setDialogOpen(true)}>
              New shared connection
            </Button>
          </>
        }>
        {error && <Banner variant="danger">Couldn&apos;t load your shared connections: {error}</Banner>}

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
                onManage={() => setManaging(row)}
                onDelete={() => setDeleting(row)}
                onLeave={() => setLeaving(row)}
                onDismiss={() => void handleDismiss(row.name)}
                onRetry={() => void handleRetry(row.name)}
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
          onClose={() => setManaging(null)}
          space={managing.name}
          owner={username}
          members={managing.members ?? [username]}
          unavailable={managing.members === undefined}
          busy={membersBusy}
          onAddMembers={(toAdd) => void handleAddMembers(managing.name, toAdd)}
          onRemoveMembers={(toRemove) => void handleRemoveMembers(managing.name, toRemove)}
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
      {toast && (
        <Toast
          {...toast}
          onDismiss={() => setToast(null)}
        />
      )}
    </>
  );
}

// Secondary meta line under a card's name. Owner cards show member count + created
// date; member cards show the owner; transient states explain that the change
// applies on the next refresh. Null when there's nothing to show.
function metaLine(row: ConnectionRow): string | null {
  if (row.status === 'active') {
    if (row.role === 'owner') {
      const parts: string[] = [];
      if (row.members) {
        const n = row.members.length;
        parts.push(`${n} member${n === 1 ? '' : 's'}`);
      }
      const created = formatCreated(row.createdAt);
      if (created) parts.push(`created ${created}`);
      return parts.length > 0 ? parts.join(' · ') : null;
    }
    return row.owner ? `owner: ${row.owner}` : null;
  }
  if (row.status === 'provisioning') return 'Creating prefix, database, and your access — applies on next refresh';
  if (row.status === 'leaving') return 'Leaving — applies on next refresh';
  if (row.status === 'deleting') return 'Deleting — applies on next refresh';
  return null; // failed: the reason is shown in its own line
}

function formatCreated(iso?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
}

function ConnectionRowItem({
  row,
  onManage,
  onDelete,
  onLeave,
  onDismiss,
  onRetry
}: {
  row: ConnectionRow;
  onManage: () => void;
  onDelete: () => void;
  onLeave: () => void;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  const isOwner = row.role === 'owner';
  const meta = metaLine(row);
  return (
    <li className="flex items-center gap-3 rounded-lg border border-border bg-surface px-5 py-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-mono text-base font-semibold text-text">{row.name}</span>
          <RolePill role={row.role} />
          <StatusBadge status={row.status} />
        </div>
        {meta && <div className="mt-1 text-xs text-text-3">{meta}</div>}
        {row.status === 'failed' && (
          <div className="mt-1 text-xs text-danger">{row.reason ?? 'Provisioning failed.'}</div>
        )}
      </div>
      <div className="flex flex-none items-center gap-2">
        {row.status === 'failed' ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDismiss}>
              Dismiss
            </Button>
            <Button
              size="sm"
              onClick={onRetry}>
              Retry
            </Button>
          </>
        ) : isOwner ? (
          <>
            <Button
              size="sm"
              onClick={onManage}
              disabled={row.status !== 'active'}>
              Manage
            </Button>
            {row.status === 'active' && (
              <Button
                variant="ghost"
                size="sm"
                className="text-danger hover:bg-danger-soft hover:text-danger"
                onClick={onDelete}>
                Delete
              </Button>
            )}
          </>
        ) : (
          row.status === 'active' && (
            <Button
              variant="ghost"
              size="sm"
              className="text-danger hover:bg-danger-soft hover:text-danger"
              onClick={onLeave}>
              Leave
            </Button>
          )
        )}
      </div>
    </li>
  );
}

function RolePill({role}: {role: SharedConnectionRole}) {
  return (
    <span className="flex-none rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-semibold capitalize text-text-2">
      {role}
    </span>
  );
}

// Status as a colored dot + text label; the label always carries the meaning, so
// the color/dot is never the only signal. The dot pulses for transient states.
function StatusBadge({status}: {status: SharedConnectionStatus}) {
  const transient = status === 'provisioning' || status === 'leaving' || status === 'deleting';
  const tone =
    status === 'active'
      ? 'bg-success-soft text-success'
      : status === 'failed'
        ? 'bg-danger-soft text-danger'
        : 'bg-warning-soft text-warning';
  return (
    <span
      className={`inline-flex flex-none items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>
      <span className={`h-[7px] w-[7px] rounded-full bg-current ${transient ? 'animate-pulse' : ''}`} />
      {connectionStatusLabel(status)}
    </span>
  );
}
