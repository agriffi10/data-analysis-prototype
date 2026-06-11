export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export type AuthUser = {
  username: string; // Cognito username — future S3 prefix + session tag
  email?: string; // from the id token, if present
};

export type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  error: string | null; // last auth error, surfaced non-blockingly
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
};
