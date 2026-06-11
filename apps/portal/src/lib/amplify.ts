import { Amplify } from 'aws-amplify';

// Cognito config comes from build-time env vars (tofu output — SPEC-006).
const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined;
const userPoolClientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID as
  | string
  | undefined;
const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
const appUrl = import.meta.env.VITE_APP_URL as string | undefined;

// If any required Cognito var is missing we skip configuration rather than throw.
// Auth features surface a config error (SPEC-007 FR-001); the file browser is
// unaffected. Note: no identityPoolId yet — credential exchange is SPEC-011.
export const isAmplifyConfigured = Boolean(
  userPoolId && userPoolClientId && domain && appUrl,
);

if (isAmplifyConfigured) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: userPoolId!,
        userPoolClientId: userPoolClientId!,
        loginWith: {
          oauth: {
            domain: domain!,
            scopes: ['openid', 'email', 'profile'],
            redirectSignIn: [appUrl!],
            redirectSignOut: [appUrl!],
            responseType: 'code',
          },
        },
      },
    },
  });
}
