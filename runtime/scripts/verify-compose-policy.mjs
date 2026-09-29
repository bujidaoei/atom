import { execFileSync } from 'node:child_process';

const output = execFileSync(
  'docker',
  [
    'compose',
    '--env-file',
    'deploy/compose/.env.example',
    '-f',
    'deploy/compose/compose.yaml',
    'config',
    '--format',
    'json',
  ],
  { encoding: 'utf8' },
);
const compose = JSON.parse(output);
const networkNames = (serviceName) => Object.keys(compose.services[serviceName].networks ?? {});

for (const serviceName of ['platform-api', 'cloud-worker']) {
  if (!networkNames(serviceName).includes('egress')) {
    throw new Error(`${serviceName} requires the dedicated egress network`);
  }
}
for (const serviceName of ['sandbox-broker', 'postgres', 'redis']) {
  if (networkNames(serviceName).includes('egress')) {
    throw new Error(`${serviceName} must not have direct external egress`);
  }
}
if (compose.networks.egress.internal === true) throw new Error('egress network cannot be internal');
for (const networkName of ['application', 'data', 'sandbox-control']) {
  if (compose.networks[networkName].internal !== true) {
    throw new Error(`${networkName} network must remain internal`);
  }
}

const preview = compose.services.preview;
const previewPort = preview.ports?.find((port) => Number(port.target) === 3000);
if (previewPort?.host_ip !== '127.0.0.1') {
  throw new Error('preview must bind only to the host loopback interface');
}
const previewWorkspace = preview.volumes?.find((volume) => volume.target === '/srv/workspaces');
if (!previewWorkspace || previewWorkspace.type !== 'volume' || previewWorkspace.read_only !== true) {
  throw new Error('preview must read the durable workspace volume through a read-only mount');
}

console.log('Compose network policy verified');
