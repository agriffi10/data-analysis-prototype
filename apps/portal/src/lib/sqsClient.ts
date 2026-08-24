import {SQSClient} from '@aws-sdk/client-sqs';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';
import {configValue} from './runtimeConfig';

/**
 * Builds an SQSClient from the signed-in user's Identity Pool credentials.
 *
 * The browser's only privileged control-plane action is `sqs:SendMessage` to
 * the request queues — all provisioning happens server-side. Pass
 * `forceRefresh` on credential expiry (callers wrap calls in
 * `withCredentialRetry(getSqsClient, …)`). Never throws — returns a
 * ServiceResult.
 */
export async function getSqsClient(forceRefresh = false): Promise<ServiceResult<SQSClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new SQSClient({
      region: configValue('awsRegion'),
      credentials: creds.data
    })
  };
}
