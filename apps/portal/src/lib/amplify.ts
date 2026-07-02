import {Amplify} from 'aws-amplify';

// Cognito config comes from build-time VITE_ env vars.
const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined;
const userPoolClientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID as string | undefined;
const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
const appUrl = import.meta.env.VITE_APP_URL as string | undefined;
// Identity Pool exchanges the User Pool token for scoped AWS credentials.
// Optional: login works without it, but fetchAuthSession() yields no credentials
// until it is set.
const identityPoolId = import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID as string | undefined;

/**
 * True when all Cognito env vars required for login are set.
 *
 * When any is missing, configuration is skipped rather than throwing — auth
 * features surface a config error while the rest of the app stays usable.
 * identityPoolId is not part of this gate; login does not require it.
 */
export const isAmplifyConfigured = Boolean(userPoolId && userPoolClientId && domain && appUrl);

if (isAmplifyConfigured) {
  // Amplify's Cognito config is a strict union — a single object literal matches
  // cleanly, but an optional/ternary identityPoolId confuses inference (it demands
  // a definite string). So we configure in two branches, each a clean literal.
  const oauth = {
    domain: domain!,
    scopes: ['openid', 'email', 'profile'],
    redirectSignIn: [appUrl!],
    redirectSignOut: [appUrl!],
    responseType: 'code' as const
  };

  if (identityPoolId) {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId: userPoolId!,
          userPoolClientId: userPoolClientId!,
          identityPoolId,
          loginWith: {oauth}
        }
      }
    });
  } else {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId: userPoolId!,
          userPoolClientId: userPoolClientId!,
          loginWith: {oauth}
        }
      }
    });
  }
}
