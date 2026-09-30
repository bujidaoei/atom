import { createHash, timingSafeEqual } from 'node:crypto';
import { isIP } from 'node:net';

export interface RuntimeConfig {
  environment: 'development' | 'test' | 'production';
  port: number;
  host: string;
  sandboxMode: 'local' | 'broker';
  brokerOrigin?: string;
  executionOrigin?: string;
  authorize(header: string | undefined): boolean;
}

/** Errors name fields only: never include caller-supplied secret values. */
export function loadRuntimeConfig(env: NodeJS.ProcessEnv): RuntimeConfig {
  const environment = env.ATOM_ENVIRONMENT ?? 'development';
  if (!['development', 'test', 'production'].includes(environment)) throw new Error('Invalid ATOM_ENVIRONMENT');
  const token = env.ATOM_RUNTIME_TOKEN ?? '';
  if (!/^[\x21-\x7e]{32,512}$/.test(token) || /change-me|dev-secret/i.test(token)) {
    throw new Error('ATOM_RUNTIME_TOKEN requires a generated 32–512 character nonspace ASCII secret');
  }
  const portText = env.ATOM_RUNTIME_PORT ?? '8721';
  const port = Number(portText);
  if (!/^\d+$/.test(portText) || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid ATOM_RUNTIME_PORT');
  const host = env.ATOM_RUNTIME_HOST ?? '127.0.0.1';
  if (!isIP(host)) throw new Error('ATOM_RUNTIME_HOST must be an IP literal');
  const loopback = host === '::1' || (isIP(host) === 4 && host.split('.')[0] === '127');
  if (environment === 'production' && !loopback) throw new Error('Production runtime listener must bind a loopback address');
  const sandboxMode = env.ATOM_SANDBOX_MODE ?? (environment === 'production' ? 'broker' : 'local');
  if (!['local', 'broker'].includes(sandboxMode) || (environment === 'production' && sandboxMode !== 'broker')) {
    throw new Error('Invalid ATOM_SANDBOX_MODE');
  }
  function origin(name: string): string {
    const value = env[name] ?? '';
    try {
      const url = new URL(value);
      if (/[\\?#\s]/.test(value) || /[^\x21-\x7e]/.test(value) || url.username || url.password
          || url.pathname !== '/' || url.port === '0'
          || (url.protocol !== 'https:' && !/^http:\/\/(?:127\.0\.0\.1|\[::1\])(?::[1-9][0-9]{0,4})?\/?$/.test(value))) throw new Error();
      return url.origin;
    } catch { throw new Error(`Invalid ${name}`); }
  }
  const brokerOrigin = sandboxMode === 'broker' ? origin('ATOM_BROKER_ORIGIN') : undefined;
  const executionOrigin = sandboxMode === 'broker' ? origin('ATOM_EXECUTION_ORIGIN') : undefined;
  const digest = createHash('sha256').update(`Bearer ${token}`).digest();
  return Object.freeze({
    environment: environment as RuntimeConfig['environment'], port, host,
    sandboxMode: sandboxMode as RuntimeConfig['sandboxMode'], brokerOrigin, executionOrigin,
    authorize(header: string | undefined): boolean {
      if (!header) return false;
      return timingSafeEqual(digest, createHash('sha256').update(header).digest());
    },
  });
}
