import {afterEach, describe, expect, it, vi} from 'vitest';
import {toUserMessage} from './errorMessages';

const RAW_AWS = 'AccessDenied: User: arn:aws:sts::123:assumed-role/portal is not authorized to perform s3:GetObject';

describe('toUserMessage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('passes a recognized app code through with its authored message', () => {
    const {message} = toUserMessage({code: 'Collision', message: '"reports/q4.csv" already exists.'});
    expect(message).toBe('"reports/q4.csv" already exists.');
  });

  it('maps a recognized AWS error name to friendly non-fixable text, ignoring the raw message', () => {
    const {message} = toUserMessage({code: 'AccessDenied', message: RAW_AWS});
    expect(message).toBe("You don't have permission to do that. Contact the Administrator.");
    expect(message).not.toContain('arn:aws');
  });

  it('maps an expired-credential code to a sign-in fix', () => {
    expect(toUserMessage({code: 'ExpiredToken', message: 'The provided token has expired.'}).message).toBe(
      'Your session expired. Sign in again.'
    );
  });

  it('maps an unqualified-table Athena failure to the add-database fix (FR-005)', () => {
    const {message} = toUserMessage({
      code: 'FAILED',
      message: 'line 1:15: Table sales does not exist'
    });
    expect(message).toBe('Add a database to each table, like `mydb.sales`.');
  });

  it('treats a qualified missing table as a not-found error, not the unqualified fix', () => {
    const {message} = toUserMessage({
      code: 'FAILED',
      message: 'line 1:15: Table mydb.sales does not exist'
    });
    expect(message).toContain('table wasn’t found');
    expect(message).not.toContain('Add a database');
  });

  it('maps an Athena column-resolution failure', () => {
    expect(
      toUserMessage({code: 'FAILED', message: "SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved"}).message
    ).toContain('column');
  });

  it('maps an Athena syntax error', () => {
    expect(toUserMessage({code: 'FAILED', message: 'SYNTAX_ERROR: mismatched input'}).message).toContain(
      'syntax error'
    );
  });

  it('returns the generic fallback for an unrecognized error and never echoes the raw message', () => {
    const raw = "TypeError: Cannot read properties of undefined (reading 'bucket')";
    const {message} = toUserMessage({code: 'KaboomException', message: raw});
    expect(message).toBe('Something went wrong. Contact the Administrator.');
    expect(message).not.toContain('undefined');
    expect(message).not.toContain('KaboomException');
  });

  it('preserves service-authored "missed information" text via passthrough codes (FR-005)', () => {
    // InvalidName carries the folder-name validation reason; TooLarge carries the size.
    expect(toUserMessage({code: 'InvalidName', message: 'Folder names cannot contain “/”.'}).message).toBe(
      'Folder names cannot contain “/”.'
    );
    expect(
      toUserMessage({code: 'TooLarge', message: 'File exceeds the maximum upload size of 100 bytes.'}).message
    ).toBe('File exceeds the maximum upload size of 100 bytes.');
  });

  it('maps a not-signed-in credential failure to a sign-in prompt', () => {
    expect(toUserMessage({code: 'NotAuthenticated', message: 'No AWS credentials — sign in required'}).message).toBe(
      'Sign in to continue.'
    );
  });

  it('accepts a thrown Error (name-based) as well as a ServiceResult error', () => {
    const err = Object.assign(new Error('Network request failed'), {name: 'NetworkError'});
    expect(toUserMessage(err).message).toContain('Check your connection');
  });

  it('logs the original error to the console in a dev build', () => {
    vi.stubEnv('DEV', true);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    toUserMessage({code: 'AccessDenied', message: RAW_AWS});
    expect(warn).toHaveBeenCalled();
    expect(warn.mock.calls[0].join(' ')).toContain('AccessDenied');
  });

  it('does not log and returns mapped text with no raw message in a production build (FR-006)', () => {
    vi.stubEnv('DEV', false);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const {message} = toUserMessage({code: 'AccessDenied', message: RAW_AWS});
    expect(warn).not.toHaveBeenCalled();
    expect(message).not.toContain('arn:aws');
    expect(message).toBe("You don't have permission to do that. Contact the Administrator.");
  });
});
