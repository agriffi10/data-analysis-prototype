import { useState } from 'react';
import { Button } from '../components/Button';
import { useAuth } from '../features/auth';
import {
  CreateSharedConnectionDialog,
  useCreateSharedConnection,
} from '../features/shared-spaces';
import { Toast, type ToastState } from '../features/query/Toast';
import { usePageTitle } from '../hooks/usePageTitle';

// The Connections tab (`/connections`) — SPEC-051 ships a MINIMAL shell: create a
// shared connection + show its optimistic provisioning state. SPEC-052 enriches
// this with the full personal+shared list, Refresh-connections, member management
// entry points, and the schema/Files selector integration. Chrome (Header + primary
// tabs) and the auth gate live in ProtectedLayout/Header.
export default function ConnectionsPage() {
  usePageTitle('Connections');
  const { user } = useAuth();
  const username = user?.username ?? null;

  const { create, busy, pending } = useCreateSharedConnection(username);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const handleCreate = async (name: string) => {
    setDialogOpen(false);
    const result = await create(name);
    if (result.success) {
      setToast({ variant: 'success', message: `Creating “${name}”…` });
    } else {
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
          <Button variant="primary" onClick={() => setDialogOpen(true)}>
            New shared connection
          </Button>
        </div>

        {pending.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-surface-2 px-5 py-10 text-center text-sm text-text-2">
            No shared connections yet. Create one to collaborate with other users.
          </div>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {pending.map((entry) => (
              <li
                key={entry.name}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                <span className="truncate font-medium text-text">
                  {entry.name}
                </span>
                <span className="flex-none rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs text-text-2">
                  Provisioning…
                </span>
              </li>
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
