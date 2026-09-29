import { isIP } from 'node:net';
import { networkInterfaces } from 'node:os';
import { connect as connectTls } from 'node:tls';
import { URL } from 'node:url';
import { Agent, Dispatcher, getGlobalDispatcher, setGlobalDispatcher } from 'undici';

/**
 * Opt-in route for hosts whose system DNS/tunnel cannot complete gateway TLS.
 * The configured IP is only the TCP destination: SNI and certificate checking
 * still use the configured gateway hostname. Other origins retain their
 * existing dispatcher, including its proxy settings.
 */
export function configureGatewayLocalRoute(environment = process.env) {
  const connectIp = environment.TOKEN_V3_AI_GATEWAY_CONNECT_IP?.trim();
  const interfaceName = environment.TOKEN_V3_AI_GATEWAY_BIND_INTERFACE?.trim();
  if (!connectIp && !interfaceName) return false;
  if (!connectIp || !interfaceName || isIP(connectIp) !== 4) {
    throw new Error('Gateway local route requires an IPv4 connect IP and a network interface name');
  }

  const bindAddress = networkInterfaces()[interfaceName]?.find(
    (address) => address.family === 'IPv4' && !address.internal,
  )?.address;
  if (!bindAddress) throw new Error(`Gateway local route interface has no IPv4 address: ${interfaceName}`);

  const baseUrl = environment.TOKEN_V3_AI_GATEWAY_BASE_URL || environment.LITELLM_BASE_URL;
  if (!baseUrl) throw new Error('Gateway local route requires a configured gateway base URL');
  const gatewayUrl = new URL(baseUrl);
  if (gatewayUrl.protocol !== 'https:') throw new Error('Gateway local route requires an HTTPS gateway');
  const gatewayHostname = gatewayUrl.hostname;
  const previousDispatcher = getGlobalDispatcher();
  const gatewayDispatcher = new Agent({
    connect(options, callback) {
      const socket = connectTls({
        host: connectIp,
        port: Number(options.port) || 443,
        servername: gatewayHostname,
        localAddress: bindAddress,
        rejectUnauthorized: true,
      });
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        socket.off('error', finish);
        socket.setTimeout(0);
        callback(error ?? null, error ? undefined : socket);
      };
      socket.once('error', finish);
      socket.once('secureConnect', () => finish());
      socket.setTimeout(10_000, () => socket.destroy(new Error('Gateway TLS connection timed out')));
    },
  });

  class GatewayOnlyDispatcher extends Dispatcher {
    dispatch(options, handler) {
      const origin = new URL(String(options.origin));
      return origin.protocol === 'https:' && origin.hostname === gatewayHostname
        ? gatewayDispatcher.dispatch(options, handler)
        : previousDispatcher.dispatch(options, handler);
    }

    async close() {
      await Promise.all([gatewayDispatcher.close(), previousDispatcher.close()]);
    }

    async destroy(error) {
      await Promise.all([gatewayDispatcher.destroy(error), previousDispatcher.destroy(error)]);
    }
  }

  setGlobalDispatcher(new GatewayOnlyDispatcher());
  return true;
}
