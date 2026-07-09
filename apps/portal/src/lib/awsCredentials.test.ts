import {describe, it, expect, vi, beforeEach} from 'vitest';

vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));
import {fetchAuthSession} from 'aws-amplify/auth';
import {getSessionCredentials, getIdToken} from './awsCredentials';

const mockSession = vi.mocked(fetchAuthSession);

beforeEach(() => vi.clearAllMocks());

describe('getSessionCredentials', () => {
  it('returns the session credentials on success', async () => {
    const credentials = {accessKeyId: 'AKIA', secretAccessKey: 's', sessionToken: 't'};
    mockSession.mockResolvedValue({credentials} as never);
    const result = await getSessionCredentials();
    expect(result).toEqual({success: true, data: credentials});
  });

  it('fails when the session has no credentials', async () => {
    mockSession.mockResolvedValue({} as never);
    const result = await getSessionCredentials();
    expect(result.success).toBe(false);
  });

  it('passes forceRefresh through to Amplify', async () => {
    mockSession.mockResolvedValue({credentials: {accessKeyId: 'AKIA'}} as never);
    await getSessionCredentials(true);
    expect(mockSession).toHaveBeenCalledWith({forceRefresh: true});
  });
});

describe('getIdToken', () => {
  it('returns the ID token string on success', async () => {
    mockSession.mockResolvedValue({tokens: {idToken: {toString: () => 'jwt-abc'}}} as never);
    const result = await getIdToken();
    expect(result).toEqual({success: true, data: 'jwt-abc'});
  });

  it('fails when no ID token is present', async () => {
    mockSession.mockResolvedValue({tokens: {}} as never);
    const result = await getIdToken();
    expect(result.success).toBe(false);
  });

  it('maps a thrown error to a ServiceResult with its name as code', async () => {
    mockSession.mockRejectedValue(Object.assign(new Error('network down'), {name: 'NetworkError'}));
    const result = await getIdToken();
    expect(result).toEqual({success: false, error: {message: 'network down', code: 'NetworkError'}});
  });
});
