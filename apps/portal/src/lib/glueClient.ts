import {GlueClient} from '@aws-sdk/client-glue';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';

// Authenticated Glue client (SPEC-034 FR-001). Same scoped Identity Pool
// credentials as getAthenaClient/getS3Client; the portal role's analytics policy
// (SPEC-032 FR-006) scopes Glue to the user's own database
// (`database/${aws:PrincipalTag/username}` + its tables), so the app only ever
// requests the user's own derived database — anything else is denied by IAM.
// On a credential-expiry error, callers retry via withCredentialRetry(getGlueClient,
// ...). Never throws — returns the ServiceResult error shape.
export async function getGlueClient(forceRefresh = false): Promise<ServiceResult<GlueClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new GlueClient({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: creds.data
    })
  };
}
