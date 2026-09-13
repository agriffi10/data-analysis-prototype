import {useEffect, useRef} from 'react';
import {isTerminalState} from '../catalog/athena.service';
import {useQueryExecution} from '../catalog/useQueryExecution';
import type {QueryStatus} from '../catalog/catalog.types';

/**
 * a headless poller, one per tab holding an execution. Each runs
 * its own useQueryExecution so a backgrounded query keeps polling to terminal
 * (its status/history finalize without waiting for the user to return). Reports
 * status up, and settles each execution id exactly once: with its terminal status
 * through `onFinalize`, or with the error through `onPollFailure` when its status
 * cannot be read. A failed poll is final — the poll is disabled rather than left to
 * answer later, when the tab has already moved on.
 *
 * @example
 * <TabExecutionPoller tabId={tab.id} executionId={run.executionId} submittedSql={run.sql} onStatus={setStatus} onFinalize={finalize} onPollFailure={settleOnFailure} />
 */
export function TabExecutionPoller({
  tabId,
  executionId,
  submittedSql,
  onStatus,
  onFinalize,
  onPollFailure
}: {
  tabId: string;
  executionId: string;
  submittedSql: string;
  onStatus: (tabId: string, status: QueryStatus | undefined) => void;
  onFinalize: (tabId: string, executionId: string, status: QueryStatus, sql: string) => void;
  /** The execution's status could not be read, after the hook's own retry. */
  onPollFailure: (tabId: string, executionId: string, error: unknown) => void;
}) {
  const execution = useQueryExecution(executionId, {stopOnError: true});
  const status = execution.data;
  const pollError = execution.error;
  const settledRef = useRef<string | null>(null);

  useEffect(() => {
    onStatus(tabId, status);
  }, [tabId, status, onStatus]);

  useEffect(() => {
    if (!status || !isTerminalState(status.state)) return;
    if (settledRef.current === executionId) return;
    settledRef.current = executionId;
    onFinalize(tabId, executionId, status, submittedSql);
  }, [tabId, status, executionId, submittedSql, onFinalize]);

  useEffect(() => {
    if (!pollError) return;
    if (settledRef.current === executionId) return;
    settledRef.current = executionId;
    onPollFailure(tabId, executionId, pollError);
  }, [tabId, pollError, executionId, onPollFailure]);

  return null;
}
