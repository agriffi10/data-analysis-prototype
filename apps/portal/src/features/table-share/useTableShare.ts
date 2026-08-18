import {useRef, useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {enqueueTableShare} from './tableShare.service';
import type {ShareRecipient} from './tableShare.types';

/** The rail table a share was invoked on (the DB comes from the rail node). */
export type ShareTarget = {database: string; table: string};

type ShareToast = {variant: 'success' | 'danger'; message: string};

/**
 * Dialog + enqueue state for "Share table". `open(database, table)`
 * targets a rail table; `submit` enqueues via `enqueueTableShare` — on success the
 * dialog closes and `notify` gets the transient "Sharing…" toast (outcomes arrive
 * as notifications); on failure the dialog stays open with `error` set
 * and the entered values intact (FR-003).
 */
export function useTableShare(notify: (toast: ShareToast) => void) {
  const [target, setTarget] = useState<ShareTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A ref, not `busy`: see useDataQualityCheck for why the state read loses the race.
  const inFlight = useRef(false);

  const open = (database: string, table: string) => {
    setError(null);
    setTarget({database, table});
  };

  const close = () => {
    if (busy) return;
    setTarget(null);
    setError(null);
  };

  const submit = async ({tableName, recipients}: {tableName: string; recipients: ShareRecipient[]}) => {
    if (!target || inFlight.current) return;
    inFlight.current = true;
    try {
      setBusy(true);
      setError(null);
      const result = await enqueueTableShare({
        source: {database: target.database, table: target.table},
        tableName,
        recipients
      });
      setBusy(false);
      if (!result.success) {
        setError(toUserText(result.error));
        return;
      }
      setTarget(null);
      notify({
        variant: 'success',
        message: `Sharing “${target.database}.${target.table}” — recipients are notified, and the outcome will appear in your notifications.`
      });
    } finally {
      // Cleared on every exit — success, failure and a throw — so one dropped click
      // never wedges the dialog.
      inFlight.current = false;
    }
  };

  return {target, busy, error, open, close, submit};
}
