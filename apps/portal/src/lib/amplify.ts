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
 * surface a config error while the rest of the app stays usable. `cognitoIdentityPoolId`
 * is not part of this gate; login does not require it.
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
  const identityPoolId = configValue('cognitoIdentityPoolId');

  const oauth = {
    domain: configValue('cognitoDomain') as string,
    scopes: ['openid', 'email', 'profile'],
    redirectSignIn: [appUrl],
    redirectSignOut: [appUrl],
    responseType: 'code' as const
  };

  // Amplify's Cognito config is a strict union — a single object literal matches
  // cleanly, but an optional/ternary identityPoolId confuses inference (it demands
  // a definite string). So we configure in two branches, each a clean literal.
  if (identityPoolId) {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId,
          userPoolClientId,
          identityPoolId,
          loginWith: {oauth}
        }
      }
    });
  } else {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId,
          userPoolClientId,
          loginWith: {oauth}
        }
      }
    });
  }

  // After `configure`, never before: the provider resolves the pool it was configured
  // with, and a storage set on an unconfigured provider is discarded.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(tabScopedStorage);
}
