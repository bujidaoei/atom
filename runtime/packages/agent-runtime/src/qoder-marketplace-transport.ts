const QODER_ORIGIN = 'https://qoder.com';
// Both vendor buckets are returned by the official catalog (verified 2026-09-23).
const QODER_PACKAGE_HOSTS = new Set([
  'qoder-skills.oss-accelerate.aliyuncs.com',
  'qoder-mind.oss-accelerate.aliyuncs.com',
]);
const MAX_CATALOG_BYTES = 2 * 1024 * 1024;

async function readBounded(response: Response, maxBytes: number): Promise<Uint8Array> {
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) throw new Error('Qoder response exceeds size policy');
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new Error('Qoder response exceeds size policy');
    }
    chunks.push(value);
  }
  const result = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

export async function qoderJson<T>(path: string, fetchImpl: typeof fetch): Promise<T> {
  const url = new URL(path, QODER_ORIGIN);
  if (url.origin !== QODER_ORIGIN) throw new Error('Invalid Qoder Marketplace path');
  const response = await fetchImpl(url, {
    method: 'GET',
    redirect: 'error',
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
    headers: { accept: 'application/json', 'user-agent': 'QoderWake-Skill-Marketplace/3' },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`Qoder Marketplace returned HTTP ${response.status}`);
  const bytes = await readBounded(response, MAX_CATALOG_BYTES);
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as T;
  } catch {
    throw new Error('Qoder Marketplace returned invalid JSON');
  }
}

export async function downloadQoderPackage(
  downloadUrlText: string,
  maxBytes: number,
  fetchImpl: typeof fetch,
): Promise<{ fileName: string; mediaType: 'application/zip' | 'application/gzip'; bytes: Uint8Array }> {
  const downloadUrl = new URL(downloadUrlText);
  if (
    downloadUrl.protocol !== 'https:' ||
    !QODER_PACKAGE_HOSTS.has(downloadUrl.hostname) ||
    downloadUrl.username ||
    downloadUrl.password ||
    downloadUrl.port
  ) {
    throw new Error('Qoder Marketplace download URL is not trusted');
  }
  const fileName = decodeURIComponent(downloadUrl.pathname.split('/').at(-1) ?? '');
  const mediaType = fileName.toLowerCase().endsWith('.zip')
    ? 'application/zip'
    : /\.(?:tgz|tar\.gz)$/iu.test(fileName)
      ? 'application/gzip'
      : undefined;
  if (!mediaType || !fileName || fileName.length > 255 || /[/\\\0]/u.test(fileName)) {
    throw new Error('Qoder Marketplace package name is invalid');
  }
  const response = await fetchImpl(downloadUrl, {
    method: 'GET',
    redirect: 'error',
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
    headers: { accept: 'application/zip,application/gzip', 'user-agent': 'QoderWake-Skill-Marketplace/3' },
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) throw new Error(`Qoder Marketplace package returned HTTP ${response.status}`);
  return { fileName, mediaType, bytes: await readBounded(response, maxBytes) };
}
