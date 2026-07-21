import {describe, it, expect, vi, beforeEach} from 'vitest';
import {getRunsIndex, runsIndexKey} from './dataQualityRuns.service';
import {getS3Client} from '../../lib/s3Client';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const send = vi.fn();

/** `getS3Client` hands back a ServiceResult, not a bare client (the sibling service test). */
const awsError = (name: string, status?: number) =>
  Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

const body = (value: unknown) => ({
  Body: {transformToString: async () => (typeof value === 'string' ? value : JSON.stringify(value))}
});

const entry = (over = {}) => ({
  requestId: 'r-1',
  location: 'alice/sales/',
  format: 'csv',
  verdict: 'issues_found',
  fileCount: 3,
  hasApproximateFigures: false,
  timestamp: '2026-07-20T10:00:00Z',
  ...over
});

beforeEach(() => {
  vi.clearAllMocks();
  send.mockReset();
  vi.mocked(getS3Client).mockResolvedValue({success: true, data: {send} as never});
});

describe('runsIndexKey', () => {
  it('matches the key the Lambda writes', () => {
    // dqcommon/index_store.py::index_key — the two must agree or the page reads nothing.
    expect(runsIndexKey('alice')).toBe('alice/_data-quality-reports/index.json');
  });
});

describe('getRunsIndex', () => {
  it('stamps the space onto every entry', async () => {
    // The entry on S3 does not carry its own space; this is the only place that knows it,
    // and the row's link is built from it.
    send.mockResolvedValue(body({entries: [entry(), entry({requestId: 'r-2'})]}));

    const result = await getRunsIndex('user-space', 'alice');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.map((r) => r.space)).toEqual(['alice', 'alice']);
  });

  it('treats a missing index as an empty success, not an error', async () => {
    // Every space is in this state until its first check completes; a red banner would be
    // the wrong answer to "you have not run one yet".
    send.mockRejectedValue(awsError('NoSuchKey', 404));

    const result = await getRunsIndex('user-space', 'alice');

    expect(result).toEqual({success: true, data: []});
  });

  it('treats a corrupt index as empty rather than failing the page', async () => {
    send.mockResolvedValue(body('{ not json'));
    await expect(getRunsIndex('user-space', 'alice')).resolves.toEqual({success: true, data: []});
  });

  it('treats a structurally wrong index as empty', async () => {
    send.mockResolvedValue(body({entries: 'not-a-list'}));
    await expect(getRunsIndex('user-space', 'alice')).resolves.toEqual({success: true, data: []});
  });

  it('drops a malformed entry without losing the good ones', async () => {
    // An index is an append-only log written by many runs over time, so one bad row must
    // cost that row and not the user's whole history.
    send.mockResolvedValue(
      body({entries: [entry(), {requestId: 'broken'}, entry({requestId: 'r-3', verdict: 'nonsense'})]})
    );

    const result = await getRunsIndex('user-space', 'alice');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.map((r) => r.requestId)).toEqual(['r-1']);
  });

  it('surfaces a real access failure as a typed error', async () => {
    send.mockRejectedValue(awsError('AccessDenied', 403));

    const result = await getRunsIndex('shared-space', 'team-data');

    expect(result.success).toBe(false);
  });
});
