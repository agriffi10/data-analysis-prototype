import {GlueClient} from '@aws-sdk/client-glue';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';
import {configValue} from './runtimeConfig';

/**
 * Builds a GlueClient from the signed-in user's Identity Pool credentials.
 *
 * IAM scopes Glue to the user's own database via the `username` principal tag —
 * anything else is denied server-side. Pass `forceRefresh` on credential expiry
 * (callers wrap calls in `withCredentialRetry(getGlueClient, …)`). Never throws
 * — returns a ServiceResult.
 */
export async function getGlueClient(forceRefresh = false): Promise<ServiceResult<GlueClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new GlueClient({
      region: configValue('awsRegion'),
      credentials: creds.data
    })
  };
}
