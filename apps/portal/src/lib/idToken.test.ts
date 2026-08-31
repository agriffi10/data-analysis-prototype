import {beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchAuthSession} from 'aws-amplify/auth';
import {getIdToken} from './idToken';

vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));

describe('getIdToken', () => {
  const mockSession = vi.mocked(fetchAuthSession);

  beforeEach(() => vi.clearAllMocks());

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

  it('passes forceRefresh through to Amplify — the one path that re-mints a claim', async () => {
    mockSession.mockResolvedValue({tokens: {idToken: {toString: () => 'jwt-abc'}}} as never);
    await getIdToken(true);
    expect(mockSession).toHaveBeenCalledWith({forceRefresh: true});
  });
});
