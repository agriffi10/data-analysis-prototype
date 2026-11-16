import type {IncomingMessage, ServerResponse} from 'node:http';
import type {Duplex} from 'node:stream';

/** The guard ahead of Next's standalone server: `server-guard.cjs`, typed for its unit test. */
export const SECURITY_HEADERS: Readonly<Record<string, string>>;
export const LOCKDOWN_POLICY: string;
export function refusal(target: string | undefined): 'malformed-escape' | 'not-a-path' | null;
export function refuse(req: IncomingMessage, res: ServerResponse, reason: 'malformed-escape' | 'not-a-path'): void;
export function refuseUpgrade(req: IncomingMessage, socket: Duplex): void;
export function install(): void;
