import { Value } from 'typebox/value';
import { describe, expect, it } from 'vitest';

import {
  V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID,
  V3_BROWSER_CONNECTOR_CHROME_EXTENSION_ID,
  V3BrowserConnectorFallbackSchema,
  V3BrowserConnectorLiveSchema,
  V3BrowserConnectorStateSchema,
  V3UpdateBrowserConnectorEnablementSchema,
  composeV3BrowserConnectorState,
  createV3BrowserConnectorWebNoopState,
  type V3BrowserConnectorEnablement,
} from '../src/v3.ts';

const observedAt = '2026-08-28T00:00:00.000Z';
const enablement: V3BrowserConnectorEnablement = {
  wakerId: '11111111-1111-4111-8111-111111111111',
  enabled: false,
  version: 1,
  updatedAt: observedAt,
};

describe('V3 Browser Connector contract', () => {
  it('keeps the clean-room candidate package distinct from official Store and profile fallback provenance', () => {
    const candidate = {
      status: 'available' as const,
      displayPath: 'C:\\Program Files\\QoderWake\\resources\\browser-extension',
      provenance: {
        source: 'candidate_manual_package' as const,
        extensionId: V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID,
        version: '0.1.0',
        manifestSha256: 'b'.repeat(64),
        observedAt,
      },
    };
    expect(Value.Check(V3BrowserConnectorFallbackSchema, candidate)).toBe(true);
    expect(
      Value.Check(V3BrowserConnectorLiveSchema, {
        connectionStatus: 'connected',
        ready: true,
        relayRunning: true,
        relayEnabled: true,
        protocolFamily: 'v2',
        provenance: {
          source: 'candidate_manual_package',
          extensionId: V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID,
          version: '0.1.0',
          observedAt,
        },
      }),
    ).toBe(true);
    expect(V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID).not.toBe(V3_BROWSER_CONNECTOR_CHROME_EXTENSION_ID);
  });

  it('keeps active 1.6.0 and fallback 1.5.0 source-qualified in four bounded layers', () => {
    const fallback = {
      status: 'available' as const,
      displayPath: 'C:\\Users\\owner\\.qoderwake-cn\\data\\browser-connector\\chrome-extension',
      provenance: {
        source: 'manual_fallback' as const,
        version: '1.5.0',
        manifestSha256: 'a'.repeat(64),
        observedAt,
      },
    };
    const live = {
      connectionStatus: 'connected' as const,
      ready: true,
      relayRunning: true as const,
      relayEnabled: true as const,
      protocolFamily: 'v2' as const,
      provenance: {
        source: 'chrome_web_store' as const,
        extensionId: V3_BROWSER_CONNECTOR_CHROME_EXTENSION_ID,
        version: '1.6.0',
        observedAt,
      },
    };

    expect(Value.Check(V3BrowserConnectorFallbackSchema, fallback)).toBe(true);
    expect(Value.Check(V3BrowserConnectorLiveSchema, live)).toBe(true);
    expect(
      Value.Check(V3BrowserConnectorFallbackSchema, {
        ...fallback,
        provenance: { ...live.provenance, version: '1.5.0' },
      }),
    ).toBe(false);

    const disabled = composeV3BrowserConnectorState({
      fallback,
      live,
      grant: { status: 'none' },
      enablement,
    });
    expect(disabled).toMatchObject({
      browserContextToolAvailable: false,
      browserPageToolReady: false,
      enablement: { enabled: false },
    });

    const enabled = composeV3BrowserConnectorState({
      fallback,
      live,
      grant: { status: 'none' },
      enablement: { ...enablement, enabled: true, version: 2 },
    });
    expect(enabled).toMatchObject({
      browserContextToolAvailable: true,
      browserPageToolReady: false,
    });
    expect(
      composeV3BrowserConnectorState({
        ...enabled,
        grant: { status: 'authorized-current-tab' },
      }),
    ).toMatchObject({ browserContextToolAvailable: true, browserPageToolReady: true });
    expect(Value.Check(V3BrowserConnectorStateSchema, enabled)).toBe(true);
  });

  it('rejects raw inventory metadata and keeps Web without native capability a no-op', () => {
    const state = createV3BrowserConnectorWebNoopState({ ...enablement, enabled: true });
    expect(state).toMatchObject({
      fallback: { status: 'unknown', displayPath: null, provenance: null },
      live: {
        connectionStatus: 'unavailable',
        ready: false,
        relayRunning: false,
        relayEnabled: false,
        protocolFamily: null,
        provenance: null,
      },
      grant: { status: 'none' },
      enablement: { enabled: true },
      browserContextToolAvailable: false,
      browserPageToolReady: false,
    });
    expect(Value.Check(V3BrowserConnectorStateSchema, state)).toBe(true);

    for (const forbidden of ['tabId', 'clientId', 'windowId', 'title', 'url', 'query', 'count']) {
      expect(Value.Check(V3BrowserConnectorStateSchema, { ...state, [forbidden]: 'forbidden' })).toBe(false);
      for (const layer of ['fallback', 'live', 'grant', 'enablement'] as const) {
        expect(
          Value.Check(V3BrowserConnectorStateSchema, {
            ...state,
            [layer]: { ...state[layer], [forbidden]: 'forbidden' },
          }),
        ).toBe(false);
      }
    }
    expect(JSON.stringify(state)).not.toMatch(/tabId|clientId|windowId|title|url|query|count/u);
  });

  it('requires a bounded expected version for independent per-Waker enablement mutation', () => {
    expect(Value.Check(V3UpdateBrowserConnectorEnablementSchema, { enabled: true, expectedVersion: 1 })).toBe(
      true,
    );
    expect(
      Value.Check(V3UpdateBrowserConnectorEnablementSchema, {
        enabled: true,
        expectedVersion: 1,
        connectorId: 'custom-mcp',
      }),
    ).toBe(false);
    expect(Value.Check(V3UpdateBrowserConnectorEnablementSchema, { enabled: true, expectedVersion: 0 })).toBe(
      false,
    );
  });
});
