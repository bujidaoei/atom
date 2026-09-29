import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';

import {
  ProtectedConfigurationSchema,
  inspectProtectedConfiguration,
  type SecretReference,
} from '../src/v3-configuration.ts';
import { maskAiGatewayVirtualKey } from '../src/ai-gateway-virtual-key.ts';
import { V3RunSchema } from '../src/v3.ts';

const run = {
  id: '11111111-1111-4111-8111-111111111111',
  taskId: '22222222-2222-4222-8222-222222222222',
  attempt: 1,
  executionTarget: 'cloud',
  provider: 'enterprise-gateway',
  model: 'gateway-model-a',
  providerCorrelationId: null,
  status: 'queued',
  usage: null,
  failureCategory: null,
};

const secretReference = (suffix: string) =>
  `secret://workspace/11111111-1111-4111-8111-111111111111/${suffix}` as SecretReference;

describe('V4 provider-neutral product contracts', () => {
  it('accepts new gateway and historical provider identities without accepting URLs or labels', () => {
    expect(Value.Check(V3RunSchema, run)).toBe(true);
    expect(Value.Check(V3RunSchema, { ...run, provider: 'deepseek' })).toBe(true);
    expect(Value.Check(V3RunSchema, { ...run, provider: 'https://provider.example.com' })).toBe(false);
    expect(Value.Check(V3RunSchema, { ...run, provider: 'Enterprise Gateway' })).toBe(false);
  });

  it('defines server-managed gateway status without a client credential reference', async () => {
    const configuration = {
      aiGateway: { model: 'gateway-model-a' },
      cos: {
        endpoint: 'https://cos.example.com',
        bucket: 'bucket',
        region: 'region',
        prefix: 'prefix',
        accessKeyRef: secretReference('22222222-2222-4222-8222-222222222222'),
        secretKeyRef: secretReference('33333333-3333-4333-8333-333333333333'),
      },
      feishu: {
        appIdRef: secretReference('44444444-4444-4444-8444-444444444444'),
        appSecretRef: secretReference('55555555-5555-4555-8555-555555555555'),
      },
    };
    expect(Value.Check(ProtectedConfigurationSchema, configuration)).toBe(true);
    expect(JSON.stringify(ProtectedConfigurationSchema)).not.toContain('deepseek');
    expect(JSON.stringify(ProtectedConfigurationSchema)).not.toContain('masterKey');
    expect(JSON.stringify(ProtectedConfigurationSchema)).not.toContain('apiKeyRef');

    await expect(
      inspectProtectedConfiguration(configuration, {
        status: async () => ({ configured: true, hint: maskAiGatewayVirtualKey('sk-test-virtual-key') }),
      }),
    ).resolves.toMatchObject({
      ready: true,
      aiGateway: { configured: true, model: 'gateway-model-a', serverManaged: true },
      issues: [],
    });
  });

  it('reports an absent model without inventing a provider fallback', async () => {
    const configuration = {
      aiGateway: { model: ' ' },
      cos: {
        endpoint: 'https://cos.example.com',
        bucket: 'bucket',
        region: 'region',
        prefix: 'prefix',
        accessKeyRef: secretReference('22222222-2222-4222-8222-222222222222'),
        secretKeyRef: secretReference('33333333-3333-4333-8333-333333333333'),
      },
      feishu: {
        appIdRef: secretReference('44444444-4444-4444-8444-444444444444'),
        appSecretRef: secretReference('55555555-5555-4555-8555-555555555555'),
      },
    };

    await expect(
      inspectProtectedConfiguration(configuration, {
        status: async () => ({ configured: true }),
      }),
    ).resolves.toMatchObject({ ready: false, issues: ['ai_gateway_model_missing'] });
  });
});
