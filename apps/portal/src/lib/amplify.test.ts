import {describe, it, expect, vi, afterEach} from 'vitest';
import {Amplify} from 'aws-amplify';
import {cognitoUserPoolsTokenProvider} from 'aws-amplify/auth/cognito';
import {defaultStorage, sessionStorage} from 'aws-amplify/utils';
import {configureAmplify, isAmplifyConfigured} from './amplify';
import {clearRuntimeConfig, seedRuntimeConfig} from '../test/seedRuntimeConfig';

vi.mock('aws-amplify', () => ({Amplify: {configure: vi.fn()}}));
vi.mock('aws-amplify/auth/cognito', () => ({
  cognitoUserPoolsTokenProvider: {setKeyValueStorage: vi.fn()}
}));
// Two DISTINCT sentinels, so the assertion is about WHICH store was chosen rather than
// about the call having happened — the browser-wide one is the mistake being guarded.
vi.mock('aws-amplify/utils', () => ({
  sessionStorage: {scope: 'tab'},
  defaultStorage: {scope: 'browser'}
}));

const configure = vi.mocked(Amplify.configure);
const setStorage = vi.mocked(cognitoUserPoolsTokenProvider.setKeyValueStorage);

/** The four values login needs, plus whatever the caller adds. */
function cognito(extra: Record<string, string> = {}) {
  return {
    cognitoUserPoolId: 'us-east-1_pool',
    cognitoUserPoolClientId: 'client-id',
    cognitoDomain: 'auth.example.test',
    appUrl: 'https://portal.example.test',
    ...extra
  };
}

afterEach(() => {
  clearRuntimeConfig();
  vi.clearAllMocks();
});

describe('isAmplifyConfigured', () => {
  it('is true when every value login needs is present', () => {
    seedRuntimeConfig(cognito());

    expect(isAmplifyConfigured()).toBe(true);
  });

  it.each(['cognitoUserPoolId', 'cognitoUserPoolClientId', 'cognitoDomain', 'appUrl'])('is false without %s', (key) => {
    seedRuntimeConfig({...cognito(), [key]: ''});

    expect(isAmplifyConfigured()).toBe(false);
  });

  it('does not require the Identity Pool — login works without credentials', () => {
    // The same line the gate has always drawn: sign-in works without it, only AWS
    // credentials do not.
    seedRuntimeConfig(cognito());

    expect(isAmplifyConfigured()).toBe(true);
  });
});

describe('configureAmplify', () => {
  it('configures nothing when the Cognito values are missing', () => {
    seedRuntimeConfig({});

    configureAmplify();

    expect(configure).not.toHaveBeenCalled();
  });

  it('includes the Identity Pool when it is configured', () => {
    seedRuntimeConfig(cognito({cognitoIdentityPoolId: 'us-east-1:pool-id'}));

    configureAmplify();

    expect(configure).toHaveBeenCalledOnce();
    expect(configure.mock.calls[0][0]).toEqual({
      Auth: {
        Cognito: {
          userPoolId: 'us-east-1_pool',
          userPoolClientId: 'client-id',
          identityPoolId: 'us-east-1:pool-id',
          loginWith: {
            oauth: {
              domain: 'auth.example.test',
              scopes: ['openid', 'email', 'profile'],
              redirectSignIn: ['https://portal.example.test'],
              redirectSignOut: ['https://portal.example.test'],
              responseType: 'code'
            }
          }
        }
      }
    });
  });

  it('OMITS the key entirely without it, rather than passing undefined', () => {
    // The two branches are two clean object literals on purpose: Amplify's Cognito config
    // is a strict union, and an optional or ternary identityPoolId defeats the inference —
    // it demands a definite string. Collapsing them is a type error waiting to be silenced
    // with a cast.
    seedRuntimeConfig(cognito());

    configureAmplify();

    const config = configure.mock.calls[0][0] as {Auth: {Cognito: Record<string, unknown>}};
    expect('identityPoolId' in config.Auth.Cognito).toBe(false);
  });
});

describe('token storage', () => {
  it('holds tokens for the TAB, not for the whole browser', () => {
    seedRuntimeConfig(cognito());

    configureAmplify();

    expect(setStorage).toHaveBeenCalledWith(sessionStorage);
    expect(setStorage).not.toHaveBeenCalledWith(defaultStorage);
  });

  it('sets the storage AFTER configuring, never before', () => {
    // The provider resolves the pool it was configured with, so a storage set first is
    // discarded — and the wrong order still satisfies a test that only counts the calls.
    seedRuntimeConfig(cognito());

    configureAmplify();

    expect(configure.mock.invocationCallOrder[0]).toBeLessThan(setStorage.mock.invocationCallOrder[0]);
  });

  it('sets no storage when nothing was configured to read it', () => {
    // An installed but EMPTY document, so every read is genuinely unset — unseeded, the
    // dev fallback answers from the local environment and the portal reads as configured.
    seedRuntimeConfig({});

    configureAmplify();

    expect(setStorage).not.toHaveBeenCalled();
  });
});
