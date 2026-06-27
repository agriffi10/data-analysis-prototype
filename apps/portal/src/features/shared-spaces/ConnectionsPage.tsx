import { useMemo, useState } from 'react';
import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { useAuth } from '../auth';
import { useConnections } from '../query/useConnections';
import { Toast, type ToastState } from '../query/Toast';
import { CreateSharedConnectionDialog } from './CreateSharedConnectionDialog';
import { useCreateSharedConnection } from './useCreateSharedConnection';
import { RefreshConnectionsButton } from './RefreshConnectionsButton';
import { connectionStatusLabel } from './connectionStatus';
import type {
  SharedConnectionRole,
  SharedConnectionStatus,
} from './sharedSpaces.types';

// One renderable shared-connection row, normalized from the cache (via
// useConnections) and the local optimistic pending list (SPEC-051 create).
type ConnectionRow = {
  name: string;
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string;
};

// SPEC-052 FR-002: the management surface for shared connections. Lists the user's
// spaces (name + role + status) with a Refresh control and the Create CTA. The
// list comes from the ONE `useConnections` hook (the same source the Query schema
// rail and Files list read), merged with the local optimistic pending entries so a
// just-created connection shows "provisioning…" before the pipeline writes the
// cache. Member management / leave / delete entry points land in SPEC-053/054.
export function ConnectionsPage() {
  const { user } = useAuth();
  const username = user?.username ?? null;

  const { connections, isLoading, error, refresh, isRefreshing } =
    useConnections(username);
  const { create, busy, pending } = useCreateSharedConnection(username);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  // Failed entries the user has hidden (FR-005 Dismiss) and ones being retried
  // (shown optimistically as provisioning). Both are local-only; a Refresh
  // reconciles against the authoritative cache.
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
      }));
    const cacheNames = new Set(fromCache.map((r) => r.name));
    // Local pending entries not yet reflected in the cache (cache wins on dupes).
    const fromPending: ConnectionRow[] = pending
      .filter((p) => !cacheNames.has(p.name))
      .map((p) => ({ name: p.name, role: p.role, status: p.status }));
    return [...fromCache, ...fromPending]
      .filter((r) => !dismissed.has(r.name))
      .map((r) =>
        retrying.has(r.name) ? { ...r, status: 'provisioning' as const } : r,
      )
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [connections, pending, dismissed, retrying]);

  const handleRefresh = () => {
    // The cache is authoritative after a refresh — drop local-only overrides so
    // a still-failed entry reappears and a now-active retry reflects reality.
    setDismissed(new Set());
    setRetrying(new Set());
    void refresh();
  };

  const handleCreate = async (name: string) => {
    setDialogOpen(false);
    const result = await create(name);
    if (result.success) {
      setToast({ variant: 'success', message: `Creating “${name}”…` });
    } else {
      setToast({ variant: 'danger', message: result.error.message });
    }
  };

  const handleDismiss = (name: string) => {
    setDismissed((prev) => new Set(prev).add(name));
  };

  const handleRetry = async (name: string) => {
    setRetrying((prev) => new Set(prev).add(name));
    const result = await create(name);
    if (result.success) {
      setToast({ variant: 'success', message: `Retrying “${name}”…` });
    } else {
      setRetrying((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
      setToast({ variant: 'danger', message: result.error.message });
    }
  };

  return (
    <div className="flex-1 overflow-auto px-6 py-6">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-text">Connections</h1>
            <p className="mt-1 text-sm text-text-2">
              Shared spaces you own or belong to. Everyone with access sees the
              same files and tables.
            </p>
          </div>
          <div className="flex flex-none items-center gap-2">
            <RefreshConnectionsButton
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
            />
            <Button variant="primary" onClick={() => setDialogOpen(true)}>
              New shared connection
            </Button>
          </div>
        </div>

        {error && (
          <Banner variant="danger" className="mb-4">
            Couldn&apos;t load your shared connections: {error}
          </Banner>
        )}

        {isLoading ? (
          <p role="status" className="px-1 py-10 text-center text-sm text-text-3">
            Loading your connections…
          </p>
        ) : rows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-surface-2 px-5 py-10 text-center text-sm text-text-2">
            No shared connections yet — create one or ask an owner to add you.
          </div>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {rows.map((row) => (
              <ConnectionRowItem
                key={row.name}
                row={row}
                onDismiss={() => handleDismiss(row.name)}
                onRetry={() => void handleRetry(row.name)}
              />
            ))}
          </ul>
        )}
      </div>

      {dialogOpen && (
        <CreateSharedConnectionDialog
          busy={busy}
          onCreate={handleCreate}
          onCancel={() => setDialogOpen(false)}
        />
      )}
      {toast && <Toast {...toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}

function ConnectionRowItem({
  row,
  onDismiss,
  onRetry,
}: {
  row: ConnectionRow;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 truncate font-mono text-sm font-medium text-text">
          {row.name}
        </span>
        <div className="flex flex-none items-center gap-2">
          <RolePill role={row.role} />
          <StatusBadge status={row.status} />
        </div>
      </div>
      {row.status === 'failed' && (
        <div className="flex items-center justify-between gap-3 rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
          <span className="min-w-0 flex-1">
            {row.reason ?? 'Provisioning failed.'}
          </span>
          <div className="flex flex-none items-center gap-2">
            <button
              type="button"
              onClick={onRetry}
              className="font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={onDismiss}
              className="font-medium opacity-80 hover:underline hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function RolePill({ role }: { role: SharedConnectionRole }) {
  return (
    <span className="flex-none rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs font-medium capitalize text-text-2">
      {role}
    </span>
  );
}

// Status as text + icon (never color-only, a11y). A spinner for the transient
// states, a check for active, an alert mark for failed.
function StatusBadge({ status }: { status: SharedConnectionStatus }) {
  const transient = status === 'provisioning' || status === 'leaving';
  const tone =
    status === 'active'
      ? 'border-success-soft bg-success-soft text-success'
      : status === 'failed'
        ? 'border-danger-soft bg-danger-soft text-danger'
        : 'border-border bg-surface text-text-2';
  return (
    <span
      className={`flex-none inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className={`h-3 w-3 ${transient ? 'animate-spin' : ''}`}
      >
        {transient ? (
          <>
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 3v6h-6" />
          </>
        ) : status === 'active' ? (
          <path d="M20 6 9 17l-5-5" />
        ) : (
          <>
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v4M12 16h.01" />
          </>
        )}
      </svg>
      {connectionStatusLabel(status)}
    </span>
  );
}
