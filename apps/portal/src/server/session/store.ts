import 'server-only';
import {
  ConditionalCheckFailedException,
  DeleteItemCommand,
  DynamoDBClient,
  GetItemCommand,
  PutItemCommand,
  UpdateItemCommand,
  type AttributeValue
} from '@aws-sdk/client-dynamodb';
import type {SessionItem, SessionStore} from './session.types';
import {deadline} from './deadline';

/** Every store call is bounded, so a stalled table answers 503 rather than holding the request. */
export const STORE_CALL_TIMEOUT_MS = 2_000;

/**
 * The compare-and-set's condition. Either clause alone refuses an absent item, because a comparison
 * on a missing attribute is false; `attribute_exists` states the intent. Without a condition,
 * `UpdateItem` creates the item it updates, which would bring back a session a sign-out deleted.
 */
export const REPLACE_CONDITION = 'attribute_exists(#pk) AND #version = :expectedVersion';

/** One DynamoDB call, bounded. The adapter takes it as a parameter so tests can run the real adapter. */
export type DynamoSend = (
  command: GetItemCommand | PutItemCommand | UpdateItemCommand | DeleteItemCommand
) => Promise<unknown>;

let cached: {region: string; client: DynamoDBClient} | undefined;

/**
 * The SDK client for a region, made once. It holds no session data, only a connection pool.
 *
 * @param region - The table's region.
 * @returns The client.
 */
function clientFor(region: string): DynamoDBClient {
  if (cached?.region !== region) cached = {region, client: new DynamoDBClient({region})};
  return cached.client;
}

/**
 * The production `send`: the SDK client, with every call aborted after the store bound.
 *
 * @param region - The table's region.
 * @returns A bounded send.
 */
export function boundedSend(region: string): DynamoSend {
  return async (command) => {
    const bound = deadline(STORE_CALL_TIMEOUT_MS);
    try {
      return await clientFor(region).send(command as GetItemCommand, {abortSignal: bound.signal});
    } finally {
      bound.clear();
    }
  };
}

/**
 * Turn an item into DynamoDB's attribute map.
 *
 * @param item - The session item.
 * @returns The attribute map.
 */
function marshal(item: SessionItem): Record<string, AttributeValue> {
  return {
    pk: {S: item.pk},
    idToken: {S: item.idToken},
    refreshToken: {S: item.refreshToken},
    tokenExpiresAt: {N: String(item.tokenExpiresAt)},
    sessionExpiresAt: {N: String(item.sessionExpiresAt)},
    expiresAt: {N: String(item.expiresAt)},
    version: {N: String(item.version)}
  };
}

/**
 * Turn DynamoDB's attribute map into an item, refusing one that is not a whole session.
 *
 * @param attributes - The attribute map.
 * @returns The item, or null when any attribute is missing or mistyped.
 */
function unmarshal(attributes: Record<string, AttributeValue> | undefined): SessionItem | null {
  if (!attributes) return null;
  const text = (name: string) => attributes[name]?.S;
  const number = (name: string) => (attributes[name]?.N === undefined ? undefined : Number(attributes[name].N));
  const pk = text('pk');
  const idToken = text('idToken');
  const refreshToken = text('refreshToken');
  const tokenExpiresAt = number('tokenExpiresAt');
  const sessionExpiresAt = number('sessionExpiresAt');
  const expiresAt = number('expiresAt');
  const version = number('version');
  if (
    pk === undefined ||
    idToken === undefined ||
    refreshToken === undefined ||
    tokenExpiresAt === undefined ||
    sessionExpiresAt === undefined ||
    expiresAt === undefined ||
    version === undefined
  ) {
    return null;
  }
  return {pk, idToken, refreshToken, tokenExpiresAt, sessionExpiresAt, expiresAt, version};
}

/**
 * The session store on a DynamoDB table.
 *
 * Every read is strongly consistent, because a refresh compares a version it read a moment ago.
 *
 * @param tableName - The table.
 * @param send - How each command reaches DynamoDB.
 * @returns The store.
 */
export function dynamoSessionStore(tableName: string, send: DynamoSend): SessionStore {
  return {
    async get(pk) {
      const result = (await send(
        new GetItemCommand({TableName: tableName, Key: {pk: {S: pk}}, ConsistentRead: true})
      )) as {Item?: Record<string, AttributeValue>};
      return unmarshal(result.Item);
    },
    async put(item) {
      await send(new PutItemCommand({TableName: tableName, Item: marshal(item)}));
    },
    async replaceTokens(pk, expectedVersion, next) {
      try {
        await send(
          new UpdateItemCommand({
            TableName: tableName,
            Key: {pk: {S: pk}},
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
              ':expectedVersion': {N: String(expectedVersion)},
              ':nextVersion': {N: String(expectedVersion + 1)}
            }
          })
        );
        return true;
      } catch (error) {
        if (error instanceof ConditionalCheckFailedException) return false;
        throw error;
      }
    },
    async delete(pk) {
      await send(new DeleteItemCommand({TableName: tableName, Key: {pk: {S: pk}}}));
    }
  };
}
