import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {asSentence, formatRatio, isApproximateIssue, locationLabel, sourceFolderPrefix} from './dataQuality.format';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueQualityCheck} from './dataQuality.service';
import {getQualityReport, reportKey} from './dataQualityReport.service';
import {getS3Client} from '../../lib/s3Client';
import {csvReport} from './reportFixtures';
import {getRunsIndex, runsIndexKey} from './dataQualityRuns.service';
import type {DataQualityRequest} from './dataQuality.types';

// ─── from dataQuality.format.test.ts ───
vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getIdToken: vi.fn(),
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));
vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

describe('dataQuality.format', () => {
  describe('locationLabel', () => {
    it('names a folder by its own segment and a file by its basename', () => {
      expect(locationLabel('alice/data/sales/')).toBe('sales');
      expect(locationLabel('alice/data/sales.csv')).toBe('sales.csv');
      expect(locationLabel('sales.csv')).toBe('sales.csv');
    });

    it('never returns a blank label', () => {
      // A space root, or a degenerate key — the caller puts this in a sentence.
      expect(locationLabel('/')).toBe('/');
      expect(locationLabel('')).toBe('');
    });
  });

  describe('sourceFolderPrefix', () => {
    it('reduces a file key to its parent folder and leaves a folder alone', () => {
      // `/files?prefix=` seeds the browser's CURRENT FOLDER, so a file key passed
      // through would ask it to open a folder that does not exist.
      expect(sourceFolderPrefix('alice/data/sales.csv')).toBe('alice/data/');
      // A folder is already the answer — it is returned untouched, not climbed.
      expect(sourceFolderPrefix('alice/data/sales/')).toBe('alice/data/sales/');
      expect(sourceFolderPrefix('top.csv')).toBe('');
    });
  });

  describe('formatRatio', () => {
    it('distinguishes no blanks from a ratio that merely rounds to none', () => {
      // A handful of blanks in a million rows is not the same as none, and "0.0%"
      // would claim it is.
      expect(formatRatio(0)).toBe('0%');
      expect(formatRatio(0.0000008)).toBe('<0.1%');
      expect(formatRatio(0.0432)).toBe('4.3%');
      expect(formatRatio(0.61)).toBe('61.0%');
    });
  });

  describe('asSentence', () => {
    it('makes a lower-case Lambda fragment read as a standalone sentence', () => {
      // dqcommon writes reasons as fragments that complete "Couldn't check data quality:
      // {reason}". This view shows them alone after a bold lead, where the raw fragment
      // reads as a typo — "Not applicable. not a line-delimited text format."
      expect(asSentence('not a line-delimited text format.')).toBe('Not a line-delimited text format.');
      expect(asSentence('binary format — encoding is defined by the file format')).toBe(
        'Binary format — encoding is defined by the file format.'
      );
    });

    it('leaves an already-well-formed reason alone', () => {
      const parquet = 'Parquet enforces types in the file format, so this check cannot find anything.';
      expect(asSentence(parquet)).toBe(parquet);
    });

    it('returns empty for empty input rather than a bare full stop', () => {
      expect(asSentence('')).toBe('');
      expect(asSentence('   ')).toBe('');
    });
  });

  describe('isApproximateIssue', () => {
    // THE WORDINGS BELOW ARE COPIED FROM `dqcommon/report.py::top_issues`, which authors
    // every top-issue line. The classifier reads those strings, so if that module's
    // wording drifts an approximate finding would be labelled `Exact` — a claim the data
    // does not support. These four cases are its four generators; this test is what makes
    // that drift loud instead of silent.
    it('flags the two approximate generators — ragged rows and encoding', () => {
      expect(isApproximateIssue('37 rows have the wrong number of fields (approximate)')).toBe(true);
      expect(
        isApproximateIssue(
          '4 invalid text encodings found, in the part examined — this data may have been exported in the wrong character set'
        )
      ).toBe(true);
      // Encoding is approximate even when the scan was complete (no ", in the part
      // examined" clause) — the whole check lives in the report's `approximate` block.
      expect(
        isApproximateIssue(
          '4 invalid text encodings found — this data may have been exported in the wrong character set'
        )
      ).toBe(true);
    });

    it('leaves the two exact generators — cross-file disagreements and column types', () => {
      expect(isApproximateIssue('mar.csv is missing the column `region` that the other 2 files have')).toBe(false);
      expect(isApproximateIssue('`amount` has 412 values that aren’t numbers in an otherwise numeric column')).toBe(
        false
      );
      expect(isApproximateIssue('12 duplicate rows')).toBe(false);
    });
  });
});

// ─── from dataQuality.service.test.ts ───

describe('dataQuality.service', () => {
  const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
  const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

  const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-data-quality-requests.fifo';
  const REQUEST_ID = '11111111-2222-4333-8444-555555555555';

  type Cmd = {input: Record<string, unknown>};

  function fakeQueue(rejectWith?: unknown) {
    const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
    if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
    else send.mockResolvedValue({MessageId: 'm1'});
    mockGetSqs.mockResolvedValue({success: true, data: {send}});
    return {send};
  }

  function makeReq(over: Partial<DataQualityRequest> = {}): DataQualityRequest {
    return {
      requestId: REQUEST_ID,
      space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
      location: 'alice/sales/',
      ...over
    };
  }

  beforeEach(() => {
    vi.stubEnv('VITE_DATA_QUALITY_QUEUE_URL', QUEUE);
    mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
  });

  describe('enqueueQualityCheck', () => {
    it('sends the envelope with the token and no username', async () => {
      const {send} = fakeQueue();
      const res = await enqueueQualityCheck(makeReq());

      expect(res).toEqual({success: true, data: {requestId: REQUEST_ID}});
      const input = send.mock.calls[0][0].input;
      expect(input.QueueUrl).toBe(QUEUE);
      const body = JSON.parse(input.MessageBody as string);
      expect(body).toEqual({
        requestId: REQUEST_ID,
        idToken: 'id-token-abc',
        space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
        location: 'alice/sales/'
      });
      // The actor is derived server-side from the verified claim — the body must not
      // carry an identity the caller could assert.
      expect(body).not.toHaveProperty('actor');
      expect(body).not.toHaveProperty('username');
    });

    it('uses the requestId as the deduplication id', async () => {
      const {send} = fakeQueue();
      await enqueueQualityCheck(makeReq());
      expect(send.mock.calls[0][0].input.MessageDeduplicationId).toBe(REQUEST_ID);
    });

    it('hashes a location far longer than SQS allows into a 64-char group id', async () => {
      // The failure this prevents: SQS caps MessageGroupId at 128 chars while S3 keys reach
      // 1024, so a RAW location group id would fail the send in the browser — for exactly
      // the users with the deepest folders.
      const deep = `alice/${'nested-folder/'.repeat(20)}data/`;
      expect(deep.length).toBeGreaterThan(128);

      const {send} = fakeQueue();
      const res = await enqueueQualityCheck(makeReq({location: deep}));

      expect(res.success).toBe(true);
      const groupId = send.mock.calls[0][0].input.MessageGroupId as string;
      expect(groupId).toHaveLength(64);
      expect(groupId).toMatch(/^[0-9a-f]{64}$/);
      expect(groupId).not.toContain('nested-folder');
    });

    it('gives the same group id to the same location (they serialize)', async () => {
      const {send} = fakeQueue();
      await enqueueQualityCheck(makeReq({requestId: 'req-a'}));
      await enqueueQualityCheck(makeReq({requestId: 'req-b'}));

      const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
      expect(a).toBe(b);
    });

    it('gives different group ids to different locations (they run in parallel)', async () => {
      const {send} = fakeQueue();
      await enqueueQualityCheck(makeReq({location: 'alice/sales/'}));
      await enqueueQualityCheck(makeReq({location: 'alice/marketing/'}));

      const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
      expect(a).not.toBe(b);
    });

    it('treats trailing-slash variants of one location as the same group', async () => {
      const {send} = fakeQueue();
      await enqueueQualityCheck(makeReq({location: 'alice/sales/'}));
      await enqueueQualityCheck(makeReq({location: 'alice/sales'}));

      const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
      expect(a).toBe(b);
    });

    it('returns a failure when the queue is not configured', async () => {
      vi.stubEnv('VITE_DATA_QUALITY_QUEUE_URL', '');
      const res = await enqueueQualityCheck(makeReq());
      expect(res.success).toBe(false);
    });

    it('propagates a credential failure without sending', async () => {
      mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no session'}});
      const {send} = fakeQueue();
      const res = await enqueueQualityCheck(makeReq());
      expect(res.success).toBe(false);
      expect(send).not.toHaveBeenCalled();
    });

    it('never throws when the send fails', async () => {
      fakeQueue(Object.assign(new Error('SQS down'), {name: 'ServiceUnavailable'}));
      const res = await enqueueQualityCheck(makeReq());
      expect(res.success).toBe(false);
      if (!res.success) expect(res.error.code).toBe('ServiceUnavailable');
    });
  });
});

// ─── from dataQualityReport.service.test.ts ───

describe('dataQualityReport.service', () => {
  const send = vi.fn();
  const mockGetS3Client = vi.mocked(getS3Client);

  /** An S3 GetObject response body, as the SDK hands it to the service. */
  const body = (text: string) => ({Body: {transformToString: async () => text}});

  const awsError = (name: string, status?: number) =>
    Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

  beforeEach(() => {
    vi.clearAllMocks();
    send.mockReset();
    mockGetS3Client.mockResolvedValue({success: true, data: {send} as never});
  });

  describe('reportKey', () => {
    it('builds the key assemble-report writes, for personal and shared spaces alike', () => {
      // Mirrors dq_assemble_report.report_key — a pure function of the request id.
      expect(reportKey('alice', 'req-1')).toBe('alice/_data-quality-reports/req-1/report.json');
      expect(reportKey('team-data', 'req-1')).toBe('team-data/_data-quality-reports/req-1/report.json');
    });
  });

  describe('getQualityReport', () => {
    it('reads and returns the report from the space it was given', async () => {
      const report = csvReport();
      send.mockResolvedValue(body(JSON.stringify(report)));

      const result = await getQualityReport('shared-bucket', 'team-data', 'req-1');

      expect(result).toEqual({success: true, data: report});
      const input = send.mock.calls[0][0].input;
      expect(input.Bucket).toBe('shared-bucket');
      expect(input.Key).toBe('team-data/_data-quality-reports/req-1/report.json');
    });

    it('reports a missing report as not-found, NOT as an empty clean report', async () => {
      // Unlike the notifications inbox, absence is not a legitimate empty state here:
      // the user followed a link to a specific report. Rendering "no issues" over a
      // report that was never written would be the worst possible lie this page tells.
      send.mockRejectedValue(awsError('NoSuchKey', 404));

      const result = await getQualityReport('user-space', 'alice', 'gone');

      expect(result.success).toBe(false);
      expect(result.success === false && result.error.code).toBe('DataQualityReportNotFound');
    });

    it('rejects a document that is not a report, rather than rendering half a page', async () => {
      // Structurally invalid (no `exact`), and outright non-JSON. Both would otherwise
      // throw inside the render, which is a blank screen instead of an empty state.
      send.mockResolvedValueOnce(body(JSON.stringify({requestId: 'x', verdict: 'clean'})));
      const structural = await getQualityReport('user-space', 'alice', 'req-1');
      expect(structural.success === false && structural.error.code).toBe('DataQualityReportUnreadable');

      send.mockResolvedValueOnce(body('<html>nope</html>'));
      const garbage = await getQualityReport('user-space', 'alice', 'req-1');
      expect(garbage.success === false && garbage.error.code).toBe('DataQualityReportUnreadable');
    });

    it('surfaces a denied read as a typed failure carrying the AWS name', async () => {
      send.mockRejectedValue(awsError('AccessDenied', 403));
      const result = await getQualityReport('shared-bucket', 'team-data', 'req-1');
      expect(result.success).toBe(false);
      expect(result.success === false && result.error.code).toBe('AccessDenied');
    });
  });
});

// ─── from dataQualityRuns.service.test.ts ───

describe('dataQualityRuns.service', () => {
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
});
