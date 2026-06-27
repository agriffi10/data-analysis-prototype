import { describe, it, expect, vi } from 'vitest';
import { isExpiryError, withCredentialRetry } from './credentialRetry';
import type { ServiceResult } from '../types/service.types';

describe('isExpiryError', () => {
  it('recognizes the credential-expiry SDK error names', () => {
    expect(isExpiryError('ExpiredToken')).toBe(true);
    expect(isExpiryError('ExpiredTokenException')).toBe(true);
    expect(isExpiryError('CredentialsProviderError')).toBe(true);
    expect(isExpiryError('InvalidToken')).toBe(true);
  });

  it('is false for unknown / undefined codes', () => {
    expect(isExpiryError('AccessDenied')).toBe(false);
    expect(isExpiryError(undefined)).toBe(false);
  });
});

describe('withCredentialRetry', () => {
  const okClient = (id: string): ServiceResult<{ id: string }> => ({
    success: true,
    data: { id },
  });

  it('runs the op once on success — no refresh', async () => {
    const getClient = vi.fn(async () => okClient('first'));
    const op = vi.fn(async () => ({ success: true as const, data: 'done' }));

    const result = await withCredentialRetry(getClient, op);

    expect(result).toEqual({ success: true, data: 'done' });
    expect(getClient).toHaveBeenCalledTimes(1);
    expect(op).toHaveBeenCalledTimes(1);
  });

  it('does not retry on a non-expiry error', async () => {
    const getClient = vi.fn(async () => okClient('first'));
    const op = vi.fn(async () => ({
      success: false as const,
      error: { message: 'denied', code: 'AccessDenied' },
    }));

    const result = await withCredentialRetry(getClient, op);

    expect(result.success).toBe(false);
    expect(getClient).toHaveBeenCalledTimes(1);
    expect(op).toHaveBeenCalledTimes(1);
  });

  it('refreshes the client and retries once on a credential-expiry error', async () => {
    const getClient = vi
      .fn<(forceRefresh?: boolean) => Promise<ServiceResult<{ id: string }>>>()
      .mockResolvedValueOnce(okClient('first'))
      .mockResolvedValueOnce(okClient('refreshed'));
    const op = vi
      .fn<(c: { id: string }) => Promise<ServiceResult<string>>>()
      .mockResolvedValueOnce({
        success: false,
        error: { message: 'expired', code: 'ExpiredToken' },
      })
      .mockResolvedValueOnce({ success: true, data: 'done-after-refresh' });

    const result = await withCredentialRetry(getClient, op);

    expect(result).toEqual({ success: true, data: 'done-after-refresh' });
    expect(getClient).toHaveBeenCalledTimes(2);
    expect(getClient).toHaveBeenNthCalledWith(2, true); // forced refresh
    expect(op).toHaveBeenCalledTimes(2);
    expect(op).toHaveBeenNthCalledWith(2, { id: 'refreshed' });
  });

  it('surfaces a client-acquisition failure without running the op', async () => {
    const getClient = vi.fn(async () => ({
      success: false as const,
      error: { message: 'no creds' },
    }));
    const op = vi.fn();

    const result = await withCredentialRetry(getClient, op);

    expect(result.success).toBe(false);
    expect(op).not.toHaveBeenCalled();
  });

  it('returns the refreshed-client error if the refresh itself fails', async () => {
    const getClient = vi
      .fn<(forceRefresh?: boolean) => Promise<ServiceResult<{ id: string }>>>()
      .mockResolvedValueOnce(okClient('first'))
      .mockResolvedValueOnce({
        success: false,
        error: { message: 'refresh failed' },
      });
    const op = vi.fn(async () => ({
      success: false as const,
      error: { message: 'expired', code: 'ExpiredToken' },
    }));

    const result = await withCredentialRetry(getClient, op);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('refresh failed');
    expect(op).toHaveBeenCalledTimes(1); // never retried
  });
});
