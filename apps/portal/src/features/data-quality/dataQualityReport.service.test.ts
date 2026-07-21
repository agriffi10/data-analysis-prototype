import {describe, it, expect, vi, beforeEach} from 'vitest';
import {getQualityReport, reportKey} from './dataQualityReport.service';
import {getS3Client} from '../../lib/s3Client';
import {csvReport} from './reportFixtures';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

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
