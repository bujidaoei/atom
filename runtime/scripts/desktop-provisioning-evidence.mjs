const KNOWN_ELECTRON_STDOUT = new Set(['[WARNING] Ignore caches that are heterogeneous']);

export function parseDesktopProvisioningEvidence(stdout) {
  if (typeof stdout !== 'string' || stdout.length > 16_384) {
    throw new Error('Desktop provisioning process output is invalid');
  }
  let evidence;
  for (const line of stdout
    .split(/\r?\n/u)
    .map((value) => value.trim())
    .filter(Boolean)) {
    if (KNOWN_ELECTRON_STDOUT.has(line)) continue;
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (cause) {
      throw new Error('Desktop provisioning process output is unrecognized', { cause });
    }
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      Array.isArray(parsed) ||
      Object.keys(parsed).sort().join(',') !== 'availableModelCount,model,operation,status' ||
      parsed.operation !== 'platform_config_provision' ||
      parsed.status !== 'ready' ||
      typeof parsed.model !== 'string' ||
      !parsed.model.trim() ||
      parsed.model.length > 256 ||
      !Number.isSafeInteger(parsed.availableModelCount) ||
      parsed.availableModelCount < 1 ||
      parsed.availableModelCount > 10_000
    ) {
      throw new Error('Desktop provisioning process evidence is invalid');
    }
    if (evidence) throw new Error('Desktop provisioning process evidence is duplicated');
    evidence = parsed;
  }
  if (!evidence) throw new Error('Desktop provisioning process evidence is missing');
  return Object.freeze({ ...evidence });
}
