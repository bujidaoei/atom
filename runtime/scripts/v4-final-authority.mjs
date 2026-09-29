import { Buffer } from 'node:buffer';
import { spawnSync } from 'node:child_process';
import { createPrivateKey, createPublicKey, sign as cryptoSign, verify as cryptoVerify } from 'node:crypto';

const revisionPattern = /^[0-9a-f]{40}$/u;
const sha256Pattern = /^[0-9a-f]{64}$/u;
const base64Pattern = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;
const receiptKinds = new Set(['prepush', 'windows-installed', 'production']);

function receiptSafeChildEnvironment() {
  const environment = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (/^WORKDUDE_V4_.*RECEIPT_PRIVATE_KEY_BASE64$/u.test(name)) delete environment[name];
  }
  return environment;
}

function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(value).sort();
  return keys.length === expected.length && keys.every((key, index) => key === expected[index]);
}

function decodeKey(value, kind) {
  if (typeof value !== 'string' || value.length === 0 || !base64Pattern.test(value)) {
    throw new Error(`V4 gate receipt ${kind} key is invalid`);
  }
  const decoded = Buffer.from(value, 'base64');
  if (decoded.length === 0 || decoded.toString('base64') !== value) {
    throw new Error(`V4 gate receipt ${kind} key is invalid`);
  }
  const key = kind === 'private' ? createPrivateKey(decoded) : createPublicKey(decoded);
  if (key.asymmetricKeyType !== 'ed25519') {
    throw new Error(`V4 gate receipt ${kind} key must be Ed25519`);
  }
  return key;
}

function normalizePayload(payload) {
  const keys = [
    'arch',
    'gates',
    'issuedAt',
    'kind',
    'manifestSha256',
    'platform',
    'revision',
    'rollbackRevision',
    'schemaVersion',
  ];
  if (!exactKeys(payload, keys)) throw new Error('V4 gate receipt payload is malformed');
  if (payload.schemaVersion !== 1 || !receiptKinds.has(payload.kind)) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (!revisionPattern.test(payload.revision) || !sha256Pattern.test(payload.manifestSha256)) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (
    !Array.isArray(payload.gates) ||
    payload.gates.length === 0 ||
    payload.gates.some((gate) => typeof gate !== 'string' || gate.length === 0) ||
    new Set(payload.gates).size !== payload.gates.length
  ) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (typeof payload.platform !== 'string' || !payload.platform) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (typeof payload.arch !== 'string' || !payload.arch) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (
    typeof payload.issuedAt !== 'string' ||
    !Number.isFinite(Date.parse(payload.issuedAt)) ||
    new Date(payload.issuedAt).toISOString() !== payload.issuedAt
  ) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  if (payload.kind === 'production') {
    if (
      !revisionPattern.test(payload.rollbackRevision ?? '') ||
      payload.rollbackRevision === payload.revision
    ) {
      throw new Error('V4 gate receipt payload is malformed');
    }
  } else if (payload.rollbackRevision !== null) {
    throw new Error('V4 gate receipt payload is malformed');
  }
  return {
    schemaVersion: 1,
    kind: payload.kind,
    revision: payload.revision,
    rollbackRevision: payload.rollbackRevision,
    gates: [...payload.gates],
    manifestSha256: payload.manifestSha256,
    platform: payload.platform,
    arch: payload.arch,
    issuedAt: payload.issuedAt,
  };
}

function payloadBytes(payload) {
  return Buffer.from(JSON.stringify(payload), 'utf8');
}

export function signGateReceipt({ payload, privateKeyBase64 }) {
  const normalized = normalizePayload(payload);
  const privateKey = decodeKey(privateKeyBase64, 'private');
  return {
    payload: normalized,
    signature: cryptoSign(null, payloadBytes(normalized), privateKey).toString('base64'),
  };
}

export function verifyGateReceipt({ receipt, expected, publicKeyBase64 }) {
  const kind = expected?.kind ?? 'unknown';
  let payload;
  let publicKey;
  if (!exactKeys(receipt, ['payload', 'signature'])) {
    return [`${kind} gate receipt is malformed`];
  }
  try {
    payload = normalizePayload(receipt.payload);
    publicKey = decodeKey(publicKeyBase64, 'public');
  } catch {
    return [`${kind} gate receipt is malformed`];
  }
  if (
    typeof receipt.signature !== 'string' ||
    !base64Pattern.test(receipt.signature) ||
    !cryptoVerify(null, payloadBytes(payload), publicKey, Buffer.from(receipt.signature, 'base64'))
  ) {
    return [`${kind} gate receipt signature is invalid`];
  }

  const problems = [];
  if (payload.kind !== expected.kind) problems.push(`${kind} gate receipt kind does not match`);
  if (payload.revision !== expected.revision) {
    problems.push(`${kind} gate receipt revision does not match WORKDUDE_V4_FINAL_REVISION`);
  }
  if (payload.rollbackRevision !== (expected.rollbackRevision ?? null)) {
    problems.push(`${kind} gate receipt rollback revision does not match`);
  }
  if (
    payload.gates.length !== expected.gates.length ||
    payload.gates.some((gate, index) => gate !== expected.gates[index])
  ) {
    problems.push(`${kind} gate receipt gate set does not match`);
  }
  if (payload.manifestSha256 !== expected.manifestSha256) {
    problems.push(`${kind} gate receipt manifest does not match`);
  }
  if (expected.platform && payload.platform !== expected.platform) {
    problems.push(`${kind} gate receipt platform does not match`);
  }
  if (expected.arch && payload.arch !== expected.arch) {
    problems.push(`${kind} gate receipt architecture does not match`);
  }
  return problems;
}

export function inspectGitHubReleaseRun({ runId, expectedRevision, cwd, spawn = spawnSync }) {
  if (!/^[1-9]\d*$/u.test(runId ?? '')) {
    return ['WORKDUDE_V4_RELEASE_RUN_ID must be a positive integer GitHub Actions run ID'];
  }

  const result = spawn(
    'gh',
    ['run', 'view', runId, '--json', 'workflowName,event,headSha,headBranch,status,conclusion'],
    {
      cwd,
      encoding: 'utf8',
      windowsHide: true,
      env: receiptSafeChildEnvironment(),
    },
  );
  if (result.error || result.status !== 0) {
    return ['GitHub release workflow identity is unavailable'];
  }

  let metadata;
  try {
    metadata = JSON.parse(String(result.stdout));
  } catch {
    return ['GitHub release workflow identity is malformed'];
  }
  if (!metadata || typeof metadata !== 'object') {
    return ['GitHub release workflow identity is malformed'];
  }
  if (metadata.workflowName !== 'Release Desktop') {
    return ['GitHub Actions run is not the Release Desktop workflow'];
  }
  if (metadata.event !== 'push') {
    return ['GitHub release workflow was not triggered by a source tag push'];
  }
  if (typeof metadata.headBranch !== 'string' || !metadata.headBranch.startsWith('desktop-v')) {
    return ['GitHub release workflow was not triggered by a Desktop tag'];
  }
  if (metadata.headSha !== expectedRevision) {
    return ['GitHub release workflow revision does not match WORKDUDE_V4_FINAL_REVISION'];
  }
  if (metadata.status !== 'completed' || metadata.conclusion !== 'success') {
    return ['GitHub release workflow did not complete successfully'];
  }
  return [];
}
