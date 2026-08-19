import {useCallback, useEffect, useRef, useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {invalidateSchema} from '../catalog/useSchema';
import {toUserText} from '../../lib/errorMessages';
import {enqueueTableRefresh} from './tableBuild.service';
import {parseTableLocation} from './tableRefresh.location';
import type {GlueTableSummary} from '../catalog/catalog.types';
import type {PendingRemoval, TableRefreshTarget} from './tableRefresh.types';

type RefreshToast = {variant: 'success' | 'danger'; message: string};

/**
 * A target the caller derived from the URL (`columns_removed` link) plus
 * the way to retire it. The link-borne dialog is a function of the query string
 * rather than of state set in an effect — React Compiler's `set-state-in-effect`
 * rule forbids the latter, and the derived form is the shape the rulebook asks for
 * anyway (react.md §3: derive, don't store).
 */
type LinkedTarget = {
  target: TableRefreshTarget | null;
  /** Strips the parameters, which is what closes the link-borne dialog. */
  onConsumed: () => void;
};

/**
 * Dialog + enqueue state for "Refresh table", shaped like
 * {@link useTableShare} so the two dialogs in the same menu are wired alike:
 * `open` targets a rail table, `submit(allowRemovals)` enqueues, and on success the
 * dialog closes with a transient toast (the outcome is a notification).
 * A failure keeps the dialog open with `error` set.
 *
 * `linked` is the optional second entry point: a target the caller derived from
 * the notification link. It is passed in rather than opened, because opening
 * it would mean setting state in an effect. An explicitly opened target always wins.
 *
 * It also owns the schema invalidation, because the successful enqueue is the
 * only signal there is: the rail is invalidated once on submit and once more the
 * next time the window regains focus — the refresh is asynchronous, so the columns
 * usually land while the user is elsewhere. The second pass is armed by a submit
 * and disarmed by firing, so idle focus events never invalidate.
 */
export function useTableRefresh(notify: (toast: RefreshToast) => void, linked?: LinkedTarget) {
  const {user} = useAuth();
  const username = user?.username ?? '';
  const queryClient = useQueryClient();
  const [opened, setOpened] = useState<TableRefreshTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The database and table owed a post-focus re-read, or null when nothing is armed.
  const refetchOnFocus = useRef<{database: string; table: string} | null>(null);
  // A ref, not `busy`: see useDataQualityCheck for why the state read loses the race.
  // It matters more here — concurrent refreshes on one table can race,
  // and `deduplicationId` is a fresh UUID per call, so SQS cannot collapse the pair.
  const inFlight = useRef(false);

  useEffect(() => {
    const onFocus = () => {
      const armed = refetchOnFocus.current;
      if (!armed) return;
      refetchOnFocus.current = null;
      void invalidateSchema(queryClient, armed.database, armed.table);
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [queryClient]);

  // A menu-opened target wins over a link-borne one: the user acted more recently.
  const linkTarget = linked?.target ?? null;
  const consumeLink = linked?.onConsumed;
  const target = opened ?? linkTarget;

  const open = useCallback((database: string, table: GlueTableSummary, pending?: PendingRemoval) => {
    setError(null);
    setOpened({database, table, pending: pending ?? null});
  }, []);

  const close = useCallback(() => {
    if (busy) return;
    setOpened(null);
    setError(null);
    // The link-borne dialog IS the query string, so dismissing it means retiring the
    // parameters — which also stops a reload from reopening what the user just closed.
    // Guarded on there being a live link: a menu-opened dialog closing over an
    // unresolvable link's parameters would be destroying state that isn't its own.
    if (linkTarget) consumeLink?.();
  }, [busy, consumeLink, linkTarget]);

  const submit = useCallback(
    async (allowRemovals: boolean) => {
      if (!target || inFlight.current) return;
      inFlight.current = true;
      try {
        const location = parseTableLocation(target.table.location);
        if (!location) {
          // The menu item is disabled without a location, so this is unreachable from
          // the UI — but the request cannot be built, and a silent no-op would look
          // like a refresh that never reported back.
          setError('This table has no data folder, so it can’t be refreshed.');
          return;
        }
        setBusy(true);
        setError(null);
        const result = await enqueueTableRefresh({
          space: {
            // The personal database IS the username, which is exactly what
            // the rail's `Connection.kind` encodes and what the control plane
            // re-checks against the verified actor.
            kind: target.database === username ? 'personal' : 'shared',
            bucket: location.bucket,
            prefix: location.prefix,
            database: target.database
          },
          tableName: target.table.name,
          ...(allowRemovals ? {allowRemovals: true} : {})
        });
        setBusy(false);
        if (!result.success) {
          setError(toUserText(result.error));
          return;
        }
        const {database, table} = target;
        setOpened(null);
        consumeLink?.();
        void invalidateSchema(queryClient, database, table.name);
        refetchOnFocus.current = {database, table: table.name};
        notify({
          variant: 'success',
          message: `Refreshing “${database}.${table.name}” — the result will appear in your notifications.`
        });
      } finally {
        // Every exit — success, enqueue failure, the no-location early return and a
        // throw — clears the guard, so one dropped click never wedges the dialog.
        inFlight.current = false;
      }
    },
    [consumeLink, notify, queryClient, target, username]
  );

  return {target, busy, error, open, close, submit};
}
