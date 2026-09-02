import {useEffect, useRef} from 'react';
import {isTerminalState} from '../catalog/athena.service';
import {useQueryExecution} from '../catalog/useQueryExecution';
import type {QueryStatus} from '../catalog/catalog.types';

/**
 * a headless poller, one per tab holding an execution. Each runs
 * its own useQueryExecution so a backgrounded query keeps polling to terminal
 * (its status/history finalize without waiting for the user to return). Reports
 * status up and finalizes history exactly once per execution id.
 *
 * @example
 * <TabExecutionPoller tabId={tab.id} executionId={run.executionId} submittedSql={run.sql} onStatus={setStatus} onFinalize={finalize} />
 */
export function TabExecutionPoller({
  tabId,
  executionId,
  submittedSql,
  onStatus,
  onFinalize
}: {
  tabId: string;
  executionId: string;
  submittedSql: string;
  onStatus: (tabId: string, status: QueryStatus | undefined) => void;
  onFinalize: (tabId: string, executionId: string, status: QueryStatus, sql: string) => void;
}) {
  const execution = useQueryExecution(executionId);
  const status = execution.data;
  const finalizedRef = useRef<string | null>(null);

  useEffect(() => {
    onStatus(tabId, status);
  }, [tabId, status, onStatus]);

  useEffect(() => {
    if (!status || !isTerminalState(status.state)) return;
    if (finalizedRef.current === executionId) return;
    finalizedRef.current = executionId;
    onFinalize(tabId, executionId, status, submittedSql);
  }, [tabId, status, executionId, submittedSql, onFinalize]);

  return null;
}
