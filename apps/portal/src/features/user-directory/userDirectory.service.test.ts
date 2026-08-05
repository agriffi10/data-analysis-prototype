import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {DIRECTORY_KEY, getUserDirectory} from './userDirectory.service';
import {getS3Client} from '../../lib/s3Client';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const send = vi.fn();

const awsError = (name: string, status?: number) =>
  Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

const body = (value: unknown) => ({
  Body: {transformToString: async () => (typeof value === 'string' ? value : JSON.stringify(value))}
});

const document = (over: Record<string, unknown> = {}) => ({
  version: 1,
  generatedAt: '2026-08-05T04:00:11Z',
  count: 2,
  usernames: ['alice', 'bob_smith'],
  ...over
});

beforeEach(() => {
  vi.clearAllMocks();
  send.mockReset();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.mocked(getS3Client).mockResolvedValue({success: true, data: {send} as never});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('getUserDirectory', () => {
  it('reads the key SPEC-146 publishes, from the user-space bucket', async () => {
    send.mockResolvedValue(body(document()));

    const result = await getUserDirectory();

    expect(DIRECTORY_KEY).toBe('_directory/usernames.json');
    const command = send.mock.calls[0][0];
    expect(command.input).toMatchObject({Bucket: 'user-space', Key: '_directory/usernames.json'});
    expect(result).toEqual({
      success: true,
      data: {usernames: ['alice', 'bob_smith'], generatedAt: '2026-08-05T04:00:11Z'}
    });
  });

  it('reads the bucket name at call time, not module load', async () => {
    // A module-level `import.meta.env` const would have been captured before `stubEnv` ran.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'a-different-bucket');
    send.mockResolvedValue(body(document()));

    await getUserDirectory();

    expect(send.mock.calls[0][0].input.Bucket).toBe('a-different-bucket');
  });

  it('treats a missing document as the empty state, not an error', async () => {
    // The ordinary state of the bucket until the builder's first run.
    send.mockRejectedValue(awsError('NoSuchKey', 404));

    expect(await getUserDirectory()).toEqual({success: true, data: {usernames: [], generatedAt: null}});
  });

  it('treats a corrupt document as the empty state', async () => {
    send.mockResolvedValue(body('{not json'));

    expect(await getUserDirectory()).toEqual({success: true, data: {usernames: [], generatedAt: null}});
  });

  it('refuses a version it does not understand, and names it', async () => {
    // A shape this reader does not understand is not a shape it should guess at.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    send.mockResolvedValue(body(document({version: 2})));

    const result = await getUserDirectory();

    expect(result).toEqual({success: true, data: {usernames: [], generatedAt: null}});
    expect(warn.mock.calls[0][0]).toContain('2');
    warn.mockRestore();
  });

  it('treats a non-array usernames field as empty', async () => {
    send.mockResolvedValue(body(document({usernames: {alice: true}})));

    expect((await getUserDirectory()) as never).toMatchObject({data: {usernames: []}});
  });

  it('re-checks every entry against the catalog-safe rule', async () => {
    // The producer already guarantees this. The consumer re-checks because the array is
    // rendered into the DOM and used to build keys, and a producer guarantee is not a runtime
    // guarantee — the object is one `aws s3 cp` away from holding anything.
    send.mockResolvedValue(body(document({usernames: ['alice', 'Bob', '../etc/passwd', 42, '', 'cara']})));

    const result = await getUserDirectory();

    expect(result).toMatchObject({success: true, data: {usernames: ['alice', 'cara']}});
  });

  it('reports a real fault as a failure', async () => {
    send.mockRejectedValue(awsError('AccessDenied', 403));

    const result = await getUserDirectory();

    expect(result.success).toBe(false);
  });

  it('never throws', async () => {
    send.mockImplementation(() => {
      throw new TypeError('something unexpected');
    });

    await expect(getUserDirectory()).resolves.toMatchObject({success: false});
  });

  it('drops generatedAt when it is not a string, keeping the usernames', async () => {
    send.mockResolvedValue(body(document({generatedAt: 12345})));

    expect(await getUserDirectory()).toMatchObject({data: {usernames: ['alice', 'bob_smith'], generatedAt: null}});
  });
});
