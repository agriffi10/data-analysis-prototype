import {DynamoDBClient, GetItemCommand} from '@aws-sdk/client-dynamodb';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {REPLACE_CONDITION, STORE_CALL_TIMEOUT_MS, boundedSend} from './store';
import {idToken, storedSession, testDeps} from './testSupport';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the DynamoDB session store', () => {
  it('reads consistently, and replaces tokens only on the condition the double enforces', async () => {
    const {store, dynamo} = testDeps();
    const {item} = storedSession({version: 4});
    await store.put(item);
    const next = {idToken: idToken({jti: 'next'}), tokenExpiresAt: item.tokenExpiresAt + 60};

    await store.get(item.pk);
    expect(await store.replaceTokens(item.pk, 4, next)).toBe(true);

    const [read, update] = dynamo.sent.filter(({name}) => name !== 'PutItemCommand');
    expect(read).toEqual({
      name: 'GetItemCommand',
      input: {TableName: 'test-sessions', Key: {pk: {S: item.pk}}, ConsistentRead: true}
    });
    expect(update.name).toBe('UpdateItemCommand');
    expect(update.input).toEqual({
      TableName: 'test-sessions',
      Key: {pk: {S: item.pk}},
      UpdateExpression: 'SET #idToken = :idToken, #tokenExpiresAt = :tokenExpiresAt, #version = :nextVersion',
      ConditionExpression: REPLACE_CONDITION,
      ExpressionAttributeNames: {
        '#pk': 'pk',
        '#idToken': 'idToken',
        '#tokenExpiresAt': 'tokenExpiresAt',
        '#version': 'version'
      },
      ExpressionAttributeValues: {
        ':idToken': {S: next.idToken},
        ':tokenExpiresAt': {N: String(next.tokenExpiresAt)},
        ':expectedVersion': {N: '4'},
        ':nextVersion': {N: '5'}
      }
    });
    expect(REPLACE_CONDITION).toBe('attribute_exists(#pk) AND #version = :expectedVersion');
  });

  it('aborts a store call that has not answered after two seconds, and not before', async () => {
    vi.useFakeTimers();
    vi.spyOn(DynamoDBClient.prototype, 'send').mockImplementation(
      ((_command: unknown, options: {abortSignal: AbortSignal}) =>
        new Promise((_resolve, reject) =>
          options.abortSignal.addEventListener('abort', () => reject(options.abortSignal.reason))
        )) as unknown as DynamoDBClient['send']
    );
    let settled = false;

    const call = boundedSend('us-east-1')(new GetItemCommand({TableName: 't', Key: {pk: {S: 'k'}}})).finally(() => {
      settled = true;
    });
    const outcome = call.catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(STORE_CALL_TIMEOUT_MS - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await outcome).toMatchObject({name: 'TimeoutError'});
    expect(STORE_CALL_TIMEOUT_MS).toBe(2_000);
  });
});
