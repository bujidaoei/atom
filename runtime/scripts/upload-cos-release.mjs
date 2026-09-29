/* global fetch, AbortSignal */
import { createHash, createDecipheriv, privateDecrypt } from 'node:crypto';
import { Buffer } from 'node:buffer';
import { URL } from 'node:url';
import { createReadStream, existsSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { open } from 'node:fs/promises';
import { basename } from 'node:path';
import { parseArgs } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import { verifyPublicAsset } from '../packages/data-access/src/release-asset-verification.ts';

const { values } = parseArgs({
  options: {
    file: { type: 'string' },
    authorization: { type: 'string' },
    'private-key': { type: 'string' },
  },
});
if (!values.file || !values.authorization || !values['private-key'])
  throw new Error('File, authorization and private key required');
const envelope = JSON.parse(readFileSync(values.authorization, 'utf8'));
const secret = privateDecrypt(
  { key: readFileSync(values['private-key']), oaepHash: 'sha256' },
  Buffer.from(envelope.key, 'base64'),
);
const cipher = createDecipheriv('aes-256-gcm', secret, Buffer.from(envelope.iv, 'base64'));
cipher.setAuthTag(Buffer.from(envelope.tag, 'base64'));
const auth = JSON.parse(
  Buffer.concat([cipher.update(Buffer.from(envelope.ciphertext, 'base64')), cipher.final()]).toString('utf8'),
);
if (auth.expiresAt <= Date.now() || basename(values.file) !== auth.file)
  throw new Error('Expired authorization or wrong installer');
const digest = createHash('sha256');
let fileSize = 0;
for await (const chunk of createReadStream(values.file)) {
  fileSize += chunk.length;
  digest.update(chunk);
}
if (fileSize !== auth.size || digest.digest('hex') !== auth.sha256)
  throw new Error('Installer identity differs from reviewed authorization');
if (auth.verifiedExisting === true) {
  console.log(
    JSON.stringify({ phase: 'direct-cos-upload', reused: true, bytes: auth.size, publicUrl: auth.publicUrl }),
  );
} else {
  for (const url of [...auth.parts.map((part) => part.url), auth.completeUrl, auth.abortUrl]) {
    const destination = new URL(url);
    if (
      destination.protocol !== 'https:' ||
      destination.hostname !== new URL(auth.publicUrl).hostname ||
      !destination.hostname.endsWith('.myqcloud.com')
    )
      throw new Error('Invalid COS destination');
  }
  let nextOffset = 0;
  for (const [index, part] of auth.parts.entries()) {
    if (
      part.number !== index + 1 ||
      part.offset !== nextOffset ||
      !Number.isSafeInteger(part.size) ||
      part.size <= 0 ||
      part.size > 8 * 1024 * 1024
    )
      throw new Error('Invalid bounded part layout');
    nextOffset += part.size;
  }
  if (nextOffset !== fileSize) throw new Error('Incomplete part layout');
  const statePath = values.authorization + '.progress.json';
  const state = existsSync(statePath)
    ? JSON.parse(readFileSync(statePath, 'utf8'))
    : { uploadId: auth.uploadId, parts: {} };
  if (state.uploadId !== auth.uploadId) throw new Error('Upload progress belongs to another authorization');
  const started = Date.now();
  let next = 0;
  async function worker() {
    while (next < auth.parts.length) {
      const part = auth.parts[next++];
      if (state.parts[part.number]) continue;
      const bytes = Buffer.alloc(part.size);
      const handle = await open(values.file, 'r');
      try {
        let received = 0;
        while (received < bytes.length) {
          const { bytesRead } = await handle.read(
            bytes,
            received,
            bytes.length - received,
            part.offset + received,
          );
          if (!bytesRead) throw new Error('Installer truncated during upload');
          received += bytesRead;
        }
      } finally {
        await handle.close();
      }
      if (createHash('md5').update(bytes).digest('base64') !== part.md5)
        throw new Error('Part identity mismatch');
      let lastError;
      for (let attempt = 1; attempt <= 3; attempt++) {
        let reason = 'network';
        let retryable = true;
        const attemptStarted = Date.now();
        try {
          if (Date.now() >= auth.expiresAt) {
            reason = 'authorization-expired';
            retryable = false;
            throw new Error(reason);
          }
          const response = await fetch(part.url, {
            method: 'PUT',
            headers: { 'content-length': String(part.size), 'content-md5': part.md5 },
            body: bytes,
            redirect: 'error',
            signal: AbortSignal.timeout(180_000),
          });
          if (!response.ok) {
            reason = 'http-' + response.status;
            retryable = [408, 429, 500, 502, 503, 504].includes(response.status);
            await response.body?.cancel();
            throw new Error(reason);
          }
          const etag = response.headers.get('etag');
          await response.body?.cancel();
          if (!etag || !/^"?[a-fA-F0-9-]+"?$/.test(etag)) {
            reason = 'invalid-receipt';
            retryable = false;
            throw new Error(reason);
          }
          state.parts[part.number] = etag;
          writeFileSync(statePath + '.tmp', JSON.stringify(state));
          renameSync(statePath + '.tmp', statePath);
          console.log(
            JSON.stringify({
              phase: 'cos-part',
              part: part.number,
              parts: auth.parts.length,
              bytes: part.size,
              attempt,
              attemptSeconds: (Date.now() - attemptStarted) / 1000,
              elapsedSeconds: (Date.now() - started) / 1000,
            }),
          );
          lastError = undefined;
          break;
        } catch (error) {
          lastError = error;
          if (error?.name === 'TimeoutError') reason = 'timeout';
          const retryDelayMs =
            retryable && attempt < 3 ? 500 * 2 ** (attempt - 1) + Math.floor(Math.random() * 250) : 0;
          // Never log raw fetch errors: they may contain the signed upload URL.
          console.log(
            JSON.stringify({
              phase: 'cos-part-retry',
              part: part.number,
              attempt,
              reason,
              retryable,
              retryDelayMs,
              attemptSeconds: (Date.now() - attemptStarted) / 1000,
            }),
          );
          if (!retryable) break;
          if (retryDelayMs) await delay(retryDelayMs);
        }
      }
      if (lastError) throw new Error('Part ' + part.number + ' failed; completed parts retained for retry');
    }
  }
  const workers = await Promise.allSettled(Array.from({ length: 4 }, worker));
  if (workers.some((result) => result.status === 'rejected'))
    throw new Error('Multipart upload incomplete; reuse the same authorization to resume');
  const xml =
    '<CompleteMultipartUpload>' +
    auth.parts
      .map(
        (part) =>
          '<Part><PartNumber>' +
          part.number +
          '</PartNumber><ETag>' +
          state.parts[part.number] +
          '</ETag></Part>',
      )
      .join('') +
    '</CompleteMultipartUpload>';
  let completionStatus;
  for (let attempt = 1; attempt <= 3; attempt++) {
    let retryable = true;
    let reason = 'network';
    try {
      const completed = await fetch(auth.completeUrl, {
        method: 'POST',
        headers: {
          'content-type': 'application/xml',
          'x-cos-forbid-overwrite': 'true',
          'if-none-match': '*',
        },
        body: xml,
        redirect: 'error',
        signal: AbortSignal.timeout(120_000),
      });
      const body = await completed.text();
      if (!completed.ok || /<Error[>\s]/.test(body)) {
        reason = completed.ok ? 'cos-error-response' : 'http-' + completed.status;
        retryable = [408, 429, 500, 502, 503, 504].includes(completed.status);
        throw new Error(reason);
      }
      completionStatus = completed.status;
      break;
    } catch (error) {
      if (error?.name === 'TimeoutError') reason = 'timeout';
      console.log(JSON.stringify({ phase: 'cos-completion-recovery', attempt, reason }));
      // A lost response can leave a fully committed object and an invalid upload ID.
      // Only its actual public bytes can establish successful completion.
      try {
        await verifyPublicAsset(auth.publicUrl, auth.size, auth.sha256);
        completionStatus = 200;
        break;
      } catch {
        if (!retryable || attempt === 3)
          throw new Error('COS completion unverified; preserve authorization and installer for retry');
      }
      await delay(500 * 2 ** (attempt - 1));
    }
  }
  console.log(
    JSON.stringify({
      phase: 'direct-cos-upload',
      status: completionStatus,
      bytes: fileSize,
      elapsedSeconds: (Date.now() - started) / 1000,
      publicUrl: auth.publicUrl,
    }),
  );
}
