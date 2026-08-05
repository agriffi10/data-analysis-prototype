import {describe, it, expect, vi, afterEach} from 'vitest';
import {enqueueFifoRequest} from './enqueueFifo';
import {toUserMessage} from './errorMessages';
import {enqueueQualityCheck} from '../features/data-quality/dataQuality.service';
import {enqueueNotificationAction} from '../features/notifications/notifications.service';
import {enqueueSharedSpaceRequest} from '../features/shared-spaces/sharedSpaces.service';
import {enqueueTableBuild, enqueueTableRefresh} from '../features/table-builder/tableBuild.service';
import {enqueueTableShare} from '../features/table-share/tableShare.service';
import type {ServiceResult} from '../types/service.types';

// SPEC-150 FR-004. The queue-URL guard returns before `getIdToken` and before any
// SQS call, so nothing here needs the AWS boundary mocked — an unset env var is
// the whole precondition.

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('enqueueFifoRequest — the missing-queue-URL guard', () => {
  it('codes the failure NotConfigured so the authored wording can be mapped', async () => {
    const result = await enqueueFifoRequest({
      queueUrl: undefined,
      notConfiguredMessage: 'Table refresh is not configured',
      build: () => {
        throw new Error('build must not run when the queue URL is missing');
      }
    });

    expect(result).toEqual({
      success: false,
      error: {message: 'Table refresh is not configured', code: 'NotConfigured'}
    });
  });

  it('surfaces that wording to the user instead of the generic fallback', () => {
    // The regression this closes: with no `code`, `toUserMessage` fell through every
    // MATCH_RULES pattern to GENERIC, and the documented deploy gotcha presented as
    // "Something went wrong."
    const {message} = toUserMessage({code: 'NotConfigured', message: 'Table refresh is not configured'});

    expect(message).toBe('Table refresh is not configured');
    expect(message).not.toContain('Something went wrong');
  });
});

// Every `notConfiguredMessage` in the app, with the env var whose absence produces
// it. A seventh control plane added without a row here is a message a user cannot
// see — which is the defect this FR fixes, not a new one.
const CALL_SITES: {name: string; envVar: string; message: string; call: () => Promise<ServiceResult<unknown>>}[] = [
  {
    name: 'sharedSpaces.service — enqueueSharedSpaceRequest',
    envVar: 'VITE_SHARED_SPACE_QUEUE_URL',
    message: 'Shared connections are not configured',
    call: () => enqueueSharedSpaceRequest({action: 'create', actor: 'alice', space: 'project_alpha'})
  },
  {
    name: 'dataQuality.service — enqueueQualityCheck',
    envVar: 'VITE_DATA_QUALITY_QUEUE_URL',
    message: 'Data quality checks are not configured',
    call: () =>
      enqueueQualityCheck({
        requestId: 'req-1',
        space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/'},
        location: 'alice/sales/'
      })
  },
  {
    name: 'tableShare.service — enqueueTableShare',
    envVar: 'VITE_TABLE_SHARE_QUEUE_URL',
    message: 'Table sharing is not configured',
    call: () =>
      enqueueTableShare({
        source: {database: 'alice', table: 'sales'},
        tableName: 'sales',
        recipients: [{kind: 'user', name: 'bob'}]
      })
  },
  {
    name: 'notifications.service — enqueueNotificationAction',
    envVar: 'VITE_NOTIFICATIONS_QUEUE_URL',
    message: 'Notifications are not configured',
    call: () => enqueueNotificationAction({action: 'markAllRead', username: 'alice'})
  },
  {
    name: 'tableBuild.service — enqueueTableBuild',
    envVar: 'VITE_TABLE_BUILD_QUEUE_URL',
    message: 'Table creation is not configured',
    call: () =>
      enqueueTableBuild({
        space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/sales/', database: 'alice'},
        tableName: 'sales',
        partitionKeys: []
      })
  },
  {
    name: 'tableBuild.service — enqueueTableRefresh',
    envVar: 'VITE_TABLE_BUILD_QUEUE_URL',
    message: 'Table refresh is not configured',
    call: () =>
      enqueueTableRefresh({
        space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/sales/', database: 'alice'},
        tableName: 'sales'
      })
  }
];

describe('every "not configured" message reaches the user', () => {
  it.each(CALL_SITES)('$name', async ({envVar, message, call}) => {
    vi.stubEnv(envVar, undefined);

    const result = await call();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('NotConfigured');
    // The assertion that matters is the MAPPED text, not the raw one: the raw
    // message was always correct, and was always thrown away by the mapper.
    expect(toUserMessage(result.error).message).toBe(message);
  });
});
