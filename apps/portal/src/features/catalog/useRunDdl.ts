import {useCallback, useEffect, useRef, useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {isAbandoned, runStatementToCompletion} from './athena.service';
import {invalidateSchema} from './useSchema';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import type {ToastApi} from '../../components/toastContext';
import type {QueryState} from './catalog.types';

export type RunDdlArgs = {
  sql: string;
  /** The schema invalidated on success, and the history entry's recorded context. */
  database: string;
  /**
   * The one catalog object this statement changes — the table dropped, the view created.
   * Passed on so a consumer that caches per table can evict that one rather than all of them:
   * creating a view beside an exploration must not re-run it, and a bill is what the
   * difference costs. Omit only for a statement whose target is genuinely unknown.
   */
  table?: string;
  /** The two toast wordings, in the user's terms. */
  describe: {
    /** Shown verbatim on success — e.g. `Saved view sales_2024`. */
    success: string;
    /** The lead sentence a failure prefixes to the mapped reason — e.g. `Couldn’t drop sales.` */
    failure: string;
  };
  /** Closes the dialog that raised this statement. Not called on abandonment. */
  onSettled: () => void;
};

export type UseRunDdlResult = {
  /** True while a statement is in flight; drives the raising dialog's busy state. */
  busy: boolean;
  run: (args: RunDdlArgs) => void;
};

/**
 * Records the statement in whatever history the caller keeps. Typed structurally rather than
 * imported from `features/query/`: this module moved DOWN into the shared layer so the Data
 * Explorer could create a view, and a shared module naming a leaf feature's type would be the
 * undeclared shared layer the layering rule exists to prevent, one import deep. The return
 * value is unused here — a history write is best-effort and its result belongs to its owner.
 */
export type RecordedStatement = {
  queryExecutionId: string;
  sql: string;
  database: string;
  /** ISO timestamp. */
  submittedAt: string;
  status?: QueryState;
  dataScannedBytes?: number;
  durationMs?: number;
};

export type RecordStatement = (entry: RecordedStatement) => Promise<unknown>;

type Params = {
  username: string;
  appendEntry: RecordStatement;
  toast: ToastApi;
};

/**
 * Runs one background DDL statement to completion and reports it — the single
 * path behind Create view and Drop table, which were the
 * same forty lines written twice.
 *
 * It lives in `features/catalog/` rather than in the Query workspace because the Data
 * Explorer creates views too, and a leaf feature importing another leaf is how a feature
 * quietly becomes a shared layer nobody declared. Nothing about the behaviour changed in the
 * move; only `appendEntry`'s type, which is now structural.
 *
 * "Background" means the editor keeps showing the user's own SQL while the
 * statement runs; the outcome arrives as a toast. Every run is recorded in
 * history, and a success invalidates the target database's schema so the rail
 * catches up.
 *
 * The two dialogs are mutually exclusive in the UI, so they share one `busy`
 * flag rather than the two they carried separately.
 */
export function useRunDdl({username, appendEntry, toast}: Params): UseRunDdlResult {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  // These statements poll Athena for up to ~36 s. Leaving the
  // workspace abandons that poller — the statement itself carries on server-side;
  // what stops is us waiting for it.
  //
  // The controller is CREATED IN THE EFFECT, not in a ref initializer. StrictMode runs
  // mount → cleanup → mount in dev, so a controller made once and aborted in the
  // cleanup would leave the ref holding an already-aborted signal for the component's
  // whole life — every Create view and Drop table would submit, then immediately report
  // failure. Measured; not hypothetical.
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    return () => controller.abort();
  }, []);

  const run = useCallback(
    ({sql, database, table, describe, onSettled}: RunDdlArgs) => {
      setBusy(true);
      void (async () => {
        const result = await runStatementToCompletion({sql, database, username, signal: abortRef.current?.signal});
        // We stopped waiting because the user left. The statement is still running, and
        // `ToastProvider` sits above the router — so a toast here would surface on
        // whatever page they went to, about something that did not fail.
        if (isAbandoned(result)) return;
        setBusy(false);
        onSettled();
        if (!result.success) {
          // A statement we stopped waiting for has not failed: it carries on in Athena and usually
          // lands, so "Couldn't … try again" would send the user into a retried DROP that is then
          // refused as not found.
          const message =
            result.error.code === 'Timeout'
              ? `Data Quarry stopped waiting on “${table}”, but Athena may still finish the change. Refresh the tables in a minute to see whether it did.`
              : `${describe.failure} ${toUserText(result.error)}`;
          toast.push({variant: 'danger', message});
          return;
        }
        const status = result.data;
        // Record the run in history — a CREATE VIEW / DROP is a real statement.
        appendEntry({
          queryExecutionId: status.queryExecutionId,
          sql,
          database,
          submittedAt: new Date().toISOString(),
          status: status.state,
          dataScannedBytes: status.dataScannedBytes,
          durationMs: status.engineExecutionTimeMillis
        }).catch((e) => logBackgroundFailure('query-history', e));

        if (status.state === 'SUCCEEDED') {
          void invalidateSchema(queryClient, database, table);
          toast.push({variant: 'success', message: describe.success});
        } else {
          toast.push({
            variant: 'danger',
            message: `${describe.failure} ${toUserText({code: status.state, message: status.stateChangeReason})}`
          });
        }
      })();
    },
    [username, appendEntry, toast, queryClient]
  );

  return {busy, run};
}
