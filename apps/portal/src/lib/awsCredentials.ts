import { fetchAuthSession } from 'aws-amplify/auth';
import type { ServiceResult } from '../types/service.types';

// The Cognito Identity Pool credentials Amplify holds for the signed-in user.
type SessionCredentials = NonNullable<
  Awaited<ReturnType<typeof fetchAuthSession>>['credentials']
>;

// Fetch the signed-in user's scoped Identity Pool credentials (SPEC-011). Shared
// by the Athena and Glue client builders (SPEC-034 FR-001); `getS3Client` mirrors
// this inline because it additionally constructs a dev-only static client and sets
// checksum options. `forceRefresh` drives the credential-expiry retry path.
// Never throws — returns the ServiceResult error shape instead.
export async function getSessionCredentials(
  forceRefresh = false,
): Promise<ServiceResult<SessionCredentials>> {
  try {
    const session = await fetchAuthSession({ forceRefresh });
    if (!session.credentials) {
      return {
        success: false,
        error: { message: 'No AWS credentials — sign in required' },
      };
    }
    return { success: true, data: session.credentials };
  } catch (err) {
    const e = err as { message?: string; name?: string };
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain AWS credentials',
        code: e.name,
      },
    };
  }
}

// Fetch the signed-in user's Cognito ID token (JWT). SPEC-056 trusted-actor
// binding: shared-space requests carry this token in the message; the provisioner
// Lambda verifies it server-side and derives the actor from cognito:username, so
// the caller's identity can't be spoofed. Never throws.
export async function getIdToken(
  forceRefresh = false,
): Promise<ServiceResult<string>> {
  try {
    const session = await fetchAuthSession({ forceRefresh });
    const idToken = session.tokens?.idToken?.toString();
    if (!idToken) {
      return {
        success: false,
        error: { message: 'No ID token — sign in required' },
      };
    }
    return { success: true, data: idToken };
  } catch (err) {
    const e = err as { message?: string; name?: string };
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain ID token',
        code: e.name,
      },
    };
  }
}
