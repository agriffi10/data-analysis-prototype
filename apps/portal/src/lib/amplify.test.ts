import {describe, it, expect, vi, afterEach} from 'vitest';
import {Amplify} from 'aws-amplify';
import {configureAmplify, isAmplifyConfigured} from './amplify';
import {clearRuntimeConfig, seedRuntimeConfig} from '../test/seedRuntimeConfig';

vi.mock('aws-amplify', () => ({Amplify: {configure: vi.fn()}}));

const configure = vi.mocked(Amplify.configure);

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
