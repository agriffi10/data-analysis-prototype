import {Amplify} from 'aws-amplify';
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
}
