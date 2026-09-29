import { fileURLToPath } from 'node:url';

import {
  loadV4ServerConfiguration,
  type V4AiGatewayServerConfiguration,
} from '../packages/product-contracts/src/server-configuration.ts';
import { validateEnterpriseAiGatewayModel } from '../packages/agent-runtime/src/enterprise-ai-gateway.ts';

export interface AiGatewayProbeResult {
  liveness: 'ready' | 'unavailable';
  livenessStatus: number;
  unauthenticatedModelsStatus: number;
  authenticatedModelsStatus: 200;
  model: string;
  modelAvailable: true;
  availableModelCount: number;
  checkedAt: string;
}

export async function probeAiGateway(
  configuration: V4AiGatewayServerConfiguration,
  fetchImplementation: typeof fetch = fetch,
): Promise<AiGatewayProbeResult> {
  // The configured HTTPS base URL is the product boundary. Do not probe or
  // enforce an unrelated HTTP listener on the gateway host: WorkDude is a
  // client of the gateway, not its network administrator.
  const readiness = await validateEnterpriseAiGatewayModel(configuration, fetchImplementation);
  return {
    liveness: 'ready',
    livenessStatus: readiness.livenessStatus,
    unauthenticatedModelsStatus: readiness.unauthenticatedModelsStatus,
    authenticatedModelsStatus: 200,
    model: readiness.model,
    modelAvailable: true,
    availableModelCount: readiness.availableModelCount,
    checkedAt: readiness.checkedAt,
  };
}

async function main(): Promise<void> {
  // This probe only exercises the gateway boundary; it must not require or
  // load Feishu application credentials (or the dedicated Feishu auth key).
  const configuration = loadV4ServerConfiguration(process.env, { requireFeishu: false }).aiGateway;
  const result = await probeAiGateway(configuration);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main();
}
