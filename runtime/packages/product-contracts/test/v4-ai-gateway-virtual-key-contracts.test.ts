import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';

import { V3AiGatewayVirtualKeyInputSchema, V3AiGatewayVirtualKeyStatusSchema } from '../src/v3.ts';
import { maskAiGatewayVirtualKey } from '../src/ai-gateway-virtual-key.ts';

describe('AI gateway virtual-key contracts', () => {
  it('accepts opaque non-whitespace credentials while exposing only a masked status', () => {
    expect(Value.Check(V3AiGatewayVirtualKeyInputSchema, { virtualKey: 'sk-test-virtual-key' })).toBe(true);
    expect(Value.Check(V3AiGatewayVirtualKeyInputSchema, { virtualKey: 'sk-test virtual-key' })).toBe(false);
    expect(Value.Check(V3AiGatewayVirtualKeyInputSchema, { virtualKey: 'sk-test-virtual-key\n' })).toBe(
      false,
    );
    expect(Value.Check(V3AiGatewayVirtualKeyInputSchema, { virtualKey: `sk-test-virtual-key\u0085` })).toBe(
      false,
    );
    expect(Value.Check(V3AiGatewayVirtualKeyStatusSchema, { configured: false })).toBe(true);
    expect(Value.Check(V3AiGatewayVirtualKeyStatusSchema, { configured: false, hint: 'sk****ey' })).toBe(
      true,
    );
    expect(Value.Check(V3AiGatewayVirtualKeyStatusSchema, { configured: false, hint: 'sk-secret-key' })).toBe(
      false,
    );
    expect(
      Value.Check(V3AiGatewayVirtualKeyStatusSchema, {
        configured: true,
        hint: maskAiGatewayVirtualKey('sk-test-virtual-key'),
      }),
    ).toBe(true);
    expect(Value.Check(V3AiGatewayVirtualKeyStatusSchema, { configured: true })).toBe(false);
    expect(
      Value.Check(V3AiGatewayVirtualKeyStatusSchema, { configured: true, hint: 'sk-test-virtual-key' }),
    ).toBe(false);
  });
});
