import {Amplify} from 'aws-amplify';
import {cognitoUserPoolsTokenProvider} from 'aws-amplify/auth/cognito';
import {sessionStorage as tabScopedStorage} from 'aws-amplify/utils';
import {configValue} from './runtimeConfig';

/**
 * True when every Cognito value login needs is configured.
 *
 * A FUNCTION, not a const: the values arrive with the runtime document, which the
 * bootstrap fetches before anything renders. Captured at module load it would read an
 * unloaded document — a throw in a production build, and the deployed names instead of
 * the stubbed ones in a test.
 *
 * When any is missing, configuration is skipped rather than throwing — auth features
 * surface a config error while the rest of the app stays usable.
 *
 * @returns Whether `configureAmplify` will configure anything.
 */
export function isAmplifyConfigured(): boolean {
  return Boolean(
    configValue('cognitoUserPoolId') &&
    configValue('cognitoUserPoolClientId') &&
    configValue('cognitoDomain') &&
    configValue('appUrl')
  );
}

/**
 * Configure Amplify from the runtime document.
 *
 * Called once by the bootstrap, after the document resolves and before the first render:
 * a sign-in that begins against an unconfigured Amplify fails in a way a warm session
 * never reproduces.
 *
 * TOKENS ARE HELD PER TAB, not per browser. Amplify's default is `localStorage`, where an
 * ID token outlives the browser being closed and is readable by anything running on the
 * origin; scoping it to the tab means closing the tab ends the session. The cost is
 * deliberate and visible: there is no "stay signed in", and a second tab signs in again
 * rather than inheriting the first one's session.
 *
 * @returns None.
 */
export function configureAmplify(): void {
  if (!isAmplifyConfigured()) return;

  const userPoolId = configValue('cognitoUserPoolId') as string;
  const userPoolClientId = configValue('cognitoUserPoolClientId') as string;
  const appUrl = configValue('appUrl') as string;

  const oauth = {
    domain: configValue('cognitoDomain') as string,
    scopes: ['openid', 'email', 'profile'],
    redirectSignIn: [appUrl],
    redirectSignOut: [appUrl],
    responseType: 'code' as const
  };

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: {oauth}
      }
    }
  });

  // After `configure`, never before: the provider resolves the pool it was configured
  // with, and a storage set on an unconfigured provider is discarded.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(tabScopedStorage);
  removeBrowserWideTokens();
}

/** Amplify's prefix for every key it writes, tokens and redirect state alike. */
const AMPLIFY_KEY_PREFIX = 'CognitoIdentityServiceProvider.';

/** The session keys Amplify's token store writes per user, the last segment of each key. */
const TOKEN_KEY_NAMES = new Set([
  'idToken',
  'accessToken',
  'refreshToken',
  'clockDrift',
  'oauthMetadata',
  'signInDetails'
]);

/**
 * Remove the token set a browser kept from before tokens were held per tab.
 *
 * Nothing reads `localStorage` for tokens any more, so the old set is inert, but it is a
 * complete, readable session left on the origin until the browser is wiped. Only the
 * session's keys go: `<prefix><client>.LastAuthUser` and `<prefix><client>.<user>.<token>`.
 * The token store's device keys stay, as Amplify's own sign-out leaves them. The redirect
 * sign-in state (`oauthPKCE`, `oauthState`, `inflightOAuth`, `oauthSignIn`) still lives in
 * `localStorage` and a sign-in in flight needs it, so it is left alone.
 *
 * @returns None.
 */
function removeBrowserWideTokens(): void {
  try {
    const keys = Array.from({length: localStorage.length}, (_, index) => localStorage.key(index));
    for (const key of keys) {
      if (!key?.startsWith(AMPLIFY_KEY_PREFIX)) continue;
      const segments = key.slice(AMPLIFY_KEY_PREFIX.length).split('.');
      const isLastAuthUser = segments.length === 2 && segments[1] === 'LastAuthUser';
      const isToken = segments.length >= 3 && TOKEN_KEY_NAMES.has(segments[segments.length - 1]);
      if (isLastAuthUser || isToken) localStorage.removeItem(key);
    }
  } catch {
    // localStorage unavailable — there is nothing left in it to remove.
  }
}
