export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export type AuthUser = {
  /** Cognito username — also the user's S3 prefix and principal tag. */
  username: string;
  /** From the ID token claim, when present. */
  email?: string;
};

export type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  /** Last auth error, surfaced non-blockingly. */
  error: string | null;
  signIn: () => Promise<void>;
  /** The same sign-in, whose Managed Login page links to sign-up. */
  signUp: () => Promise<void>;
  signOut: () => Promise<void>;
};
