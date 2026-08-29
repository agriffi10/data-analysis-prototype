import {beforeEach, describe, expect, it, vi} from 'vitest';
import {asSentence, isApproximateIssue, locationLabel, sourceFolderPrefix} from './dataQuality.format';
import {enqueueQualityCheck} from './dataQuality.service';
import {getQualityReport, reportKey} from './dataQualityReport.service';
import {apiRequest} from '../../lib/apiClient';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {getRunsIndex} from './dataQualityRuns.service';
import type {DataQualityRequest} from './dataQuality.types';

// ─── from dataQuality.format.test.ts ───
vi.mock('../../lib/awsCredentials', () => ({
  getIdToken: vi.fn(),
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));
vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));

describe('dataQuality.format', () => {
  describe('locationLabel', () => {
    it('names a folder by its own segment and a file by its basename', () => {
      expect(locationLabel('alice/data/sales/')).toBe('sales');
      expect(locationLabel('alice/data/sales.csv')).toBe('sales.csv');
      expect(locationLabel('sales.csv')).toBe('sales.csv');
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
  const REQUEST_ID = '11111111-2222-4333-8444-555555555555';

  function makeReq(over: Partial<DataQualityRequest> = {}): DataQualityRequest {
    return {
      requestId: REQUEST_ID,
      space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
      location: 'alice/sales/',
      ...over
    };
  }

  /**
   * The data-quality enqueue, now over the API.
   *
   * **The location group id is deliberately absent from this file.** It was the digest of
   * `{bucket}/{location}` — hashed rather than raw because SQS caps a group id at 128 characters
   * where an S3 key reaches 1024 — and the whole of it moved: the digest itself is replayed
   * against vectors captured from this service in `lambdas/api/test_fifo_derivations.py`, and the
   * one-character divergence that made two spellings of one location serialize (this plane strips
   * BOTH ends where the space-keyed planes keep a trailing slash) has its own named test there.
   *
   * The `idToken` field went the same way — the API stamps it from the verified bearer and
   * refuses a body that claims one.
   */
  describe('enqueueQualityCheck', () => {
    let api: ApiMock;

    beforeEach(() => {
      api = mockApi(vi.mocked(apiRequest));
    });

    it('sends the check once and echoes back the caller’s own request id', async () => {
      api.on('dataQuality.enqueue', {success: true, data: {requestId: REQUEST_ID}});

      const res = await enqueueQualityCheck(makeReq());

      // This service is the one of the ten that keeps a payload: the id is what the runs index
      // and the report link are keyed on, and it is the caller's, never the API's.
      expect(res).toEqual({success: true, data: {requestId: REQUEST_ID}});
      expect(api.routes()).toEqual(['dataQuality.enqueue']);
      // `toEqual`, not `toMatchObject`: the absence of a claimed identity is the assertion.
      expect(api.bodyFor('dataQuality.enqueue')).toEqual({
        requestId: REQUEST_ID,
        space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
        location: 'alice/sales/'
      });
    });

    it('returns the failure as a result and never throws', async () => {
      api.on('dataQuality.enqueue', apiFailure('ApiUnavailable'));

      const res = await enqueueQualityCheck(makeReq());

      expect(res.success).toBe(false);
      expect(res.success === false && res.error.code).toBe('ApiUnavailable');
    });
  });
});

// ─── from dataQualityReport.service.test.ts ───

describe('dataQualityReport.service', () => {
  const send = vi.mocked(apiRequest);

  /** The document route's answer: the object's bytes as text, never parsed. */
  const body = (text: string) => ({success: true as const, data: {body: text, etag: 'e'}});

  /** A failure now arrives as a machine code rather than as a thrown AWS error. */
  const awsError = (code: string) => ({
    success: false as const,
    error: {message: '', code: code === 'NoSuchKey' ? 'NotFound' : code}
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('reportKey', () => {
    it('builds the key assemble-report writes, for personal and shared spaces alike', () => {
      // Mirrors dq_assemble_report.report_key — a pure function of the request id.
      expect(reportKey('alice', 'req-1')).toBe('alice/_data-quality-reports/req-1/report.json');
      expect(reportKey('team-data', 'req-1')).toBe('team-data/_data-quality-reports/req-1/report.json');
    });
  });

  describe('getQualityReport', () => {
    it('reports a missing report as not-found, NOT as an empty clean report', async () => {
      // Unlike the notifications inbox, absence is not a legitimate empty state here:
      // the user followed a link to a specific report. Rendering "no issues" over a
      // report that was never written would be the worst possible lie this page tells.
      send.mockResolvedValue(awsError('NoSuchKey'));

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
      send.mockResolvedValue(awsError('AccessDenied'));
      const result = await getQualityReport('shared-bucket', 'team-data', 'req-1');
      expect(result.success).toBe(false);
      expect(result.success === false && result.error.code).toBe('AccessDenied');
    });
  });
});

// ─── from dataQualityRuns.service.test.ts ───

describe('dataQualityRuns.service', () => {
  const send = vi.mocked(apiRequest);

  /** A failure arrives as a machine code now, not as a thrown AWS error. */
  const awsError = (name: string) => ({
    success: false as const,
    error: {message: '', code: name === 'NoSuchKey' ? 'NotFound' : name}
  });

  const body = (value: unknown) => ({
    success: true as const,
    data: {body: typeof value === 'string' ? value : JSON.stringify(value), etag: 'e'}
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
      send.mockResolvedValue(awsError('NoSuchKey'));

      const result = await getRunsIndex('user-space', 'alice');

      expect(result).toEqual({success: true, data: []});
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
  });
});
