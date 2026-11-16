#!/usr/bin/env node
/**
 * The exchanger: stands in for the Next.js server's task role and calls `CreateTokenWithIAM`.
 *
 * It runs in Node with `@aws-sdk/client-sso-oidc` because that is the shape Phase 5 ships, and the
 * question several checks ask is about principals: the role that exchanges is not the role that
 * assumes. It records who called, against which application and account, and what came back, then
 * keeps the Identity Center tokens and the identity context for `phase0.py` to read.
 *
 * The context is read from `awsAdditionalDetails.identityContext` and, independently, from the
 * Identity Center ID token's `sts:identity_context` claim; the two are compared, and either one is
 * enough, so an SDK that drops the field cannot silently lose the context.
 *
 * Usage (credentials come from AWS_PROFILE, region from AWS_REGION):
 *   node exchange.mjs jwt     --from alice   --out alice-1 --label C1.exchange
 *   node exchange.mjs refresh --from alice-1 --out alice-1r --label C4.refresh.before
 *   Add --app-arn <arn> to use an application other than IDC_APPLICATION_ARN.
 */
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { Evidence, decodeJwt, errorOutcome, fingerprint, loggableClaims, readSecret, requireEnv, writeSecret } from './evidence.mjs';

export const JWT_BEARER = 'urn:ietf:params:oauth:grant-type:jwt-bearer';

/**
 * The account an Identity Center application ARN belongs to.
 * @param {string} arn Such as `arn:aws:sso::<account>:application/ssoins-.../apl-...`.
 * @returns {string | null} The account id, or null when the ARN does not have that shape.
 */
export function applicationAccount(arn) {
  const match = /^arn:aws[a-z-]*:sso::(\d{12}):application\//.exec(arn);
  return match ? match[1] : null;
}

/**
 * Exchange an assertion, or refresh, and record everything telling about the result.
 * @param {object} args
 * @param {{send: (cmd: unknown) => Promise<any>}} args.oidc An SSO-OIDC client.
 * @param {{send: (cmd: unknown) => Promise<any>}} args.sts An STS client on the same credentials.
 * @param {{CreateTokenWithIAMCommand: new (input: object) => unknown, GetCallerIdentityCommand: new (input: object) => unknown}} args.commands The SDK command classes.
 * @param {Evidence} args.evidence The evidence log.
 * @param {'jwt' | 'refresh'} args.mode Which grant.
 * @param {string} args.appArn The application's ARN, the `clientId`.
 * @param {string} args.credential The Cognito ID token for `jwt`, the Identity Center refresh token for `refresh`.
 * @param {string} args.label The evidence label.
 * @returns {Promise<Record<string, unknown> | null>} The tokens to keep, or null when the call was refused.
 */
export async function runExchange({ oidc, sts, commands, evidence, mode, appArn, credential, label }) {
  evidence.addSecrets(credential);
  let caller;
  try {
    caller = await sts.send(new commands.GetCallerIdentityCommand({}));
  } catch (err) {
    const outcome = errorOutcome(err);
    evidence.record(`${label}.caller`, outcome);
    evidence.record(label, { ...outcome, data: { ...outcome.data, mode, appArn, appAccount: applicationAccount(appArn), caller: null } });
    return null;
  }
  const callerData = { account: caller.Account, arn: caller.Arn };
  evidence.record(`${label}.caller`, { ok: true, data: callerData });

  const input =
    mode === 'jwt'
      ? { clientId: appArn, grantType: JWT_BEARER, assertion: credential }
      : { clientId: appArn, grantType: 'refresh_token', refreshToken: credential };
  const base = { mode, appArn, appAccount: applicationAccount(appArn), caller: callerData };
  let res;
  try {
    res = await oidc.send(new commands.CreateTokenWithIAMCommand(input));
  } catch (err) {
    const outcome = errorOutcome(err);
    evidence.record(label, { ...outcome, data: { ...outcome.data, ...base } });
    return null;
  }

  const claims = res.idToken ? decodeJwt(res.idToken) : {};
  const fromField = res.awsAdditionalDetails?.identityContext ?? null;
  const fromClaim = typeof claims['sts:identity_context'] === 'string' ? claims['sts:identity_context'] : null;
  const context = fromField ?? fromClaim;
  evidence.addSecrets(res.accessToken, res.refreshToken, res.idToken, context ?? undefined);
  evidence.record(label, {
    ok: true,
    data: {
      ...base,
      scope: res.scope ?? null,
      expiresIn: res.expiresIn ?? null,
      tokenType: res.tokenType ?? null,
      issuedRefreshToken: Boolean(res.refreshToken),
      refreshTokenRotated: mode === 'refresh' && res.refreshToken ? res.refreshToken !== credential : null,
      context: {
        present: context !== null,
        fromField: fromField !== null,
        fromClaim: fromClaim !== null,
        fieldMatchesClaim: fromField !== null && fromClaim !== null ? fromField === fromClaim : null,
        fingerprint: fingerprint(context),
      },
      idTokenClaims: loggableClaims(claims),
    },
  });
  return {
    identityContext: context,
    refreshToken: res.refreshToken ?? (mode === 'refresh' ? credential : null),
    accessToken: res.accessToken ?? null,
    idToken: res.idToken ?? null,
    contextExp: typeof claims.exp === 'number' ? claims.exp : null,
    identityStoreUserId: typeof claims.sub === 'string' ? claims.sub : null,
    appArn,
    mintedAt: new Date().toISOString(),
  };
}

/**
 * Parse the command line, build real SDK clients and run one exchange.
 * @returns {Promise<void>}
 */
async function main() {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    options: { from: { type: 'string' }, out: { type: 'string' }, label: { type: 'string' }, 'app-arn': { type: 'string' } },
  });
  const [mode] = positionals;
  if ((mode !== 'jwt' && mode !== 'refresh') || !values.from || !values.out || !values.label) {
    process.stderr.write('usage: node exchange.mjs jwt|refresh --from <name> --out <name> --label <label> [--app-arn <arn>]\n');
    process.exit(2);
  }
  const appArn = values['app-arn'] ?? requireEnv('IDC_APPLICATION_ARN');
  const credential =
    mode === 'jwt' ? readSecret(`cognito-${values.from}.json`).idToken : readSecret(`idc-${values.from}.json`).refreshToken;
  if (!credential) throw new Error(`no ${mode === 'jwt' ? 'Cognito ID token' : 'Identity Center refresh token'} kept under ${values.from}`);
  const { SSOOIDCClient, CreateTokenWithIAMCommand } = await import('@aws-sdk/client-sso-oidc');
  const { STSClient, GetCallerIdentityCommand } = await import('@aws-sdk/client-sts');
  const region = requireEnv('AWS_REGION');
  const kept = await runExchange({
    oidc: new SSOOIDCClient({ region }),
    sts: new STSClient({ region }),
    commands: { CreateTokenWithIAMCommand, GetCallerIdentityCommand },
    evidence: new Evidence(requireEnv('PHASE0_EVIDENCE')),
    mode,
    appArn,
    credential,
    label: values.label,
  });
  if (kept === null) {
    process.exitCode = 1;
    return;
  }
  writeSecret(`idc-${values.out}.json`, kept);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) await main();
