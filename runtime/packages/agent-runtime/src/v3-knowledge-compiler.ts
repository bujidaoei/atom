import { extname } from 'node:path';
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';

import { OfficeParser, type SupportedFileType } from 'officeparser';
import { WasmDocument } from 'office-oxide-wasm/bundler';
import { createWorker } from 'tesseract.js';
import { parseKnowledgeEmail } from '../../data-access/src/v3/knowledge-email.ts';

const DEFAULT_MAX_SOURCE_BYTES = 10 * 1024 * 1024;
const MAX_REDIRECTS = 4;

export interface V3KnowledgeSourceFetchOptions {
  fetch?: typeof fetch;
  resolveHost?: (hostname: string) => Promise<string[]>;
  signal?: AbortSignal;
  timeoutMs?: number;
  maxBytes?: number;
}

function privateIpv4(address: string): boolean {
  const octets = address.split('.').map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return true;
  }
  const [a, b] = octets as [number, number, number, number];
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19)) ||
    a >= 224
  );
}

function privateAddress(address: string): boolean {
  const normalized = address.toLowerCase().split('%')[0]!;
  if (isIP(normalized) === 4) return privateIpv4(normalized);
  if (isIP(normalized) !== 6) return true;
  if (normalized.startsWith('::ffff:')) return privateIpv4(normalized.slice(7));
  return (
    normalized === '::' ||
    normalized === '::1' ||
    normalized.startsWith('fc') ||
    normalized.startsWith('fd') ||
    /^fe[89ab]/u.test(normalized)
  );
}

async function defaultResolveHost(hostname: string): Promise<string[]> {
  return (await lookup(hostname, { all: true, verbatim: true })).map(({ address }) => address);
}

async function assertPublicUrl(
  value: string,
  resolveHost: (hostname: string) => Promise<string[]>,
): Promise<URL> {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port) {
    throw new Error('Knowledge source must be a credential-free HTTPS URL on the default port');
  }
  const hostname = url.hostname.toLowerCase();
  if (
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    hostname.endsWith('.local') ||
    hostname.endsWith('.internal')
  ) {
    throw new Error('Knowledge source host is not public');
  }
  const addresses = isIP(hostname) ? [hostname] : await resolveHost(hostname);
  if (!addresses.length || addresses.some(privateAddress)) {
    throw new Error('Knowledge source resolved to a non-public address');
  }
  return url;
}

async function readBounded(response: Response, maxBytes: number): Promise<Uint8Array> {
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new Error(`Knowledge source exceeds the ${maxBytes} byte limit`);
  }
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
      throw new Error(`Knowledge source exceeds the ${maxBytes} byte limit`);
    }
    chunks.push(value);
  }
  const output = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

export async function fetchPublicKnowledgeSource(
  sourceUrl: string,
  options: V3KnowledgeSourceFetchOptions = {},
): Promise<{ bytes: Uint8Array; mediaType: string }> {
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  const resolveHost = options.resolveHost ?? defaultResolveHost;
  const timeoutMs = options.timeoutMs ?? 30_000;
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_SOURCE_BYTES;
  let url = await assertPublicUrl(sourceUrl, resolveHost);
  for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
    const response = await fetcher(url, {
      method: 'GET',
      redirect: 'manual',
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      headers: {
        accept: 'text/html,text/plain,text/markdown,application/xhtml+xml,application/json;q=0.9',
        'user-agent': 'QoderWake-Knowledge-Ingestion/3',
      },
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(timeoutMs)])
        : AbortSignal.timeout(timeoutMs),
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get('location');
      if (!location || redirect === MAX_REDIRECTS) throw new Error('Knowledge source redirect is invalid');
      url = await assertPublicUrl(new URL(location, url).href, resolveHost);
      continue;
    }
    if (!response.ok) throw new Error(`Knowledge source returned HTTP ${response.status}`);
    return {
      bytes: await readBounded(response, maxBytes),
      mediaType: response.headers.get('content-type') ?? '',
    };
  }
  throw new Error('Knowledge source redirect limit exceeded');
}

function decodeEntities(value: string): string {
  const named: Readonly<Record<string, string>> = {
    amp: '&',
    apos: "'",
    gt: '>',
    lt: '<',
    nbsp: ' ',
    quot: '"',
  };
  return value.replace(/&(?:#(\d+)|#x([\da-f]+)|([a-z]+));/giu, (entity, decimal, hexadecimal, name) => {
    const point = decimal ? Number(decimal) : hexadecimal ? Number.parseInt(hexadecimal, 16) : undefined;
    if (point !== undefined && Number.isInteger(point) && point > 0 && point <= 0x10ffff) {
      return String.fromCodePoint(point);
    }
    return named[String(name).toLowerCase()] ?? entity;
  });
}

function normalizedCompiledText(value: string, emptyMessage: string): string {
  const normalized = value
    .replace(/\r\n?/gu, '\n')
    .replace(/[\t\f\v ]+/gu, ' ')
    .replace(/ *\n */gu, '\n')
    .replace(/\n{3,}/gu, '\n\n')
    .trim();
  if (!normalized) throw new Error(emptyMessage);
  return normalized;
}

export function knowledgeHtmlTitle(bytes: Uint8Array, mediaTypeHeader: string): string | undefined {
  const mediaType = mediaTypeHeader.split(';')[0]!.trim().toLowerCase();
  if (mediaType !== 'text/html' && mediaType !== 'application/xhtml+xml') return undefined;
  const html = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  const raw = /<title\b[^>]*>([^]*?)<\/title>/iu.exec(html)?.[1];
  if (!raw) return undefined;
  const title = decodeEntities(
    raw
      .replace(/<[^>]+>/gu, ' ')
      .replace(/\s+/gu, ' ')
      .trim(),
  );
  return title ? title.slice(0, 500) : undefined;
}

export function compileKnowledgeText(bytes: Uint8Array, mediaTypeHeader: string): string {
  const mediaType = mediaTypeHeader.split(';')[0]!.trim().toLowerCase();
  if (
    ![
      'text/plain',
      'text/markdown',
      'text/csv',
      'text/html',
      'application/xhtml+xml',
      'application/json',
      'image/svg+xml',
    ].includes(mediaType)
  ) {
    throw new Error(`Unsupported Knowledge source media type: ${mediaType || 'missing'}`);
  }
  let text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  if (mediaType === 'application/json') {
    try {
      text = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      throw new Error('Knowledge JSON source is invalid');
    }
  } else if (
    mediaType === 'text/html' ||
    mediaType === 'application/xhtml+xml' ||
    mediaType === 'image/svg+xml'
  ) {
    text = text
      .replace(/<head\b[^>]*>[^]*?<\/head>/giu, ' ')
      .replace(/<title\b[^>]*>[^]*?<\/title>/giu, ' ')
      .replace(/<!--[^]*?-->/gu, ' ')
      .replace(/<(script|style|noscript)\b[^>]*>[^]*?<\/\1>/giu, ' ')
      .replace(
        /<\/?(?:p|div|section|article|header|footer|main|aside|nav|h[1-6]|li|tr|br|hr)\b[^>]*>/giu,
        ' ',
      )
      .replace(/<[^>]+>/gu, ' ');
    text = decodeEntities(text);
  }
  return normalizedCompiledText(text, 'Knowledge source contains no indexable text');
}

const OFFICE_TYPE_BY_EXTENSION: Readonly<Partial<Record<string, SupportedFileType>>> = {
  '.csv': 'csv',
  '.docx': 'docx',
  '.html': 'html',
  '.htm': 'html',
  '.markdown': 'md',
  '.md': 'md',
  '.pdf': 'pdf',
  '.pptx': 'pptx',
  '.xlsx': 'xlsx',
};

const IMAGE_MEDIA_TYPES = new Set(['image/bmp', 'image/gif', 'image/jpeg', 'image/png', 'image/webp']);

async function recognizeImage(bytes: Uint8Array, signal?: AbortSignal): Promise<string> {
  if (signal?.aborted) throw new DOMException('Knowledge file parsing was cancelled', 'AbortError');
  const worker = await createWorker(['eng', 'chi_sim']);
  const abort = () => void worker.terminate();
  signal?.addEventListener('abort', abort, { once: true });
  try {
    const result = await worker.recognize(Buffer.from(bytes));
    return normalizedCompiledText(result.data.text, 'Knowledge image contains no indexable text');
  } finally {
    signal?.removeEventListener('abort', abort);
    await worker.terminate().catch(() => undefined);
  }
}

function compileLegacyOffice(
  bytes: Uint8Array,
  extension: '.doc' | '.xls' | '.ppt',
  signal?: AbortSignal,
): string {
  if (signal?.aborted) throw new DOMException('Knowledge file parsing was cancelled', 'AbortError');
  const document = new WasmDocument(bytes, extension.slice(1));
  try {
    const text = document.plainText();
    if (signal?.aborted) throw new DOMException('Knowledge file parsing was cancelled', 'AbortError');
    return normalizedCompiledText(text, 'Knowledge file contains no indexable text');
  } finally {
    document.free();
  }
}

export async function compileKnowledgeFile(
  bytes: Uint8Array,
  fileName: string,
  mediaTypeHeader: string,
  signal?: AbortSignal,
): Promise<string> {
  const mediaType = mediaTypeHeader.split(';')[0]!.trim().toLowerCase();
  const extension = extname(fileName).toLowerCase();
  if (extension === '.eml' && mediaType === 'message/rfc822') {
    if (signal?.aborted) throw new DOMException('Knowledge file parsing was cancelled', 'AbortError');
    const email = await parseKnowledgeEmail(bytes, fileName);
    if (signal?.aborted) throw new DOMException('Knowledge file parsing was cancelled', 'AbortError');
    return normalizedCompiledText(email.indexText, 'Knowledge email contains no indexable text');
  }
  if (mediaType === 'text/plain' || mediaType === 'image/svg+xml') {
    return compileKnowledgeText(bytes, mediaType);
  }
  if (IMAGE_MEDIA_TYPES.has(mediaType)) return recognizeImage(bytes, signal);
  if (extension === '.doc' || extension === '.xls' || extension === '.ppt') {
    return compileLegacyOffice(bytes, extension, signal);
  }
  const fileType = OFFICE_TYPE_BY_EXTENSION[extension];
  if (!fileType) throw new Error(`Unsupported Knowledge file parser for ${extension || mediaType}`);
  const ast = await OfficeParser.parseOffice(bytes, {
    fileType,
    abortSignal: signal ?? null,
    extractAttachments: false,
    ocr: false,
    decompressionLimits: {
      maxUncompressedBytes: 512 * 1024 * 1024,
      maxZipEntries: 10_000,
    },
  });
  const converted = await ast.to('text', {
    includeImages: false,
    textConfig: { preserveLayout: true, renderNotes: true },
  });
  if (typeof converted.value !== 'string') throw new Error('Knowledge parser returned invalid text');
  return normalizedCompiledText(converted.value, 'Knowledge file contains no indexable text');
}
